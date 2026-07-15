"""
全链路端到端 E2E 集成测试（阶段十）
═════════════════════════════════════════════════════════════════
覆盖：API 创建视频 → pipeline 执行（Mock 不可用插件）→ 数据持久化 → 文本/混合检索。
"""
import asyncio
import os
import uuid
from unittest.mock import AsyncMock, patch

import httpx
from httpx import ASGITransport
import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from core.config_loader import load_config
from core.schemas import VideoCreate
from core.repository import create_video
from services.video_service import VideoService
from main import app
from api.deps import get_db

_TEST_VIDEO = "/tmp/cerno_e2e_test.mp4"


# ── Mock 插件 ────────────────────────────────────────────────
MOCK_TRANSCRIBER = AsyncMock()
MOCK_TRANSCRIBER.transcribe.return_value = {
    "full_text": "E2E pipeline test transcript content",
    "language": "en",
    "duration": 10.0,
    "words": [
        {"word": "E2E", "start": 0.0, "end": 0.3, "confidence": 0.9},
        {"word": "pipeline", "start": 0.3, "end": 0.7, "confidence": 0.8},
    ],
}
MOCK_SEGMENTER = AsyncMock()
MOCK_SEGMENTER.segment.return_value = [
    {"scene_index": 0, "start_sec": 0.0, "end_sec": 4.0, "keyframe": np.full((10, 10, 3), 100, dtype=np.uint8)},
    {"scene_index": 1, "start_sec": 4.0, "end_sec": 8.0, "keyframe": np.full((10, 10, 3), 100, dtype=np.uint8)},
    {"scene_index": 2, "start_sec": 8.0, "end_sec": 10.0, "keyframe": np.full((10, 10, 3), 100, dtype=np.uint8)},
]
MOCK_CAPTIONER = AsyncMock()
MOCK_CAPTIONER.caption.side_effect = ["开场画面", "功能演示", "结尾致谢"]
MOCK_EMBEDDER = AsyncMock()
MOCK_EMBEDDER.encode_image.return_value = [0.1] * 768
MOCK_EMBEDDER.encode_text.return_value = [0.2] * 768
MOCK_SUMMARIZER = AsyncMock()
MOCK_SUMMARIZER.summarize.return_value = {
    "one_liner": "E2E 测试摘要",
    "scenes_summary": [],
    "tags": ["test"],
    "main_topics": ["E2E"],
    "main_entities": ["Cerno"],
}
MOCK_EXTRACT_AUDIO = AsyncMock()


def _ensure_test_video():
    if not os.path.exists(_TEST_VIDEO):
        import subprocess
        subprocess.run(
            ["ffmpeg", "-y",
             "-f", "lavfi", "-i", "testsrc=duration=10:size=640x480:rate=10",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=10",
             "-c:v", "libx264", "-c:a", "aac", "-shortest", _TEST_VIDEO],
            check=True, capture_output=True,
        )
    return _TEST_VIDEO


async def _mock_load(config, category):
    if category in ("transcriber",): return MOCK_TRANSCRIBER
    if category in ("segmenter",): return MOCK_SEGMENTER
    if category in ("captioner",): return MOCK_CAPTIONER
    if category in ("embedder",): return MOCK_EMBEDDER
    if category in ("summarizer",): return MOCK_SUMMARIZER
    if category in ("detector", "ocr", "grounding"): return None
    from plugins.factory import load_plugin as r
    return await r(config, category)


class TestFullPipelineE2E:
    """Step 1‑7 全链路。"""

    async def test_full_pipeline_e2e(self, db_session):
        _ensure_test_video()

        # ── 准备 session_factory + httpx client ──
        factory = async_sessionmaker(
            db_session.bind, class_=AsyncSession, expire_on_commit=False,
        )

        async def override_get_db():
            async with factory() as session:
                yield session

        app.dependency_overrides[get_db] = override_get_db
        transport = ASGITransport(app=app)

        keyword = "E2E"

        # ════════════════════════════════════════════════════════
        # Step 1: POST /api/v1/videos
        # ════════════════════════════════════════════════════════
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/videos",
                json={
                    "file_path": _TEST_VIDEO,
                    "file_name": "e2e_test.mp4",
                    "file_size": os.path.getsize(_TEST_VIDEO),
                },
            )
        assert resp.status_code == 201, f"Step 1 失败: {resp.text}"
        body = resp.json()
        assert body["code"] == 0
        video_id = body["data"]["id"]
        uuid.UUID(video_id)

        # ════════════════════════════════════════════════════════
        # Step 2: 直接调用 process_video（BackgroundTasks 不可靠）
        # ════════════════════════════════════════════════════════
        load_config.cache_clear()
        config = load_config()
        service = VideoService(config, factory)

        with patch("pipeline.engine.load_plugin", _mock_load), \
             patch("pipeline.phase1_qc.extract_audio", MOCK_EXTRACT_AUDIO):
            await service.process_video(uuid.UUID(video_id))

        # ════════════════════════════════════════════════════════
        # Step 3: 验证 status=COMPLETED progress=1.0
        # ════════════════════════════════════════════════════════
        row = (
            await db_session.execute(
                text("SELECT status::text, progress FROM videos WHERE id = :vid"),
                {"vid": uuid.UUID(video_id)},
            )
        ).fetchone()
        assert row[0] == "COMPLETED", f"状态应为 COMPLETED，实际 {row[0]}"
        assert row[1] == 1.0

        # ════════════════════════════════════════════════════════
        # Step 4: GET /api/v1/videos/{id} → summary 非空
        # ════════════════════════════════════════════════════════
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/v1/videos/{video_id}")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["summary"] is not None
        assert data["summary"]["one_liner"] == "E2E 测试摘要"

        # ════════════════════════════════════════════════════════
        # Step 5: scenes → caption / text_embedding 非空
        # ════════════════════════════════════════════════════════
        rows = (
            await db_session.execute(
                text("""
                    SELECT id, caption, text_embedding::text
                    FROM scenes WHERE video_id = :vid ORDER BY scene_index
                """),
                {"vid": uuid.UUID(video_id)},
            )
        ).fetchall()
        assert len(rows) >= 1
        for i, r in enumerate(rows):
            assert r[1] and len(r[1]) > 0, f"scene[{i}] caption 空"
