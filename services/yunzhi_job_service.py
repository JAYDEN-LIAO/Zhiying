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
        "summary_mode": "native_video",
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


async def run_yunzhi_job(payload: YunzhiJobPayload, app) -> None:
    """后台执行云智自动化任务（路由以 202 接收后 create_task 调用）。"""
    token = payload.jobToken
    source = Path(payload.file.absolutePath).resolve()
    work_dir = Path(payload.workDirectory).resolve() if payload.workDirectory else None
    video_id = None
    try:
        if not source.is_file():
            raise FileNotFoundError(f"共享文件不存在: {source}")

        # 1. 按 operation 映射参数 → 建 Video 记录（源文件归平台所有）
        params = default_params_for_operation(payload.operation)
        # 允许平台在 job payload 内携带 params 覆盖默认参数（schema extra="allow"，
        # 白名单只接受默认参数集合内的键，防注入 file_path 等字段）
        _extra = getattr(payload, "__pydantic_extra__", None) or {}
        if isinstance(_extra.get("params"), dict):
            for k, v in _extra["params"].items():
                if k in params and v is not None:
                    params[k] = v
        dto = VideoCreate(
            file_path=str(source),
            file_name=payload.file.name or source.name,
            file_size=source.stat().st_size,
            source_owned=False,
            **params,
        )
        async with app.state.db_session_factory() as session:
            video = await create_video(session, dto)
        video_id = video.id
        logger.info("[Yunzhi] job=%s video=%s source=%s", payload.task.automationJobId, video.id, source)

        # 2. 同步 probe + 异步 remux（与上传流程一致）
        await app.state.format_service.probe_and_save(video.id, str(source))
        asyncio.create_task(app.state.format_service.process_format(video.id, str(source)))

        # 3. 平台回调（共享一个 HTTP 客户端）
        async with httpx.AsyncClient(timeout=_CALLBACK_TIMEOUT) as client:
            async def post(url: str, body: dict) -> None:
                await client.post(
                    url,
                    json=body,
                    headers={**_CALLBACK_HEADERS, "X-Yunzhi-Job-Token": token},
                )

            await post(payload.callback.progressUrl, {"progress": 5, "message": "Zhiying 已接收共享文件绝对路径"})

            async def on_progress(progress: float, message: str) -> None:
                try:
                    await post(payload.callback.progressUrl, {
                        "progress": min(99, max(0, round(progress * 100))),
                        "message": message,
                    })
                except Exception:
                    logger.warning("[Yunzhi] 进度回调失败: %s", message, exc_info=True)

            # 4. 跑管道（复用共享 embedder/detector + 并发限流 + 删除取消登记）
            config = load_config()
            service = VideoService(
                config=config,
                db_session_factory=app.state.db_session_factory,
                embedder=app.state.embedder,
                captioner=getattr(app.state, "captioner", None),
                detector=getattr(app.state, "detector", None),
            )
            await service.process_video(video.id, progress_callback=on_progress)

            # 5. process_video 内部吞异常 → 按 DB 最终状态决定回调
            #    ★ 必须在本 `async with` 块内发送（客户端仍存活），否则 "client has been closed"
            async with app.state.db_session_factory() as session:
                row = (await session.execute(
                    select(Video.status, Video.error_message).where(Video.id == video.id)
                )).one_or_none()
            status = row[0].value if hasattr(row[0], "value") else row[0]
            error_message = row[1]

            if status == VideoStatus.COMPLETED:
                result_data = {
                    "videoId": str(video.id),
                    "sourcePath": str(source),
                    "sourceName": payload.file.name or source.name,
                    "processedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                report_path = _write_report(work_dir, result_data) if work_dir else None
                if report_path:
                    result_data["reportPath"] = report_path
                await post(payload.callback.completeUrl, {
                    "message": "Zhiying 视频分析完成",
                    "resultData": result_data,
                })
                logger.info("[Yunzhi] job completed video=%s", video.id)
            else:
                await post(payload.callback.failUrl, {
                    "message": "Zhiying 视频分析失败",
                    "error": error_message or "管道未完成",
                })
                logger.warning("[Yunzhi] job failed video=%s error=%s", video.id, error_message)

    except Exception as e:
        logger.error("[Yunzhi] job crashed: %s", e, exc_info=True)
        try:
            async with httpx.AsyncClient(timeout=_CALLBACK_TIMEOUT) as client:
                await client.post(
                    payload.callback.failUrl,
                    json={"message": "Zhiying 视频分析失败", "error": str(e)},
                    headers={**_CALLBACK_HEADERS, "X-Yunzhi-Job-Token": token},
                )
        except Exception as ce:
            logger.error("[Yunzhi] fail 回调失败: %s", ce)
