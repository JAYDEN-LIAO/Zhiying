"""
pipeline/runners/ocr.py
═══════════════════════════════════════════════════════════
OCR 画面文字提取 runner — 独立感知模块（v0.34）。

depends_on=["duration"]，自抽高清帧（原分辨率 / max_width 缩小 / scale 放大，走 CPU），
识别结果落 ocr_detections 表。与摘要/检测路径完全解耦：
OCR 模式关掉 summary+search_index 后 DAG 退化为 duration→ocr，零索引开销。

滑动/滚动场景处理：
  - 采样率由 sample_fps 控制（聊天建议 2-3fps；静止截图可降到 1）
  - 内容去重：归一化文本一致 + 近窗内只保留最优一次（更长/更高置信度），
    窗口外重现视为新一次（两条都保留），顺带治好"同一条消息反复读到 / 半截字 /
    滚动糊读"三类重复；最终按时间戳 + 框位升序输出 → 阅读顺序
"""

import asyncio
import logging
from difflib import SequenceMatcher

import cv2
import numpy as np

from pipeline.runners.base import OperationRunner, PipelineContext
from core.search import _normalize_plate as _normalize_text

logger = logging.getLogger(__name__)

# OCR 去重阈值默认值（可被 config plugins.ocr.params 覆盖，见 docs/ocr.md）。
# static_frames:    帧；文本连续静止 ≥ 此帧数 → 判固定 HUD（顶部时间/状态栏，只读一遍）。
# static_move_eps:  归一化；固定文字允许的 bbox 中心位移上限（纹丝不动才算固定）。
_DEFAULT_PARAMS = {
    "static_frames": 3,
    "static_move_eps": 0.02,
}


def _center(row: dict) -> tuple[float, float]:
    b = row.get("bbox") or {}
    return (
        (float(b.get("x1", 0.0)) + float(b.get("x2", 0.0))) / 2.0,
        (float(b.get("y1", 0.0)) + float(b.get("y2", 0.0))) / 2.0,
    )


def _dist(a: tuple[float, float], bx: tuple[float, float]) -> float:
    return ((a[0] - bx[0]) ** 2 + (a[1] - bx[1]) ** 2) ** 0.5


# 模糊合并判据（宁缺毋滥，防误并真正不同的句子）：
#   _FUZZ_MIN_LEN    : 参与模糊合并的最短长度（< 此值只靠精确匹配/子串，防"别卷/别卷我"误并）
#   _FUZZ_SUBSTRING  : 子串包含（半截→完整，如"这是我的邀请码"⊂"这是我的邀请码用了..."），安全强合并
#   _FUZZ_RATIO      : 非子串但字符级相似度 ≥ 此值（如"8月138"/"8月13日"、"ifcloud"/"jfcloud"）
_FUZZ_MIN_LEN = 3
_FUZZ_RATIO = 0.79


def _fuzzy_key(keys: set[str], norm: str) -> str | None:
    """在已有 key 集合里找 norm 的"相似/包含"合并目标，找不到返回 None。

    策略（宁缺毋滥，防误并真正不同的句子）：
      1) 子串包含：短串 ⊂ 长串（半截→完整，如"这是我的邀请码"⊂"这是我的邀请码用了..."）
         → 直接命中（强合并）。已有"别卷"这类短串也满足子串，靠 _FUZZ_MIN_LEN 挡住：
         仅当 len(目标串)>=_FUZZ_MIN_LEN 才做子串判定（"别卷"长 2 < 3，不参与 → 不与"别卷我"并）。
      2) 非子串：diff 相似度 ratio >= _FUZZ_RATIO（如"8月138"/"8月13日"、"ifcloud"/"jfcloud"）
         → 取相似度最高者。同样要求 norm 与目标都足够长（≥ _FUZZ_MIN_LEN），防两字词误并。
    """
    if len(norm) < _FUZZ_MIN_LEN:
        return None
    best: str | None = None
    best_ratio = _FUZZ_RATIO
    for k in keys:
        if k == norm:
            continue
        # 子串包含（双向，如"这是我的邀请码"⊂"这是我的邀请码用了..."）→ 强合并。
        # 要求较短一方 ≥ _FUZZ_MIN_LEN：挡住"别卷"(2)⊂"别卷我"(3) 这类短词误并。
        short = norm if len(norm) <= len(k) else k
        if norm in k or k in norm:
            if len(short) >= _FUZZ_MIN_LEN:
                return k
            continue
        if len(k) < _FUZZ_MIN_LEN:
            continue
        r = SequenceMatcher(None, norm, k).ratio()
        if r >= best_ratio:
            best, best_ratio = k, r
    return best


