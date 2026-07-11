"""
services/video_service.py 异常流程测试
═════════════════════════════════════════════════════════════════
file_path 指向不存在文件时，process_video 不应崩溃，Video 状态应变为 FAILED。
"""
import uuid
import os
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from core.config_loader import load_config
from core.models import Video, VideoStatus
from core.schemas import VideoCreate
from core.repository import create_video
from services.video_service import VideoService


class TestVideoService:
    """VideoService 异常流程。"""

    async def test_process_video_with_nonexistent_file(self, db_session):
        """file_path 不存在时，video 应变为 FAILED 且 error_message 非空。"""
        video = await create_video(
            db_session,
            VideoCreate(
                file_path="/tmp/__nonexistent_video_xyz__.mp4",
                file_name="nonexistent.mp4",
                file_size=100,
            ),
        )
        video_id = video.id

        # 构造 session_factory + config
        load_config.cache_clear()
        config = load_config()
        factory = async_sessionmaker(
            db_session.bind, class_=AsyncSession, expire_on_commit=False,
        )

        # 模拟 load_plugin 使 pipeline 能走到 run()
        # 让 QC 的 check 抛出异常（文件不存在）
        from plugins.qc.basic_qc import BasicQC
        with patch("plugins.factory.load_plugin") as mock_load:

            async def side_effect(cfg, category):
                if category == "qc":
                    return BasicQC()
                return None  # 其他插件禁用
            mock_load.side_effect = side_effect

            service = VideoService(config, factory)
            await service.process_video(video_id)

        # 验证状态
        row = (
            await db_session.execute(
                text("SELECT status::text, error_message, progress FROM videos WHERE id = :vid"),
                {"vid": video_id},
            )
        ).fetchone()
        assert row is not None, "Video 应仍在数据库中"
        assert row[0] == "FAILED", f"状态应为 FAILED，实际 {row[0]}"
        assert row[1] is not None and len(row[1]) > 0, "error_message 不应为空"
