"""智能参数推荐 — 基于 embedder zero-shot 视频场景分类（无需联网/新模型）。

复用项目已有的 Qwen3-VL Embedder：
  - 视频抽 3 帧（开头/中间/结尾）
  - 每帧调用 embedder.encode_image() 得图像向量
  - 每条场景描述调用 embedder.encode_text() 得文本向量
  - 余弦相似度 → 3 帧 majority voting → top-1 场景
  - 场景映射到推荐参数（含 confidence）
"""

import asyncio
import logging
import subprocess
import uuid
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# 场景类别定义：每个场景包含中英文双语描述（中英文向量合并提升鲁棒性）
SCENE_CLASSES: list[dict[str, Any]] = [
    {
        "key": "traffic",
        "label": "交通监控",
        "texts": [
            "道路上行驶的车辆监控画面，主要是汽车车流",
            "traffic monitoring road vehicles cars driving",
            "十字路口汽车和车辆川流不息",
        ],
        "params": {"detection_enabled": True, "face_enabled": False, "plate_enabled": True, "ocr_enabled": False, "search_index_enabled": True, "summary_enabled": False},
    },
    {
        "key": "vehicle_focus",
        "label": "车辆特写",
        "texts": [
            "机动车特写追踪，画面中央是一辆车",
            "vehicle close-up tracking a car in the center",
        ],
        "params": {"detection_enabled": True, "face_enabled": False, "plate_enabled": True, "ocr_enabled": False, "search_index_enabled": True, "summary_enabled": False},
    },
    {
        "key": "surveillance_people",
        "label": "人流监控",
        "texts": [
            "监控画面中多人走动，人员密集",
            "crowd surveillance many people walking in a monitored space",
            "商场或车站人流监控，镜头中有很多人",
        ],
        "params": {"detection_enabled": True, "face_enabled": True, "plate_enabled": False, "ocr_enabled": False, "search_index_enabled": True, "summary_enabled": False},
    },
    {
        "key": "indoor",
        "label": "室内人物",
        "texts": [
            "室内人物会议场景，几个人围坐交谈",
            "indoor people meeting scene several people sitting talking",
            "多人出现在房间里",
        ],
        "params": {"detection_enabled": True, "face_enabled": True, "plate_enabled": False, "ocr_enabled": False, "search_index_enabled": True, "summary_enabled": False},
    },
    {
        "key": "portrait_focus",
        "label": "人物特写",
        "texts": [
            "人物特写肖像，一个人脸占据画面主体",
            "portrait close-up person face fills the frame",
            "综艺节目舞台上的主持人或嘉宾",
        ],
        "params": {"detection_enabled": True, "face_enabled": True, "plate_enabled": False, "ocr_enabled": False, "search_index_enabled": True, "summary_enabled": False},
    },
    {
        "key": "document",
        "label": "文档/屏幕",
        "texts": [
            "文档屏幕 PPT 文字画面",
            "document screen text presentation",
            "电脑屏幕上的文档或幻灯片",
        ],
        "params": {"detection_enabled": False, "face_enabled": False, "plate_enabled": False, "ocr_enabled": True, "search_index_enabled": False, "summary_enabled": False},
    },
    {
        "key": "street_mixed",
        "label": "街景混合",
        "texts": [
            "户外街景同时有行人和车辆",
            "outdoor street scene with both pedestrians and vehicles",
        ],
        "params": {"detection_enabled": True, "face_enabled": True, "plate_enabled": True, "ocr_enabled": False, "search_index_enabled": True, "summary_enabled": False},
    },
    {
        "key": "outdoor_landscape",
        "label": "室外空旷/风景",
        "texts": [
            "空旷的室外风景，天空田野或城市远景",
            "outdoor open landscape sky field city skyline",
            "无人机航拍风景或户外自然景色",
        ],
        "params": {"detection_enabled": True, "face_enabled": False, "plate_enabled": False, "ocr_enabled": False, "search_index_enabled": True, "summary_enabled": False},
    },
    {
        "key": "chat_screen",
        "label": "聊天记录录屏",
        "texts": [
            "聊天记录屏幕录制，手机聊天应用界面",
            "chat log screen recording mobile chat app interface",
            "手机屏幕上有微信聊天窗口和文字消息",
        ],
        "params": {"detection_enabled": False, "face_enabled": False, "plate_enabled": False, "ocr_enabled": True, "search_index_enabled": False, "summary_enabled": False},
    },
]

