"""
services/report_service.py
═══════════════════════════════════════════════════════════
任务导出报告（v0.34）— 单个版本行 → Markdown 文本。

聚合 videos 主行信息 + 各产物表统计 + 任务日志，生成人可读报告。
批量导出 = 逐任务调 build_report_md()，zip 打包（见 api/tasks_routes.py）。
"""

import logging

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import (
    Video, TaskLog, Scene,
    FrameEmbedding, Chunk, FrameDetection, Track,
    FaceIdentity, FaceDetection, PlateDetection, OCRDetection,
)
from services.export_service import condense_ocr, fmt_clock

logger = logging.getLogger(__name__)

# 报告要聚合的产物表（用于 count 统计；表异常/缺失时降级为 0，不阻塞报告）
_PRODUCT_MODELS = [
    Scene, FrameEmbedding, Chunk, FrameDetection, Track,
    FaceIdentity, FaceDetection, PlateDetection,
]

_STATUS_CN = {
    "pending": "待参数",
    "processing": "处理中",
    "completed": "已完成",
    "failed": "失败",
}


async def _group_name(session: AsyncSession, group_id) -> str:
    from sqlalchemy import text
    row = await session.execute(
        text("SELECT name FROM video_groups WHERE id = :gid"), {"gid": group_id}
    )
    g = row.first()
    return g[0] if g else ""


def _fmt_sec(sec: float | None) -> str:
    if sec is None:
        return "—"
    total = int(round(sec))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}小时{m}分{s}秒"
    return f"{m}分{s}秒"


def _fmt_dt(dt) -> str:
    if dt is None:
        return "—"
    return dt.strftime("%Y-%m-%d %H:%M:%S")