def _dedup_tracklets(
    video_id: str,
    sampled: list[tuple[float, list[dict]]],
    static_frames: int = int(_DEFAULT_PARAMS["static_frames"]),
    static_move_eps: float = _DEFAULT_PARAMS["static_move_eps"],
) -> list[dict]:
    """把逐帧 OCR 行序列合并成流畅文字流 → 最终落库行列表。

    基于实测（ocr.mp4 + ocr.txt 基准）：这是垂直滚动聊天面板，同一条文本随
    滚动出现在多帧（y 连续变化），即使暂时滚出视野再出现仍是同一条。
    故采用**全局文本合并**：同一归一化文本全视频合并成一条，不做位置跳变拆分、
    不做短窗拆分（旧逻辑会把「别卷我」这类跨窗重现拆成两条）。

    规则：
      - 同文本 = 同一条：取最佳读取（score=len*2+conf 最高）做代表行，时间钉**首现**；
      - static-hold：同文本连续 static_frames 帧位移 < static_move_eps（顶部
        时间/状态栏，如「已备餐」「11:15」）→ 判固定文字，只保留首次一次；
      - 最终按 (timestamp_sec, bbox.y1, bbox.x1) 升序输出 → 阅读顺序。
    """
    # 全局文本合并：key=norm_text → 一条聚合记录。
    #   实测（ocr.mp4 + ocr.txt 基准）：这是垂直滚动聊天面板，同一条文本随滚动
    #   出现在多帧（y 连续变化），即使暂时滚出视野再出现（跨 5s+）仍是同一条。
    #   故不做"位置跳变拆分"或"5s 短窗拆分"（旧逻辑会把「别卷我」拆成两条）——
    #   改为同文本全局合并为一条。
    #   固定文字（顶部已备餐/时间/百分比，y 全程不动）走 static-hold 只读一遍。
    #   static_frames: 连续静止 ≥ 此帧数判为固定（覆盖整段滚动不被误拆）。
    #   first_ts/代表行: 用最佳读取（score 最高）做代表行，但时间钉在首现帧。
    active: dict[str, dict] = {}
    # static 判定：同文本在连续 static_frames 帧内位移 < static_move_eps → 固定
    static_track: dict[str, int] = {}        # norm -> 连续静止帧数
    for ts, lines in sampled:
        for line in lines:
            text = (line.get("text") or "").strip()
            if not text:
                continue
            norm = _normalize_text(text)
            if not norm:
                continue
            row = OcrRunner._make_row(video_id, ts, line)
            center = _center(row)
            score = len(text) * 2.0 + float(line.get("confidence", 0.0))

            tr = active.get(norm)
            if tr is None:
                # 无完全相等的 key → 模糊匹配已有 key（半截→完整、近似误读）合并，不新建
                fk = _fuzzy_key(set(active), norm)
                if fk is not None:
                    tr = active[fk]
                    # 合并：该文本的半截/变体，更新延续帧，若更完整/更优则升级代表行
                    tr["last_ts"] = ts
                    tr["last_center"] = center
                    if score > tr["best_score"]:
                        tr["best_score"] = score
                        tr["best_row"] = row
                        tr["best_row"]["timestamp_sec"] = round(tr["first_ts"], 2)
                    continue
                active[norm] = {
                    "first_ts": ts, "last_ts": ts, "last_center": center,
                    "first_y": row.get("bbox", {}).get("y1", 0.0),
                    "first_x": row.get("bbox", {}).get("x1", 0.0),
                    "static": False, "best_score": score, "best_row": row,
                }
                # 首帧也算一次静止（连续计数起点）
                static_track[norm] = 1
                continue

            disp = _dist(center, tr["last_center"])
            if disp < static_move_eps:
                static_track[norm] = static_track.get(norm, 0) + 1
            else:
                static_track[norm] = 0  # 动了 → 非固定

            # 已判固定：只保留首次读取一次，后续同文本直接忽略（不重复）
            if tr["static"]:
                continue
            # 刚达固定阈值：冻结首次最佳读取，后续忽略
            if static_track[norm] >= static_frames:
                tr["static"] = True
                tr["last_ts"] = ts
                continue

            # 动态滚动消息：同文本全局合并，取最佳读取，时间钉首现
            tr["last_ts"] = ts
            tr["last_center"] = center
            if score > tr["best_score"]:
                tr["best_score"] = score
                tr["best_row"] = row
                tr["best_row"]["timestamp_sec"] = round(tr["first_ts"], 2)

    # 子串收敛：完整句可能是多条半截 key 的公共超串（如「这是我的邀请码」+「用了直接...
    # 三十五块的」⊂「这是我的邀请码用了直接多三十五块的余」），而流式模糊合并只吸收其一，
    # 需把互为子串的 key 归并到最长者——取更完整文本做代表，时间/位置保留最早（首现）。
    keys = list(active.keys())
    for i in range(len(keys)):
        longer = keys[i]
        if longer not in active:
            continue
        for j in range(len(keys)):
            if i == j or keys[j] not in active:
                continue
            short_k, long_k = (keys[j], longer) if len(keys[j]) <= len(longer) else (longer, keys[j])
            if len(short_k) < _FUZZ_MIN_LEN:
                continue
            if short_k in long_k:
                dst, src = active[long_k], active[short_k]
                # 归并到较长 key：代表行取更优者，但时间/位置保留最早首现
                if dst["best_score"] < src["best_score"]:
                    dst["best_row"] = src["best_row"]
                    dst["best_row"]["timestamp_sec"] = round(dst["first_ts"], 2)
                    dst["best_score"] = src["best_score"]
                if src["first_ts"] < dst["first_ts"]:
                    dst["first_ts"] = src["first_ts"]
                    dst["first_y"] = src["first_y"]
                    dst["first_x"] = src["first_x"]
                del active[short_k]
    # 顺序用**首现位置**（first_y/first_x），而非代表行的 bbox——代表行取"最佳读取帧"
    # 的位置可能已随滚动变化，用它排序会颠乱屏幕阅读顺序（如「评价给到npc吧」被错排到
    # 「梦男来了」前）。首现位置反映该条实际入屏位置，才是正确阅读序。
    tracks = sorted(active.values(),
                    key=lambda tr: (tr["first_ts"], tr["first_y"], tr["first_x"]))
    results = [tr["best_row"] for tr in tracks]
    return results