# 置信度阈值：低于此值视为不确定（前端弹窗标记"建议确认"）。
# 偏低一点以尽量让每个视频都能命中一个场景；命中不了的仍走 _DEFAULT_PARAMS 兜底。
LOW_CONFIDENCE_THRESHOLD = 0.30

# 兜底参数：低置信/无法归类时仍给保守推荐，保证"每个视频都有参数产出"。
# 保守默认：开物体检测与搜索索引，关人脸/车牌/OCR（最通用，避免误开昂贵模块）。
_DEFAULT_PARAMS: dict[str, Any] = {
    "detection_enabled": True,
    "face_enabled": False,
    "plate_enabled": False,
    "ocr_enabled": False,
    "search_index_enabled": True,
    "summary_enabled": False,
}


def _default_suggestion(
    video_id: str,
    reason: str,
    confidence: float = 0.0,
    all_scores: dict | None = None,
) -> dict:
    """兜底推荐：低置信/失败时仍返回保守参数，保证每个视频都有参数产出。

    始终带 params（_DEFAULT_PARAMS），前端可逐项编辑并一键应用；scene_key=None
    表示未命中明确场景，前端据此标记"低置信/默认"。
    """
    return {
        "video_id": video_id,
        "scene_key": None,
        "scene_label": None,
        "confidence": round(confidence, 4),
        "params": dict(_DEFAULT_PARAMS),
        "all_scores": {k: round(v, 4) for k, v in (all_scores or {}).items()},
        "reason": reason,
    }


def _extract_frames(video_path: str, duration: float) -> list[bytes]:
    """抽 3 帧（开头/中间/结尾），返回 JPEG bytes 列表（失败返回 []）。

    asyncio.to_thread 中调用：阻塞子进程。逐点 input-seek（快速关键帧定位），
    每个时间戳一个进程，避免长视频整段解码（output 侧 -ss 会 1.5× 全量解码而超时）。
    """
    if duration <= 0:
        # 拿不到时长直接抽开头一帧
        times = [0.0]
    else:
        times = [0.0, max(0.0, duration * 0.5), max(0.1, duration - 0.1)]
    return _extract_frames_seek(video_path, times)


def _extract_frames_seek(video_path: str, times: list[float]) -> list[bytes]:
    """逐点 input-seek 抽帧 — 每帧一个快速 seek 进程（input -ss 关键帧定位，快）。"""
    frames: list[bytes] = []
    for t in times:
        try:
            cmd = [
                "ffmpeg",
                "-y", "-loglevel", "error",
                "-ss", f"{t:.2f}",
                "-i", video_path,
                "-vframes", "1",
                "-q:v", "5",
                "-f", "image2pipe",
                "-vcodec", "mjpeg",
                "pipe:1",
            ]
            out = subprocess.run(cmd, capture_output=True, timeout=5).stdout
            if out:
                frames.append(out)
        except subprocess.TimeoutExpired:
            logger.warning("[SmartSuggest] ffmpeg frame extract timeout t=%.2f", t)
        except Exception as e:
            logger.warning("[SmartSuggest] ffmpeg frame extract failed at t=%.2f: %s", t, e)
    return frames


_SCENE_TEXT_CACHE: dict[str, np.ndarray] | None = None
_SCENE_TEXT_CACHE_KEY: str | None = None
_SCENE_TEXT_LOCK = asyncio.Lock()
# 场景文本一次批量编码的超时（GPU 卡住时避免无限阻塞单视频路径）
_SCENE_TEXT_ENCODE_TIMEOUT = 90.0


def _scene_fingerprint() -> str:
    """SCENE_CLASSES 内容指纹 — 场景增改时场景文本缓存自动失效。"""
    import hashlib
    parts: list[str] = []
    for s in SCENE_CLASSES:
        parts.append(s["key"])
        parts.extend(s["texts"])
        parts.append(repr(sorted(s["params"].items())))
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]