async def build_report_md(session: AsyncSession, video: Video) -> str:
    """构建单个版本行的 Markdown 报告文本。"""
    gname = await _group_name(session, video.group_id) if video.group_id else ""

    # ── 统计各产物表（单表异常降级为 0，不阻塞整份报告） ──
    async def _count(model, **filters):
        try:
            stmt = select(func.count()).select_from(model).where(model.video_id == video.id)
            for k, v in filters.items():
                stmt = stmt.where(getattr(model, k) == v)
            return (await session.execute(stmt)).scalar() or 0
        except Exception:
            logger.warning("[Report] count on %s failed, degrades to 0", model.__tablename__, exc_info=True)
            return 0

    counts = {}
    for model in _PRODUCT_MODELS:
        counts[model.__tablename__] = await _count(model)

    scene_count = counts[Scene.__tablename__]
    frame_count = counts[FrameEmbedding.__tablename__]
    chunk_count = counts[Chunk.__tablename__]
    track_count = counts[Track.__tablename__]
    detection_count = counts[FrameDetection.__tablename__]
    face_identity_count = counts[FaceIdentity.__tablename__]
    face_detection_count = counts[FaceDetection.__tablename__]
    plate_count = counts[PlateDetection.__tablename__]

    # ── 检测按类别聚合 ──
    det_summary = "—"
    try:
        det_rows = await session.execute(
            select(Track.class_name, func.count(Track.id))
            .where(Track.video_id == video.id)
            .group_by(Track.class_name)
            .order_by(func.count(Track.id).desc())
        )
        det_summary = "、".join(f"{cls} {n}条" for cls, n in det_rows.all()) or "—"
    except Exception:
        logger.warning("[Report] track aggregate failed, degrades to '—'", exc_info=True)

    # ── 车牌识别明细（去重保序，完整列出） ──
    plate_texts: list[str] = []
    try:
        plate_texts = (await session.execute(
            select(PlateDetection.plate_text).where(
                PlateDetection.video_id == video.id,
                PlateDetection.plate_text.isnot(None),
            )
        )).scalars().all()
    except Exception:
        logger.warning("[Report] plate texts failed, degrades to empty", exc_info=True)
    plate_texts = list(dict.fromkeys(plate_texts))

    # ── OCR 画面文字（相邻重复行折叠，与 txt 导出同一逻辑） ──
    ocr_lines: list[tuple[float, str]] = []
    try:
        ocr_dets = (await session.execute(
            select(OCRDetection)
            .where(OCRDetection.video_id == video.id)
            .order_by(OCRDetection.timestamp_sec)
        )).scalars().all()
        ocr_lines = condense_ocr(ocr_dets)
    except Exception:
        logger.warning("[Report] ocr condense failed, degrades to empty", exc_info=True)

    # ── 任务日志（表缺失时降级为空） ──
    logs = []
    try:
        logs = (await session.execute(
            select(TaskLog).where(TaskLog.task_id == video.id).order_by(TaskLog.seq.asc())
        )).scalars().all()
    except Exception:
        logger.warning("[Report] task_logs read failed, degrades to empty", exc_info=True)

    # ── 时长 ──
    duration_sec = None
    if video.processing_started_at and video.updated_at:
        duration_sec = (video.updated_at - video.processing_started_at).total_seconds()

    lines = [
        f"# 任务报告 · {video.file_name}",
        "",
        "## 基本信息",
        f"- 状态：{_STATUS_CN.get(video.status, video.status)}",
        f"- 版本：V{video.version_no}" if video.version_no else "- 版本：—",
        f"- 所属案例：{gname}" if gname else "- 所属案例：未分组",
        f"- 提交时间：{_fmt_dt(video.created_at)}",
        f"- 完成时间：{_fmt_dt(video.updated_at)}" if video.status == "completed" else None,
        f"- 处理耗时：{_fmt_sec(duration_sec)}",
        f"- 视频时长：{_fmt_sec(video.duration)}",
        "",
        "## 分析结果",
        f"- 场景数：{scene_count}",
        f"- 帧向量：{frame_count}",
        f"- 语义块：{chunk_count}",
        f"- 检测轨迹：{track_count}（帧检测 {detection_count} 次）",
        f"- 检测类别：{det_summary}",
        f"- 人脸身份：{face_identity_count}（检测 {face_detection_count} 次）",
    ]
    lines = [ln for ln in lines if ln is not None]

    # ── 视频产出：摘要 / OCR / 车牌（有数据才出对应小节） ──
    output_parts: list[str] = []

    summary = video.summary if isinstance(video.summary, dict) else None
    if summary:
        sum_lines: list[str] = []
        if summary.get("one_liner"):
            sum_lines.append(f"**一句话概述**：{summary['one_liner']}")
        for label, key in (("标签", "tags"), ("核心主题", "main_topics"), ("主要实体", "main_entities")):
            items = [str(t) for t in (summary.get(key) or []) if str(t).strip()]
            if items:
                sum_lines.append(f"**{label}**：{'、'.join(items)}")
        scenes = summary.get("scenes_summary") or []
        if scenes:
            scene_items = [
                "- **[{} - {}]** {}".format(
                    fmt_clock(sc.get("start_sec", 0)),
                    fmt_clock(sc.get("end_sec", 0)),
                    (sc.get("description") or "").strip().replace("\n", "\n  "),
                )
                for sc in scenes
            ]
            sum_lines.append("**分场景摘要**：\n" + "\n".join(scene_items))
        if sum_lines:
            output_parts.append("### 智能摘要\n\n" + "\n\n".join(sum_lines))

    if ocr_lines:
        ocr_items = [f"- **[{fmt_clock(ts)}]** {text}" for ts, text in ocr_lines]
        output_parts.append(
            f"### 画面文字识别（去重后 {len(ocr_lines)} 行）\n\n" + "\n".join(ocr_items)
        )

    if plate_count or plate_texts:
        plate_md = f"### 车牌识别\n\n- 识别条数：{plate_count} 条"
        if plate_texts:
            plate_md += f"\n- 车牌列表（去重后 {len(plate_texts)} 个）：{'、'.join(plate_texts)}"
        output_parts.append(plate_md)

    if output_parts:
        lines += ["", "## 视频产出"]
        for part in output_parts:
            lines += ["", part]
    if logs:
        lines += ["", "## 处理日志"]
        lines += [f"{l.seq}. [{l.level}] {l.message}" for l in logs]

    return "\n".join(lines) + "\n"
