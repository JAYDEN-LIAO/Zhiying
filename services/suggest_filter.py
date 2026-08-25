"""搜索结果筛选类别智能推荐 — 基于 embedder 文本-文本相似度（无需联网/新模型）。

复用项目已有的 Qwen3-VL Embedder 与 smart_suggest（services/smart_suggest.py）成熟模式：
  - 用户搜索词 → embedder.encode_text() 得文本向量
  - 与预置两组文本（frame 事件/动作/语义组、track 物体组）算余弦相似度
  - 组内取 max、组间比较差值 → 判定默认筛选：all（不确定）/ frame（画面定位）/ track（物体定位）

只做纯文本匹配（无抽帧、无图像编码），一次前向即可，耗时毫秒级。
"""

import asyncio
import hashlib
import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# 结果筛选类别 key（与前端 resultFilter 对齐）：
#   all    → 全部（无法判断/不确定时保持用户当前选择）
#   frame  → 画面定位（search_types=["frame"]）——事件/动作/场景/语义类
#   track  → 物体定位（search_types=["track"]）——单个物体类
FILTER_ALL = "all"
FILTER_FRAME = "frame"
FILTER_TRACK = "track"

# 判定阈值（经验值，文本-文本相似度一般高于文本-图像；后续可按实测微调）：
#  - 最高组相似度必须 ≥ FRAME/TRACK 的绝对下界，且与次高组差值 ≥ DIFF，才判为确定类别
#  - 否则返回 all（保持用户手动选择，不打扰）
LOW_CONFIDENCE_THRESHOLD = 0.35   # 组内最高相似度下界
DECISION_DIFF = 0.08              # 最佳组与次优组的相似度差值门槛


# 预置文本组：每组多条中英文短语作为独立锚点（组内取 max 相似度）。
# 每条锚点语义要「单一紧致」（2~4 个相关词或一个完整短语），避免把互不相关词汇
# 揉进一条导致向量被稀释。frame = 事件/动作/场景/语义类 → 默认画面定位。
FRAME_TEXTS: list[str] = [
    "画面里正在发生的事件或动作场景",
    "events or actions happening in the scene",
    "求婚",
    "propose marriage wedding ceremony",
    "打架斗殴",
    "fighting brawling shoving",
    "推搡冲突争吵",
    "pushing shoving conflict quarrel",
    "翻墙攀爬越界",
    "climbing over a wall fence",
    "两车相撞追尾车祸",
    "two cars crashing rear-end accident",
    "奔跑追逐",
    "running chasing fleeing",
    "摔倒倒地",
    "falling down on the ground",
    "挥手聚集人群涌入",
    "waving gathering crowd rushing in",
    "人离开画面",
    "someone leaving the frame",
    "跳舞",
    "dancing",
]

# track = 单个物体类 → 默认物体定位
TRACK_TEXTS: list[str] = [
    "画面中某一个具体的物体或单个人",
    "a specific single object or person in the frame",
    "黑色车辆",
    "black car",
    "白色轿车",
    "white sedan",
    "出租车",
    "taxi",
    "黄色卡车",
    "yellow truck",
    "摩托车",
    "motorcycle bicycle cyclist",
    "穿红色衣服的人",
    "person wearing red clothes",
    "戴口罩的人",
    "person wearing a mask",
    "戴眼镜的男子",
    "man wearing glasses",
    "行人骑自行车的人",
    "pedestrian person on a bicycle",
]


def _norm(v: Any) -> np.ndarray | None:
    arr = np.asarray(v, dtype=np.float32)
    n = float(np.linalg.norm(arr))
    if n == 0:
        return None
    return arr / n


class SuggestFilterService:
    """搜索结果筛选类别推荐服务（进程内单例缓存预置文本向量）。"""

    def __init__(self) -> None:
        self._frame_vecs: list[np.ndarray] | None = None
        self._track_vecs: list[np.ndarray] | None = None
        self._cache_key: str | None = None
        self._lock = asyncio.Lock()

    def _fingerprint(self) -> str:
        parts: list[str] = []
        parts.extend(FRAME_TEXTS)
        parts.extend(TRACK_TEXTS)
        return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]

    async def _ensure_vecs(self, embedder) -> None:
        fp = self._fingerprint()
        if self._frame_vecs is not None and self._track_vecs is not None and self._cache_key == fp:
            return
        async with self._lock:
            if self._frame_vecs is not None and self._track_vecs is not None and self._cache_key == fp:
                return
            try:
                batch = await asyncio.wait_for(
                    embedder.encode_texts_batch(FRAME_TEXTS + TRACK_TEXTS),
                    timeout=90.0,
                )
                f = [v for v in (_norm(x) for x in batch[: len(FRAME_TEXTS)]) if v is not None]
                t = [v for v in (_norm(x) for x in batch[len(FRAME_TEXTS):]) if v is not None]
                if f and t:
                    self._frame_vecs, self._track_vecs = f, t
                    self._cache_key = fp
                    logger.info("[SuggestFilter] cached %d frame + %d track text vecs", len(f), len(t))
            except Exception as e:
                logger.warning("[SuggestFilter] text batch encode failed: %s", e)

    async def suggest(self, embedder, query: str) -> dict[str, Any]:
        """给定搜索词，返回 { filter: all|frame|track, score: {...} }。"""
        q = (query or "").strip()
        if not q or embedder is None:
            return {"filter": FILTER_ALL, "scores": {}}

        await self._ensure_vecs(embedder)
        if not self._frame_vecs or not self._track_vecs:
            return {"filter": FILTER_ALL, "scores": {}}

        try:
            qv = await asyncio.wait_for(embedder.encode_text(q), timeout=30.0)
        except Exception as e:
            logger.warning("[SuggestFilter] query encode failed: %s", e)
            return {"filter": FILTER_ALL, "scores": {}}
        qv = _norm(qv)
        if qv is None:
            return {"filter": FILTER_ALL, "scores": {}}

        frame_score = float(max(np.dot(qv, v) for v in self._frame_vecs))
        track_score = float(max(np.dot(qv, v) for v in self._track_vecs))

        best, best_key = (frame_score, FILTER_FRAME) if frame_score >= track_score else (track_score, FILTER_TRACK)
        second = track_score if best_key == FILTER_FRAME else frame_score

        if best >= LOW_CONFIDENCE_THRESHOLD and best - second >= DECISION_DIFF:
            result = best_key
        else:
            result = FILTER_ALL

        return {
            "filter": result,
            "scores": {"frame": round(frame_score, 4), "track": round(track_score, 4)},
        }
