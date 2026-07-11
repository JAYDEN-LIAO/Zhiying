"""
pipeline/engine.py 全链路集成测试
═════════════════════════════════════════════════════════════════
使用短测试视频（FFmpeg 生成）+ 真实 BasicQC + Mock 转录/分割插件，
验证 pipeline 完整执行后数据正确持久化到数据库。
"""
import os
import uuid
from unittest.mock import patch, AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from core.config_loader import load_config
from core.models import Video, VideoStatus
from core.schemas import VideoCreate
from core.repository import create_video
from pipeline.engine import PipelineEngine

_TEST_VIDEO = "/tmp/cerno_test_5s.mp4"


# ── Mock 插件 ────────────────────────────────────────────────
# transcriber（无 ML 依赖）
MOCK_TRANSCRIBER = AsyncMock()
MOCK_TRANSCRIBER.transcribe.return_value = {
    "full_text": "mock transcript text for pipeline testing",
    "language": "en",
    "duration": 5.0,
    "words": [
        {"word": "hello", "start": 0.0, "end": 0.5, "confidence": 0.9},
        {"word": "world", "start": 0.5, "end": 1.0, "confidence": 0.8},
        {"word": "pipeline", "start": 1.0, "end": 1.5, "confidence": 0.7},
        {"word": "test", "start": 2.0, "end": 2.5, "confidence": 0.6},
    ],
}

# segmenter
MOCK_SEGMENTER = AsyncMock()
MOCK_SEGMENTER.segment.return_value = [
    {"scene_index": 0, "start_sec": 0.0, "end_sec": 2.0, "keyframe": None},
    {"scene_index": 1, "start_sec": 2.0, "end_sec": 4.0, "keyframe": None},
    {"scene_index": 2, "start_sec": 4.0, "end_sec": 5.0, "keyframe": None},
]

# extract_audio 也 mock 掉，避免实际 ffmpeg 调用
MOCK_EXTRACT_AUDIO = AsyncMock()


def _ensure_test_video():
    """同步生成 5 秒测试视频。"""
    if not os.path.exists(_TEST_VIDEO):
        import subprocess
        subprocess.run(
            ["ffmpeg", "-y",
             "-f", "lavfi", "-i", "testsrc=duration=5:size=640x480:rate=10",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
             "-c:v", "libx264", "-c:a", "aac", "-shortest",
             _TEST_VIDEO],
            check=True, capture_output=True,
        )
    return _TEST_VIDEO


async def _mock_load_plugin(config, category):
    """替换 pipeline.engine.load_plugin —— 仅 QC 用真实插件，其余 Mock。"""
    if category == "transcriber":
        return MOCK_TRANSCRIBER
    if category == "segmenter":
        return MOCK_SEGMENTER
    if category in ("detector", "ocr", "captioner", "embedder", "summarizer", "grounding"):
        return None  # 跳过
    # QC 用真实 BasicQC
    from plugins.factory import load_plugin as real_load
    return await real_load(config, category)


class TestPipelineEngine:
    """完整 pipeline 执行 + 数据持久化断言。"""

    @pytest.fixture(scope="class", autouse=True)
    def _video_file(self):
        return _ensure_test_video()

    async def test_full_pipeline_succeeds(self, db_session, _video_file):
        # ── 1. 创建 Video 记录 ──
        video = await create_video(
            db_session,
            VideoCreate(
                file_path=_TEST_VIDEO,
                file_name="pipeline_test.mp4",
                file_size=os.path.getsize(_TEST_VIDEO),
            ),
        )

        # ── 2. 创建 session_factory（从 db_session 的 bind）
        factory = async_sessionmaker(
            db_session.bind, class_=AsyncSession, expire_on_commit=False,
        )

        # ── 3. 加载配置 ──
        load_config.cache_clear()
        config = load_config()

        # ── 4. 实例化 PipelineEngine ──
        engine = PipelineEngine(config, factory, video)

        # ── 5. 打补丁后执行 ──
        patches = [
            patch("pipeline.engine.load_plugin", _mock_load_plugin),
            patch("pipeline.phase1_qc.extract_audio", MOCK_EXTRACT_AUDIO),
        ]
        for p in patches:
            p.start()
        try:
            await engine.run()
        finally:
            for p in patches:
                p.stop()

        # ── 6. 验证: 状态 COMPLETED + progress=1.0 ──
        row = (
            await db_session.execute(
                text("SELECT status::text, progress FROM videos WHERE id = :vid"),
                {"vid": video.id},
            )
        ).fetchone()
        assert row is not None
        assert row[0] == "COMPLETED", f"状态应为 COMPLETED，实际 {row[0]}"
        assert row[1] == 1.0, f"progress 应为 1.0，实际 {row[1]}"

        # ── 7. 验证: scenes 表有记录 ──
        result = await db_session.execute(
            text("SELECT COUNT(*) FROM scenes WHERE video_id = :vid"),
            {"vid": video.id},
        )
        scene_count = result.scalar()
        assert scene_count >= 1, f"scenes 表应 >= 1 条记录，实际 {scene_count}"

        # ── 8. 验证: scene_index 从 0 连续递增 ──
        result = await db_session.execute(
            text(
                "SELECT scene_index FROM scenes WHERE video_id = :vid ORDER BY scene_index"
            ),
            {"vid": video.id},
        )
        indices = [r[0] for r in result.fetchall()]
        assert indices == list(range(len(indices))), f"scene_index 不连续: {indices}"

        # ── 9. 验证: transcript 表有记录且 full_text 非空 ──
        result = await db_session.execute(
            text("SELECT full_text FROM transcripts WHERE video_id = :vid"),
            {"vid": video.id},
        )
        t_row = result.fetchone()
        assert t_row is not None, "transcripts 表应有记录"
        assert len(t_row[0].strip()) > 0, "full_text 不应为空"

        # ── 10. 验证: qc_result 不为 NULL ──
        result = await db_session.execute(
            text("SELECT qc_result FROM videos WHERE id = :vid"),
            {"vid": video.id},
        )
        qc_row = result.fetchone()
        assert qc_row is not None and qc_row[0] is not None, "qc_result 不应为 NULL"

        load_config.cache_clear()