class OcrRunner(OperationRunner):
    """OCR 文字提取执行器。"""

    async def run(self, pctx: PipelineContext) -> None:
        ocr_plugin = pctx.plugins.get("ocr")
        if ocr_plugin is None:
            logger.info("[OcrRunner] No ocr plugin, skipping")
            return

        duration = pctx.ctx.duration or 0.0
        if duration <= 0:
            logger.info("[OcrRunner] No duration, skipping")
            return

        video_id = str(pctx.video.id)
        ocr_params = (pctx.config.get("plugins", {}).get("ocr", {}) or {}).get("params", {}) or {}
        sample_fps = float(ocr_params.get("sample_fps", 2.0) or 2.0)
        max_width = ocr_params.get("max_width")           # None = 原分辨率
        scale = float(ocr_params.get("scale", 1.0) or 1.0)
        use_nvdec = bool((pctx.config.get("pipeline", {}) or {}).get("use_nvdec", False))
        # 去重阈值（可被 config plugins.ocr.params 覆盖，见 docs/ocr.md）
        static_frames = int(ocr_params.get("static_frames", _DEFAULT_PARAMS["static_frames"]))
        static_move_eps = float(ocr_params.get("static_move_eps", _DEFAULT_PARAMS["static_move_eps"]))

        from utils.video_util import stream_frames

        await pctx.tracker.update("ocr", sub_progress=0.0, description="画面文字提取中")

        total = max(1, int(duration * sample_fps))
        frame_idx = 0
        sampled: list[tuple[float, list[dict]]] = []  # (ts, 该帧原始 OCR 行) — 流式收集，末尾统一去重排序

        try:
            async for frame in stream_frames(
                pctx.ctx.file_path,
                fps=sample_fps,
                use_nvdec=use_nvdec,
                total_frames=total,
            ):
                ts = pctx.ctx.start_time + frame_idx / sample_fps
                frame_idx += 1

                try:
                    prepared = await self._prepare_frame(frame, max_width, scale)
                    if prepared is None:
                        continue
                    lines = await ocr_plugin.extract(prepared)
                except Exception as e:
                    # 单帧容错：一帧失败不拖垮管道（照 v0.33 caption 降级思路）
                    logger.warning("[OcrRunner] frame @ %.1fs OCR failed: %s", ts, e)
                    continue

                sampled.append((ts, lines))

                if frame_idx % 10 == 0:
                    await pctx.tracker.update(
                        "ocr", sub_progress=min(0.99, frame_idx / total),
                    )
        except Exception as e:
            logger.warning("[OcrRunner] stream aborted at frame %d: %s", frame_idx, e)

        pctx.ctx.ocr_detections = _dedup_tracklets(
            video_id, sampled,
            static_frames=static_frames,
            static_move_eps=static_move_eps,
        )

        await pctx.tracker.update("ocr", sub_progress=1.0)
        logger.info(
            "[OcrRunner] Done: %d OCR detections (sampled %.1f fps, %.1fs)",
            len(pctx.ctx.ocr_detections), sample_fps, duration,
        )
        if pctx.log:
            await pctx.log(
                f"文字识别完成：{len(pctx.ctx.ocr_detections)} 条文字（采样 {sample_fps} fps）"
            )

    # ── 内部 ──

    @staticmethod
    def _make_row(video_id: str, ts: float, line: dict) -> dict:
        """组装 ocr_detections 行。bbox 为插件透传的归一化坐标。"""
        return {
            "video_id": video_id,
            "timestamp_sec": round(ts, 2),
            "text": (line.get("text") or "").strip(),
            "bbox": line.get("bbox", {"x1": 0, "y1": 0, "x2": 0, "y2": 0}),
            "confidence": float(line.get("confidence", 0.0)),
        }

    @staticmethod
    async def _prepare_frame(
        frame: np.ndarray,
        max_width: int | None,
        scale: float,
    ) -> np.ndarray | None:
        """按 max_width（缩小上限）与 scale（小字放大）调整帧分辨率。

        低采样率（1-2fps）下每帧 resize 开销可忽略；同步 cv2 调用包 to_thread。
        """
        if frame is None or frame.size == 0:
            return None
        h, w = frame.shape[:2]
        eff_w = w * scale
        eff_h = h * scale
        if max_width and eff_w > max_width:
            ratio = max_width / eff_w
            eff_w *= ratio
            eff_h *= ratio
        target_w, target_h = int(eff_w), int(eff_h)
        if (target_w, target_h) == (w, h) or target_w <= 0 or target_h <= 0:
            return frame
        return await asyncio.to_thread(
            cv2.resize, frame, (target_w, target_h),
            None, 0.0, 0.0, cv2.INTER_CUBIC,
        )