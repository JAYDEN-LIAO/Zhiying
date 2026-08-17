"""
api/tasks_routes.py
═══════════════════════════════════════════════════════════
任务中心 API（v0.34）— 一次解析 = 一个版本行（videos 行）。

列表按 scope 过滤；日志读 task_logs；重试 = 清空产物 + 重置 pending + 重新入队。
"""

import io
import uuid
import zipfile
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import select, delete as sa_delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from api.schemas import APIResponse
from core.models import (
    Video, TaskLog, VideoStatus,
    Scene, Transcript, FrameEmbedding, Chunk, FrameDetection, Track,
    TrackEmbedding, FaceIdentity, FaceDetection, PlateDetection,
)
from core.schemas import TaskItem
from core.repository import append_task_log

logger = logging.getLogger(__name__)

router = APIRouter()

_PRODUCT_MODELS = [
    Scene, Transcript, FrameEmbedding, Chunk, FrameDetection, Track,
    TrackEmbedding, FaceIdentity, FaceDetection, PlateDetection,
]


async def _task_to_dto(
    session: AsyncSession,
    v: Video,
    queued_video_ids: set[uuid.UUID] | None = None,
) -> TaskItem:
    """版本行 → TaskItem（补 file_name/group_name/queued）。

    queued_video_ids：当前「排队中」的 video_id 集合 —— list_tasks 一次性批量查好传入（防 N+1）；
    单查场景传 None → 内部按当前视频查一条。
    """
    group_name = None
    if v.group_id:
        row = await session.execute(
            text("SELECT name FROM video_groups WHERE id = :gid"), {"gid": v.group_id}
        )
        g = row.first()
        group_name = g[0] if g else None
    # 真实处理时长 = 完成/失败时间 − 管道开始处理时间（入队排队不计入）
    duration_sec = None
    if v.processing_started_at and v.updated_at:
        duration_sec = (v.updated_at - v.processing_started_at).total_seconds()
    # 排队中：pipeline_tasks 有 status='queued' 的行的 video（全局队列等 worker，侧栏黄徽章数据）
    if queued_video_ids is not None:
        queued = v.id in queued_video_ids
    else:
        row = await session.execute(
            text("SELECT 1 FROM pipeline_tasks WHERE video_id = :vid AND status = 'queued' LIMIT 1"),
            {"vid": v.id},
        )
        queued = row.first() is not None
    return TaskItem(
        id=v.id,
        version_no=v.version_no,
        file_name=v.file_name,
        group_name=group_name,
        status=v.status,
        progress=v.progress,
        error_message=v.error_message,
        queued=queued,
        detection_enabled=v.detection_enabled,
        face_enabled=v.face_enabled,
        plate_enabled=v.plate_enabled,
        search_index_enabled=v.search_index_enabled,
        summary_enabled=v.summary_enabled,
        params=None,
        created_at=v.created_at,
        updated_at=v.updated_at,
        duration_sec=duration_sec,
    )


@router.get("/tasks", response_model=APIResponse[list[TaskItem]])
async def list_tasks(
    scope: str = Query("all", pattern="^(all|active|history)$"),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[TaskItem]]:
    """任务列表 — scope: all(全部) / active(处理中+待参数) / history(已完成+失败)。"""
    stmt = select(Video).order_by(Video.created_at.desc())
    if scope == "active":
        stmt = stmt.where(
            Video.status.in_([VideoStatus.PROCESSING, VideoStatus.PENDING])
        )
    elif scope == "history":
        stmt = stmt.where(
            Video.status.in_([VideoStatus.COMPLETED, VideoStatus.FAILED])
        )
    result = await db.execute(stmt)
    videos = list(result.scalars().all())
    # 一次性批量查「排队中」video_id 集合（侧栏黄徽章数据，防 N+1）
    qrows = await db.execute(
        text("SELECT video_id FROM pipeline_tasks WHERE status = 'queued'")
    )
    queued_ids = {r[0] for r in qrows if r[0] is not None}
    items = [await _task_to_dto(db, v, queued_ids) for v in videos]
    return APIResponse(data=items)


@router.get("/tasks/{task_id}", response_model=APIResponse[TaskItem])
async def get_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[TaskItem]:
    v = await db.get(Video, task_id)
    if v is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return APIResponse(data=await _task_to_dto(db, v))


@router.get("/tasks/{task_id}/log", response_model=APIResponse[dict])
async def get_task_log(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict]:
    """任务日志 — task_logs 表（task_id = 版本行 id）。"""
    result = await db.execute(
        select(TaskLog)
        .where(TaskLog.task_id == task_id)
        .order_by(TaskLog.seq.asc())
    )
    logs = list(result.scalars().all())
    return APIResponse(data={
        "log": [{"seq": l.seq, "level": l.level, "message": l.message, "created_at": l.created_at.isoformat()} for l in logs],
    })


@router.post("/tasks/{task_id}/retry", response_model=APIResponse[dict])
async def retry_task(
    task_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict]:
    """重试 — 清空该版本行产物 + 重置 pending + 重新入队。"""
    v = await db.get(Video, task_id)
    if v is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 清空产物（防 failed 半程残留 + 重跑累积）
    for model in _PRODUCT_MODELS:
        await db.execute(
            sa_delete(model).where(model.video_id == v.id)
        )
    # 重置状态（processing_started_at 置空 → 下次 _set_processing 重新计时）
    v.status = VideoStatus.PENDING
    v.progress = 0.0
    v.error_message = None
    v.summary = None
    v.processing_started_at = None
    await db.commit()
    await append_task_log(db, v.id, "任务重试：产物已清空，重新入队")

    # 重新入队（复用全局队列）
    queue = getattr(request.app.state, "pipeline_queue", None)
    if queue is not None:
        await queue.enqueue("pipeline", {"video_id": str(v.id)})
    else:
        # 无队列（如单测）→ 直接触发
        from services.video_service import _build_service
        import asyncio
        asyncio.create_task(_build_service(request.app).process_video(v.id))
    return APIResponse(data={"ok": True, "id": str(v.id)})


# ──────────────────────────────────────────────────────────────
# 导出报告（v0.34）
# ──────────────────────────────────────────────────────────────

@router.get("/tasks/{task_id}/report")
async def export_task_report(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """导出单个任务报告（Markdown 下载）。"""
    import urllib.parse
    v = await db.get(Video, task_id)
    if v is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    from services.report_service import build_report_md
    md = await build_report_md(db, v)
    safe_name = (v.file_name or str(v.id)).replace("/", "_").replace("\\", "_")
    # 中文文件名必须 URL 编码（HTTP header 仅 latin-1），RFC 5987 filename* 兜底
    ascii_name = urllib.parse.quote(safe_name)
    return Response(
        content=md,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="report_{ascii_name}.md"; filename*=UTF-8\'\'report_{ascii_name}.md',
        },
    )


@router.post("/tasks/export-batch")
async def export_tasks_batch(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """批量导出任务报告 — body {task_ids: [uuid...]} → zip 打包下载。"""
    from services.report_service import build_report_md
    body = await request.json()
    task_ids = body.get("task_ids", [])
    if not task_ids:
        raise HTTPException(status_code=400, detail="未指定任务")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for tid in task_ids:
            v = await db.get(Video, tid)
            if v is None:
                continue
            md = await build_report_md(db, v)
            safe_name = (v.file_name or str(v.id)).replace("/", "_").replace("\\", "_")
            zf.writestr(f"report_{safe_name}.md", md)
    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=reports_{len(task_ids)}.zip",
        },
    )
