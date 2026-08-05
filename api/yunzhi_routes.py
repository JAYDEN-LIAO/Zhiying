"""
api/yunzhi_routes.py
═══════════════════════════════════════════════════════════
云智(Yunzhi)平台扩展自动化任务接口 — POST /internal/yunzhi/jobs。

契约（对照 extension-automation-demo/server.py）:
  - 平台在文件库上传匹配 Manifest 的文件后，POST 到本服务（应用后台地址）
  - 立即 202 返回 {accepted: True, bizTaskId}，业务异步执行（不阻塞）
  - 后台跑 Zhiying 管道，进度/完成/失败通过平台提供的 callback.*Url 上报
  - Idempotency-Key 或 eventId 幂等：重复投递返回同一 bizTaskId，不重复处理

注意：此路由在根路径挂载（main.py 独立 include_router，不走 /api/v1 前缀），
平台按扩展应用后台服务地址直调。信任模型与 demo 一致（平台内网调用）；
如需加固可在 config 加共享密钥校验。
"""

import asyncio
import logging

from fastapi import APIRouter, Header, Request

from core.schemas import YunzhiJobPayload
from services.yunzhi_job_service import run_yunzhi_job

logger = logging.getLogger(__name__)

router = APIRouter(tags=["yunzhi"])

# ── 幂等登记：Idempotency-Key/eventId → bizTaskId（单进程，进程内有效） ──
_accepted_jobs: dict[str, str] = {}
_accepted_jobs_lock = asyncio.Lock()


def _biz_task_id(automation_job_id: str) -> str:
    """业务任务 ID — 与 demo 一致，以 automationJobId 为锚。"""
    return f"yunzhi-{automation_job_id}"


@router.post("/internal/yunzhi/jobs", status_code=202)
async def yunzhi_jobs(
    request: Request,
    payload: YunzhiJobPayload,
    idempotency_key: str | None = Header(default=None),
) -> dict:
    """接收云智自动化任务：立即 202，后台异步跑管道并回调平台。"""
    key = idempotency_key or payload.eventId or f"{payload.task.automationJobId}:{payload.file.name}"
    async with _accepted_jobs_lock:
        biz_task_id = _accepted_jobs.get(key)
        if biz_task_id is None:
            biz_task_id = _biz_task_id(payload.task.automationJobId)
            _accepted_jobs[key] = biz_task_id
            asyncio.create_task(run_yunzhi_job(payload, request.app))
            logger.info("[Yunzhi] accepted job key=%s bizTaskId=%s file=%s",
                        key, biz_task_id, payload.file.name)
    return {"accepted": True, "bizTaskId": biz_task_id}
