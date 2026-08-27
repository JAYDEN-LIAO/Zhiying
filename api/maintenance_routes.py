"""
api/maintenance_routes.py
═══════════════════════════════════════════════════════════
运维端点 — 存储卫生清扫与用量概览。

POST /maintenance/sweep  — 孤儿文件/目录/空组清扫（dry_run 预览 / 实际执行）
GET  /maintenance/storage — 各存储目录用量 + 可回收量概览

依赖 app.state.storage_manager（main.py lifespan 挂载的 StorageManager）。
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from api.schemas import APIResponse
from core.repository import (
    TASK_LOG_RETENTION_DAYS,
    cleanup_orphan_task_logs,
    prune_old_task_logs,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class SweepRequest(BaseModel):
    """清扫请求 — dry_run=True 只报告不删除（默认，安全）。"""
    dry_run: bool = Field(default=True, description="true=预览报告；false=实际执行删除")
    log_retention_days: int = Field(
        default=TASK_LOG_RETENTION_DAYS, ge=1,
        description="任务日志保留天数（超过的旧日志行随本次清扫删除）",
    )


def _get_manager(request: Request):
    manager = getattr(request.app.state, "storage_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="StorageManager not initialized")
    return manager


@router.post("/maintenance/sweep")
async def sweep_storage(
    req: SweepRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict]:
    """扫描并清理孤儿资源（视频文件/缩略图/音频/chunk 目录/空组/过期导出）。

    dry_run=true（默认）: 返回可回收清单，不删除任何文件。
    dry_run=false: 实际执行删除，返回清理结果。
    """
    manager = _get_manager(request)
    report = await manager.sweep(db, dry_run=req.dry_run)

    # 任务日志卫生：孤儿日志（视频已删遗留）+ 超保留期旧行（dry_run 同步只统计）
    orphan_rows = await cleanup_orphan_task_logs(db, dry_run=req.dry_run)
    pruned_rows = await prune_old_task_logs(db, days=req.log_retention_days, dry_run=req.dry_run)
    report["task_logs"] = {
        "orphan_rows": orphan_rows,
        "pruned_rows": pruned_rows,
        "retention_days": req.log_retention_days,
    }
    if orphan_rows or pruned_rows:
        logger.info(
            "[Maintenance] Task-log sweep dry_run=%s → orphan=%d pruned=%d (>%dd)",
            req.dry_run, orphan_rows, pruned_rows, req.log_retention_days,
        )

    logger.info(
        "[Maintenance] Sweep dry_run=%s → %s bytes reclaimable",
        req.dry_run, report["total_bytes_reclaimable"],
    )
    return APIResponse(data=report)


@router.get("/maintenance/storage")
async def storage_overview(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict]:
    """存储用量概览：各目录大小 + 当前孤儿可回收量（dry-run 摘要）。"""
    manager = _get_manager(request)
    usage = await manager.storage_usage(db)
    return APIResponse(data=usage)
