"""
core/schemas.py 全套 Pydantic v2 校验单元测试
═════════════════════════════════════════════════════════════════
覆盖：合法 JSONB 结构解析 / 字段边界校验 / 文件大小校验 / 嵌套 JSON 序列化。
"""
import uuid
import json
from datetime import datetime

import pytest
from pydantic import ValidationError

from core.schemas import (
    TimeSegment,
    QCResult,
    SceneSummaryItem,
    VideoSummary,
    SceneEntity,
    WordTimestamp,
    VideoCreate,
    VideoResponse,
    VideoListItem,
    SceneResponse,
    TranscriptResponse,
)
from core.models import VideoStatus, ContentType


# ═══════════════════════════════════════════════════════════════
# Test 1 — 合法数据解析（4 个标准 JSON 示例）
# ═══════════════════════════════════════════════════════════════
class TestLegalDataParsing:
    """对应 4 个 JSONB 字段的完整结构解析，验证 model_validate() 正确映射。"""

    def test_qc_result_full(self):
        """videos.qc_result — 质量检测结果含黑屏/静音/过曝段。"""
        data = {
            "is_valid": True,
            "estimated_duration": 125.3,
            "black_segments": [
                {"start_sec": 10.0, "end_sec": 12.5},
                {"start_sec": 100.0, "end_sec": 101.0},
            ],
            "silent_segments": [
                {"start_sec": 0.0, "end_sec": 3.0},
            ],
            "overexposed_segments": [],
        }
        obj = QCResult.model_validate(data)

        assert obj.is_valid is True
        assert obj.estimated_duration == 125.3
        assert len(obj.black_segments) == 2
        assert obj.black_segments[0].start_sec == 10.0
        assert obj.black_segments[1].end_sec == 101.0
        assert obj.silent_segments[0].end_sec == 3.0
        assert obj.overexposed_segments == []

    def test_video_summary_full(self):
        """videos.summary — 一句话总结 + 场景条目 + 标签/主题/实体。"""
        data = {
            "one_liner": "A product demo showcasing new features",
            "scenes_summary": [
                {
                    "scene_index": 0,
                    "start_sec": 0.0,
                    "end_sec": 10.0,
                    "description": "Opening",
                    "keywords": ["intro"],
                },
                {
                    "scene_index": 1,
                    "start_sec": 10.0,
                    "end_sec": 30.0,
                    "description": "Feature overview",
                    "keywords": ["features", "demo"],
                },
            ],
            "tags": ["product", "demo"],
            "main_topics": ["new features", "user experience"],
            "main_entities": ["Product X", "Team Y"],
        }
        obj = VideoSummary.model_validate(data)

        assert obj.one_liner == data["one_liner"]
        assert len(obj.scenes_summary) == 2
        assert obj.scenes_summary[0].description == "Opening"
        assert obj.scenes_summary[1].keywords == ["features", "demo"]
        assert obj.tags == ["product", "demo"]
        assert obj.main_topics == ["new features", "user experience"]
        assert obj.main_entities == ["Product X", "Team Y"]

    def test_scene_entities_list(self):
        """scenes.entities — 检测物列表（完整场景级 JSONB）。"""
        data = [
            {
                "label": "person",
                "bbox": [0.1, 0.2, 0.8, 0.9],
                "confidence": 0.95,
                "start_sec": 5.0,
                "end_sec": 15.0,
                "track_id": 1,
            },
            {
                "label": "car",
                "bbox": [0.0, 0.0, 0.5, 0.5],
                "confidence": 0.87,
                "start_sec": 8.0,
                "end_sec": 12.0,
                # track_id 可省略 → 默认 None
            },
        ]
        entities = [SceneEntity.model_validate(item) for item in data]

        assert len(entities) == 2
        assert entities[0].label == "person"
        assert entities[0].bbox == [0.1, 0.2, 0.8, 0.9]
        assert entities[0].confidence == 0.95
        assert entities[0].track_id == 1
        assert entities[1].label == "car"
        assert entities[1].track_id is None

    def test_transcript_words_list(self):
        """transcripts.words — 字词级时间戳数组。"""
        data = [
            {"word": "hello",   "start": 0.0, "end": 0.3, "confidence": 0.98},
            {"word": "world",   "start": 0.3, "end": 0.6, "confidence": 0.96},
            # confidence 可省略
            {"word": "test",    "start": 0.6, "end": 0.9},
        ]
        words = [WordTimestamp.model_validate(item) for item in data]

        assert len(words) == 3
        assert words[0].word == "hello"
        assert words[0].start == 0.0
        assert words[0].confidence == 0.98
        assert words[2].word == "test"
        assert words[2].confidence is None
        assert words[2].end == 0.9


