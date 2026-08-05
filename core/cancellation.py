"""
core/cancellation.py
═══════════════════════════════════════════════════════════
管道取消登记 — 允许删除「处理中」视频后，后台管道优雅中止。

背景：删除端点放开 PROCESSING 守卫后，后台管道仍在跑（攒批/推理/持久化）。
若管道照常写入 DB（videos 行已删，子表 FK → videos.id 失效）会抛 FK 异常。
此模块登记「已被删除但仍可能在跑的 video id」，管道在关键写入点（persist 前）
检查即跳过，避免写已删行。

放 core/ 而非 services/：engine.py 需要引用它，而 services/video_service.py
反向依赖 pipeline.engine —— 放 core/ 无循环导入。单进程有效（uvicorn 单 worker）。
"""

import uuid

# 已删除但后台管道尚未感知/中止的视频 id 集合
CANCELLED_VIDEOS: set[uuid.UUID] = set()


def is_cancelled(video_id: uuid.UUID) -> bool:
    """该视频是否已被删除（管道应中止）。"""
    return video_id in CANCELLED_VIDEOS


def mark_cancelled(video_id: uuid.UUID) -> None:
    """登记已删除的视频 id（删除端点在 DB 删除前调用）。"""
    CANCELLED_VIDEOS.add(video_id)


def unmark_cancelled(video_id: uuid.UUID) -> None:
    """管道结束后移除登记（防集合无界增长）。"""
    CANCELLED_VIDEOS.discard(video_id)