def _embedder_cache_key(embedder) -> str:
    """生成稳定的缓存键 —— 基于模型身份 + 编码配置 + 场景指纹，而非 id(embedder)。

    避免 embedder 实例被 GC 后新对象复用同一 id 导致用到旧缓存/旧维度向量；
    场景列表增改（指纹变化）也会让缓存失效重编码。
    """
    proc = getattr(embedder, "processor", None)
    name = getattr(proc, "name_or_path", None)
    if not name:
        name = getattr(embedder, "model_name", None) or repr(embedder)
    size = getattr(embedder, "encode_size", None)
    quant = getattr(embedder, "_quantization", "")
    return f"{name}|{size}|{quant}|scene:{_scene_fingerprint()}"


async def _get_scene_text_vecs(embedder) -> dict[str, np.ndarray]:
    """缓存场景文本向量 — 同一进程内只编码一次（中英文向量合并）。

    使用 asyncio.Lock 保证单事件循环协程安全；embedder 模型/配置变化时清空缓存。
    """
    global _SCENE_TEXT_CACHE, _SCENE_TEXT_CACHE_KEY
    cache_key = _embedder_cache_key(embedder)
    if _SCENE_TEXT_CACHE is not None and _SCENE_TEXT_CACHE_KEY == cache_key:
        return _SCENE_TEXT_CACHE
    async with _SCENE_TEXT_LOCK:
        if _SCENE_TEXT_CACHE is not None and _SCENE_TEXT_CACHE_KEY == cache_key:
            return _SCENE_TEXT_CACHE
        # 一次批量编码所有场景文本（按场景，先中后英合并）
        all_texts: list[str] = []
        per_scene_text_count: list[int] = []
        for scene in SCENE_CLASSES:
            per_scene_text_count.append(len(scene["texts"]))
            all_texts.extend(scene["texts"])

        batch_vecs = None
        try:
            batch_vecs = await asyncio.wait_for(
                embedder.encode_texts_batch(all_texts),
                timeout=_SCENE_TEXT_ENCODE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning("[SmartSuggest] scene text batch encode timeout")
        except Exception as e:
            logger.warning("[SmartSuggest] encode_texts_batch failed: %s; falling back to per-text", e)

        result: dict[str, np.ndarray] = {}
        if batch_vecs:
            cursor = 0
            for scene, count in zip(SCENE_CLASSES, per_scene_text_count):
                vecs = []
                for v in batch_vecs[cursor: cursor + count]:
                    try:
                        arr = np.asarray(v, dtype=np.float32)
                        n = float(np.linalg.norm(arr))
                        if n > 0:
                            vecs.append(arr / n)
                    except Exception as e:
                        logger.warning("[SmartSuggest] bad text vector: %s", e)
                cursor += count
                if vecs:
                    merged = np.mean(vecs, axis=0)
                    n = np.linalg.norm(merged)
                    result[scene["key"]] = merged / n if n > 0 else merged
            logger.info("[SmartSuggest] cached %d scene text vecs via batch", len(result))
        if not result:
            # 兜底：逐个编码（兼容旧 embedder）
            for scene in SCENE_CLASSES:
                vecs: list[np.ndarray] = []
                for txt in scene["texts"]:
                    try:
                        v = await asyncio.wait_for(
                            embedder.encode_text(txt),
                            timeout=_SCENE_TEXT_ENCODE_TIMEOUT,
                        )
                        arr = np.asarray(v, dtype=np.float32)
                        n = np.linalg.norm(arr)
                        if n > 0:
                            vecs.append(arr / n)
                    except Exception:
                        pass
                if vecs:
                    merged = np.mean(vecs, axis=0)
                    n = np.linalg.norm(merged)
                    result[scene["key"]] = merged / n if n > 0 else merged
        _SCENE_TEXT_CACHE = result
        _SCENE_TEXT_CACHE_KEY = cache_key
        return result


def _invalidate_scene_cache() -> None:
    """测试用：清空文本向量缓存（embedder 重载后调用）。"""
    global _SCENE_TEXT_CACHE, _SCENE_TEXT_CACHE_KEY
    _SCENE_TEXT_CACHE = None
    _SCENE_TEXT_CACHE_KEY = None


async def suggest_params_for_video(
    embedder,
    video_id: uuid.UUID,
    video_path: str,
    duration: float,
    text_vecs: dict | None = None,
) -> dict:
    """对单个视频做智能参数推荐。

    text_vecs: 预先共享的场景文本向量（推荐 pass 进来避免重复计算）。
    Returns:
        {
          "video_id": "...",
          "scene_key": "traffic" | None,
          "scene_label": "交通监控" | None,
          "confidence": 0.0 ~ 1.0,
          "params": {...} | None,  # 推荐参数（confidence 低于阈值时为 None）
          "all_scores": { "traffic": 0.8, "indoor": 0.5, ... },  # 全部场景相似度
        }
    """
    if embedder is None:
        return _default_suggestion(str(video_id), "embedder unavailable")

    # 1. 抽 3 帧（线程池跑，避免阻塞事件循环）
    frames = await asyncio.to_thread(_extract_frames, video_path, duration)
    if not frames:
        return _default_suggestion(str(video_id), "frame extract failed")

    # 2. 获取缓存的场景文本向量（多视频共享，一次性编码所有场景）
    if text_vecs is None:
        text_vecs = await _get_scene_text_vecs(embedder)
    if not text_vecs:
        return _default_suggestion(str(video_id), "text encode failed")

    # 3. 把帧转 numpy 数组（每帧)
    arrs: list[np.ndarray] = []
    for frame_bytes in frames:
        try:
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(frame_bytes)).convert("RGB")
            arrs.append(np.asarray(img, dtype=np.uint8))
        except Exception as e:
            logger.warning("[SmartSuggest] frame decode failed: %s", e)

    if not arrs:
        return _default_suggestion(str(video_id), "image decode failed")

    # 4. 批量编码所有帧（一次 GPU 前向，比逐帧快 3-5 倍）
    try:
        vecs_list = await embedder.encode_images_batch(arrs)
    except Exception as e:
        logger.warning("[SmartSuggest] encode_images_batch failed: %s", e)
        return _default_suggestion(str(video_id), "image encode failed")

    # 5. 每帧算相似度
    frame_scores: list[dict[str, float]] = []
    for v in vecs_list:
        v = np.asarray(v, dtype=np.float32)
        n = np.linalg.norm(v)
        if n == 0:
            continue
        v = v / n
        scores = {key: float(np.dot(v, t_vec)) for key, t_vec in text_vecs.items()}
        frame_scores.append(scores)

    if not frame_scores:
        return _default_suggestion(str(video_id), "image encode failed")

    # 4. 3 帧 majority voting：每帧取 top-1，最后取出现最多的
    from collections import Counter
    frame_top1 = [max(s.items(), key=lambda x: x[1])[0] for s in frame_scores]
    vote_count = Counter(frame_top1)
    best_key = vote_count.most_common(1)[0][0]

    # 5. 计算最终置信度 = 该场景在 3 帧中的平均相似度
    avg_scores_by_key: dict[str, float] = {}
    for key in text_vecs.keys():
        avg_scores_by_key[key] = float(np.mean([s.get(key, 0.0) for s in frame_scores]))
    confidence = avg_scores_by_key.get(best_key, 0.0)

    # 6. 低于阈值：给保守兜底参数（scene_key=None 标记低置信），保证有参数产出
    if confidence < LOW_CONFIDENCE_THRESHOLD:
        return _default_suggestion(str(video_id), "low confidence", confidence, avg_scores_by_key)

    best_scene = next(s for s in SCENE_CLASSES if s["key"] == best_key)
    return {
        "video_id": str(video_id),
        "scene_key": best_key,
        "scene_label": best_scene["label"],
        "confidence": round(confidence, 4),
        "params": best_scene["params"],
        "all_scores": {k: round(v, 4) for k, v in avg_scores_by_key.items()},
    }