# ═══════════════════════════════════════════════════════════════
# Test 2 — 非法边界校验
# ═══════════════════════════════════════════════════════════════
class TestValidationBoundaries:
    """超出 ge/le 边界的数值应触发 ValidationError。"""

    # ── progress 越界 ──

    def test_progress_overflow(self):
        """progress > 1.0 应拒绝。"""
        with pytest.raises(ValidationError):
            VideoResponse(
                id=uuid.uuid4(),
                status=VideoStatus.PENDING,
                progress=1.5,
                file_path="/x.mp4",
                file_name="x.mp4",
                file_size=100,
                content_type=ContentType.GENERAL,
                language="auto",
                audio_enabled=False, vision_enabled=True, ocr_enabled=False,
                grounding_enabled=False, caption_enabled=True, summary_enabled=True,
                search_index_enabled=True, sample_fps=1.0, segment_threshold=0.5,
                caption_with_context=True, summary_detail="standard",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )

    def test_progress_negative(self):
        """progress < 0.0 应拒绝。"""
        with pytest.raises(ValidationError):
            VideoResponse(
                id=uuid.uuid4(),
                status=VideoStatus.PENDING,
                progress=-0.1,
                file_path="/x.mp4",
                file_name="x.mp4",
                file_size=100,
                content_type=ContentType.GENERAL,
                language="auto",
                audio_enabled=False, vision_enabled=True, ocr_enabled=False,
                grounding_enabled=False, caption_enabled=True, summary_enabled=True,
                search_index_enabled=True, sample_fps=1.0, segment_threshold=0.5,
                caption_with_context=True, summary_detail="standard",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )

    # ── 置信度越界 ──

    def test_confidence_overflow(self):
        """confidence > 1.0 应拒绝。"""
        with pytest.raises(ValidationError):
            SceneEntity(
                label="person",
                bbox=[0, 0, 1, 1],
                confidence=1.05,
                start_sec=0.0,
                end_sec=10.0,
            )

    def test_confidence_negative(self):
        """confidence < 0.0 应拒绝。"""
        with pytest.raises(ValidationError):
            WordTimestamp(
                word="test",
                start=0.0,
                end=1.0,
                confidence=-0.01,
            )

    # ── 负时间值 ──

    @pytest.mark.parametrize("start,end", [
        (-1.0, 5.0),       # start_sec 负
        (0.0, -5.0),       # end_sec 负
        (-0.001, 10.0),    # start_sec 轻微负
        (3.0, -0.001),     # end_sec 轻微负
    ])
    def test_negative_time_segment(self, start, end):
        """TimeSegment 的 start_sec / end_sec 负值应拒绝。"""
        with pytest.raises(ValidationError):
            TimeSegment(start_sec=start, end_sec=end)

    @pytest.mark.parametrize("field,value", [
        ("start_sec", -0.1),
        ("end_sec",   -5.0),
    ])
    def test_negative_time_in_scene_entity(self, field, value):
        """SceneEntity 的时间字段负值应拒绝。"""
        kwargs = {
            "label": "person",
            "bbox": [0, 0, 1, 1],
            "confidence": 0.5,
            "start_sec": 0.0,
            "end_sec": 10.0,
        }
        kwargs[field] = value
        with pytest.raises(ValidationError):
            SceneEntity(**kwargs)


