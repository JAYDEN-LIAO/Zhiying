"""
services/yunzhi_job_service.py
═══════════════════════════════════════════════════════════
云智(Yunzhi)平台自动化任务执行服务 — 接收共享文件绝对路径，跑 Zhiying 管道，
回调平台任务中心的进度 / 完成 / 失败。

流程（对照 extension-automation-demo/server.py 的契约）:
  1. 校验共享文件存在（就地引用，source_owned=False，不复制文件）
  2. 按 operation(Manifest automation id) 映射默认 PipelineParams
  3. 建 Video 记录 → 同步 probe → 异步 remux
  4. 推 5% 进度 → VideoService.process_video(progress_callback=...) 推送实时进度
  5. 完成后按 DB 最终状态回调 completeUrl / failUrl；结果 JSON 写入平台工作目录
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

import httpx
from sqlalchemy import select

from core.schemas import YunzhiJobPayload, VideoCreate
from core.config_loader import load_config
from core.repository import create_video
from core.models import Video, VideoStatus
from services.video_service import VideoService

logger = logging.getLogger(__name__)

_CALLBACK_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_CALLBACK_HEADERS = {"Content-Type": "application/json"}


def default_params_for_operation(operation: str) -> dict:
    """operation(Manifest automation id) → PipelineParams 默认值。

    云智 job payload 不含完整参数；这里给一套对通用/监控视频合理的默认。
    后续可按 operation 区分场景（如 surveillance 关 summary、开 detection），
    或从配置/config.yaml 读入自动化任务参数映射。
    """
    return {
        "content_type": "general",
        "vision_enabled": True,
        "audio_enabled": False,
        "ocr_enabled": False,
        "caption_enabled": True,
        "detection_enabled": True,
        "detection_classes": None,
        "face_enabled": False,
        "plate_enabled": False,
        "summary_enabled": True,
        "summary_mode": "vlm_llm",
        "parse_mode": "standard",
        "search_index_enabled": True,
        "language": "auto",
        "sample_fps": 1.0,
        "segment_threshold": 0.5,
        "caption_with_context": True,
        "summary_detail": "standard",
    }


def _write_report(work_dir: Path, result_data: dict) -> str | None:
    """把结果 JSON 写入平台工作目录（供前端 files.saveToLibrary 登记到文件库）。"""
    try:
        work_dir.mkdir(parents=True, exist_ok=True)
        report = work_dir / "zhiying-result.json"
        report.write_text(
            json.dumps(result_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return str(report)
    except Exception as e:
        logger.warning("[Yunzhi] 结果写入工作目录失败: %s", e)
        return None


async def _find_existing_video(app, source: Path, file_id: int | None) -> Video | None:
    """按源路径 + 平台文件 id 查已建视频（崩溃窗口防重复建）。"""
    from sqlalchemy import select
    from core.models import Video
    async with app.state.db_session_factory() as session:
        stmt = select(Video).where(Video.file_path == str(source))
        if file_id is not None:
            stmt = stmt.where(Video.external_file_id == file_id)
        return (await session.execute(stmt)).scalars().first()


async def _update_task_video_id(app, task_id: str, video_id: str) -> None:
    """worker 建好视频后回写 pipeline_tasks.video_id（恢复续跑防重复建视频）。"""
    from sqlalchemy import select
    from core.models import PipelineTask
    async with app.state.db_session_factory() as session:
        row = (await session.execute(
            select(PipelineTask).where(PipelineTask.id == uuid.UUID(task_id))
        )).scalar_one_or_none()
        if row is not None:
            row.video_id = uuid.UUID(video_id)
            await session.commit()


async def execute_yunzhi_task(app, task_id: str, payload: dict, resume_video_id: str | None = None) -> None:
    """队列 worker 执行的云智自动化任务。

    - resume_video_id 提供时（重启恢复 running 任务）：复用已有视频，跳过建视频/probe/remux，直接跑管道+回调
    - 否则：external_file_id 查重 → 建视频 → probe/remux → 回写 task.video_id → 跑管道+回调
    """
    job = YunzhiJobPayload.model_validate(payload)
    token = job.jobToken
    source = Path(job.file.absolutePath).resolve()
    work_dir = Path(job.workDirectory).resolve() if job.workDirectory else None
    video_id = resume_video_id
    try:
        if not source.is_file():
            raise FileNotFoundError(f"共享文件不存在: {source}")

        # 1. 建视频（resume 复用；否则按源路径+文件 id 查重，防崩溃窗口重复建）
        if video_id is None:
            existing = await _find_existing_video(app, source, job.file.id)
            if existing is not None:
                video_id = str(existing.id)
                logger.info("[Yunzhi] job=%s reuse existing video=%s", job.task.automationJobId, video_id)
            else:
                params = default_params_for_operation(job.operation)
                # 允许平台在 job payload 内携带 params 覆盖默认参数（白名单防注入）
                _extra = getattr(job, "__pydantic_extra__", None) or {}
                if isinstance(_extra.get("params"), dict):
                    for k, v in _extra["params"].items():
                        if k in params and v is not None:
                            params[k] = v
                dto = VideoCreate(
                    file_path=str(source),
                    file_name=job.file.name or source.name,
                    file_size=source.stat().st_size,
                    source_owned=False,
                    external_file_id=job.file.id,
                    **params,
                )
                async with app.state.db_session_factory() as session:
                    video = await create_video(session, dto)
                video_id = str(video.id)
                await _update_task_video_id(app, task_id, video_id)
                logger.info("[Yunzhi] job=%s video=%s source=%s", job.task.automationJobId, video.id, source)

                # 2. 同步 probe + 异步 remux（与上传流程一致；resume 跳过）
                await app.state.format_service.probe_and_save(video.id, str(source))
                asyncio.create_task(app.state.format_service.process_format(video.id, str(source)))
        else:
            # resume：确认视频存在
            async with app.state.db_session_factory() as session:
                existing_video = (await session.execute(
                    select(Video).where(Video.id == uuid.UUID(video_id))
                )).scalar_one_or_none()
            if existing_video is None:
                raise FileNotFoundError(f"resume 视频不存在: {video_id}")
            logger.info("[Yunzhi] job=%s resume video=%s", job.task.automationJobId, video_id)

        # 3. 平台回调（共享一个 HTTP 客户端）
        async with httpx.AsyncClient(timeout=_CALLBACK_TIMEOUT) as client:
            async def post(url: str, body: dict) -> None:
                await client.post(
                    url,
                    json=body,
                    headers={**_CALLBACK_HEADERS, "X-Yunzhi-Job-Token": token},
                )

            await post(job.callback.progressUrl, {"progress": 5, "message": "Zhiying 已接收共享文件绝对路径"})

            async def on_progress(progress: float, message: str) -> None:
                try:
                    await post(job.callback.progressUrl, {
                        "progress": min(99, max(0, round(progress * 100))),
                        "message": message,
                    })
                except Exception:
                    logger.warning("[Yunzhi] 进度回调失败: %s", message, exc_info=True)

            # 4. 跑管道（复用共享 embedder/detector + 删除取消登记）
            config = load_config()
            service = VideoService(
                config=config,
                db_session_factory=app.state.db_session_factory,
                embedder=app.state.embedder,
                captioner=getattr(app.state, "captioner", None),
                detector=getattr(app.state, "detector", None),
            )
            await service.process_video(uuid.UUID(video_id), progress_callback=on_progress)

            # 5. process_video 内部吞异常 → 按 DB 最终状态决定回调
            #    ★ 必须在本 `async with` 块内发送（客户端仍存活），否则 "client has been closed"
            async with app.state.db_session_factory() as session:
                row = (await session.execute(
                    select(Video.status, Video.error_message).where(Video.id == uuid.UUID(video_id))
                )).one_or_none()
            status = row[0].value if hasattr(row[0], "value") else row[0]
            error_message = row[1]

            if status == VideoStatus.COMPLETED:
                result_data = {
                    "videoId": video_id,
                    "sourcePath": str(source),
                    "sourceName": job.file.name or source.name,
                    "processedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                report_path = _write_report(work_dir, result_data) if work_dir else None
                if report_path:
                    result_data["reportPath"] = report_path
                await post(job.callback.completeUrl, {
                    "message": "Zhiying 视频分析完成",
                    "resultData": result_data,
                })
                logger.info("[Yunzhi] job completed video=%s", video_id)
            else:
                await post(job.callback.failUrl, {
                    "message": "Zhiying 视频分析失败",
                    "error": error_message or "管道未完成",
                })
                logger.warning("[Yunzhi] job failed video=%s error=%s", video_id, error_message)

    except Exception as e:
        logger.error("[Yunzhi] job crashed: %s", e, exc_info=True)
        try:
            async with httpx.AsyncClient(timeout=_CALLBACK_TIMEOUT) as client:
                await client.post(
                    job.callback.failUrl,
                    json={"message": "Zhiying 视频分析失败", "error": str(e)},
                    headers={**_CALLBACK_HEADERS, "X-Yunzhi-Job-Token": token},
                )
        except Exception as ce:
            logger.error("[Yunzhi] fail 回调失败: %s", ce)