async def suggest_params_batch(
    embedder,
    videos: list[dict],
) -> list[dict]:
    """批量推荐 — 一次拉全部视频帧 → 整批 image encoder 一次前向 → 复用场景文本缓存。

    videos: [{ video_id, video_path, duration }]
    """
    if embedder is None:
        return [_default_suggestion(v["video_id"], "embedder unavailable") for v in videos]

    # 1. 预缓存场景文本向量（一次编码，全部场景文本）
    try:
        text_vecs = await asyncio.wait_for(
            _get_scene_text_vecs(embedder),
            timeout=60.0,
        )
    except asyncio.TimeoutError:
        logger.warning("[SmartSuggest] scene text cache timeout")
        text_vecs = {}

    if not text_vecs:
        return [_default_suggestion(v["video_id"], "text encode failed") for v in videos]

    # 2. 并发抽帧（每视频独立 ffmpeg 调用，并发上限 3 防进程资源耗尽）
    async def extract_one(v: dict) -> tuple[dict, list[bytes]]:
        frames = await asyncio.to_thread(_extract_frames, v["video_path"], float(v.get("duration") or 0.0))
        return (v, frames)

    sem = asyncio.Semaphore(3)
    async def guarded(v: dict):
        async with sem:
            try:
                return await extract_one(v)
            except Exception as e:
                logger.warning("[SmartSuggest] extract failed for %s: %s", v.get("video_id"), e)
                return (v, [])

    extract_results = await asyncio.gather(*[guarded(v) for v in videos])

    # 3. 解码帧，按视频分组保留「成功解码」的帧数组。
    #    注意：all_vecs 只覆盖成功解码的帧，若用「原始帧数」去索引会导致
    #    帧解码失败时错位、把下一个视频的向量算进当前视频（跨视频污染）。
    #    这里 grouped 与 all_arrs 严格一一对应，消除错位。
    grouped: list[tuple[str, list[np.ndarray]]] = []  # (video_id, 已解码帧数组)
    all_arrs: list[np.ndarray] = []
    for v, frames in extract_results:
        arrs: list[np.ndarray] = []
        for fb in frames:
            try:
                from PIL import Image
                import io
                img = Image.open(io.BytesIO(fb)).convert("RGB")
                arrs.append(np.asarray(img, dtype=np.uint8))
            except Exception as e:
                logger.warning("[SmartSuggest] frame decode failed: %s", e)
        grouped.append((v["video_id"], arrs))
        all_arrs.extend(arrs)

    if not all_arrs:
        return [_default_suggestion(vid, "all frame extract failed") for vid, _ in grouped]

    # 4. 一次性批量编码所有视频的所有帧（GPU 一次前向）
    try:
        all_vecs = await embedder.encode_images_batch(all_arrs)
    except Exception as e:
        logger.warning("[SmartSuggest] encode_images_batch failed: %s", e)
        all_vecs = [None] * len(all_arrs)

    # 5. 按视频重组帧向量 → 算相似度。idx 逐帧消费，与 grouped 长度严格一致。
    results: list[dict] = []
    idx = 0
    for video_id, arrs in grouped:
        frame_scores: list[dict[str, float]] = []
        for _ in arrs:
            if idx >= len(all_vecs) or all_vecs[idx] is None:
                idx += 1
                continue
            vec = np.asarray(all_vecs[idx], dtype=np.float32)
            idx += 1
            n = float(np.linalg.norm(vec))
            if n == 0:
                continue
            vec = vec / n
            scores = {k: float(np.dot(vec, tv)) for k, tv in text_vecs.items()}
            frame_scores.append(scores)

        if not frame_scores:
            results.append(_default_suggestion(video_id, "no valid frames"))
            continue

        # majority voting
        from collections import Counter
        frame_top1 = [max(s.items(), key=lambda x: x[1])[0] for s in frame_scores]
        best_key = Counter(frame_top1).most_common(1)[0][0]
        avg_scores = {k: float(np.mean([s.get(k, 0.0) for s in frame_scores])) for k in text_vecs.keys()}
        confidence = avg_scores.get(best_key, 0.0)

        if confidence < LOW_CONFIDENCE_THRESHOLD:
            results.append(_default_suggestion(video_id, "low confidence", confidence, avg_scores))
        else:
            best_scene = next(s for s in SCENE_CLASSES if s["key"] == best_key)
            results.append({"video_id": video_id, "scene_key": best_key,
                            "scene_label": best_scene["label"],
                            "confidence": round(confidence, 4), "params": best_scene["params"],
                            "all_scores": {k: round(v, 4) for k, v in avg_scores.items()}})

    return results