# ═══════════════════════════════════════════════════════════════
# Test 3 — 文件大小校验（VideoCreate）
# ═══════════════════════════════════════════════════════════════
class TestFileSizeValidation:
    """VideoCreate.file_size 必须 > 0。"""

    @pytest.mark.parametrize("invalid_size", [0, -1, -100])
    def test_file_size_invalid(self, invalid_size):
        """file_size ≤ 0 应全部拒绝。"""
        with pytest.raises(ValidationError):
            VideoCreate(
                file_path="/tmp/test.mp4",
                file_name="test.mp4",
                file_size=invalid_size,
            )


# ═══════════════════════════════════════════════════════════════
# Test 4 — 数据导出序列化（VideoResponse → JSON）
# ═══════════════════════════════════════════════════════════════
class TestSerialization:
    """VideoResponse 嵌套 JSON 序列化与键名完整性。"""

    def test_model_dump_json_structure(self):
        """构造完整 VideoResponse（含 summary 嵌套），断言 JSON 结构与键名。"""
        summary = VideoSummary(
            one_liner="Test video one-liner",
            scenes_summary=[
                SceneSummaryItem(
                    scene_index=0,
                    start_sec=0.0,
                    end_sec=5.0,
                    description="Intro",
                    keywords=["start"],
                ),
            ],
            tags=["test", "demo"],
            main_topics=["serialization", "pydantic"],
            main_entities=["EntityA", "EntityB"],
        )
        now = datetime.utcnow()
        video_resp = VideoResponse(
            id=uuid.uuid4(),
            status=VideoStatus.PROCESSING,
            progress=0.75,
            error_message=None,
            file_path="/videos/test.mp4",
            file_name="test.mp4",
            file_size=2048,
            duration=120.0,
            content_type=ContentType.GENERAL,
            language="en",
            audio_enabled=True,
            vision_enabled=True,
            ocr_enabled=False,
            grounding_enabled=True,
            caption_enabled=True,
            summary_enabled=False,
            search_index_enabled=True,
            sample_fps=1.0,
            segment_threshold=0.5,
            caption_with_context=True,
            summary_detail="standard",
            status_detail=None,
            qc_result=None,
            summary=summary,
            created_at=now,
            updated_at=now,
        )

        json_str = video_resp.model_dump_json()
        parsed = json.loads(json_str)

        # ── 顶层字段 ──
        assert parsed["status"] == "processing"
        assert parsed["progress"] == 0.75
        assert parsed["file_path"] == "/videos/test.mp4"
        assert parsed["file_size"] == 2048
        assert parsed["duration"] == 120.0
        assert parsed["content_type"] == "general"
        assert parsed["language"] == "en"
        assert parsed["audio_enabled"] is True
        assert parsed["ocr_enabled"] is False
        assert parsed["grounding_enabled"] is True
        assert parsed["summary_enabled"] is False

        # ── qc_result null ──
        assert parsed["qc_result"] is None

        # ── 嵌套 summary ──
        assert parsed["summary"]["one_liner"] == "Test video one-liner"
        assert len(parsed["summary"]["scenes_summary"]) == 1
        scene0 = parsed["summary"]["scenes_summary"][0]
        assert scene0["scene_index"] == 0
        assert scene0["start_sec"] == 0.0
        assert scene0["end_sec"] == 5.0
        assert scene0["description"] == "Intro"
        assert scene0["keywords"] == ["start"]
        assert parsed["summary"]["tags"] == ["test", "demo"]
        assert parsed["summary"]["main_topics"] == ["serialization", "pydantic"]
        assert parsed["summary"]["main_entities"] == ["EntityA", "EntityB"]
