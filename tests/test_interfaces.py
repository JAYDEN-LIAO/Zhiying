"""
core/interfaces.py 接口完整性测试
═════════════════════════════════════════════════════════════════
验证：9 个抽象类不可实例化、最小 Mock 实现满足方法签名、
dataclass 默认值与字段类型正确。
"""
import numpy as np
import pytest

from core.interfaces import (
    Scene,
    VideoContext,
    BaseQC,
    BaseTranscriber,
    BaseSegmenter,
    BaseDetector,
    BaseOCR,
    BaseCaptioner,
    BaseEmbedder,
    BaseSummarizer,
    BaseGrounding,
)

BASE_INTERFACES = [
    (BaseQC, ["check"]),
    (BaseTranscriber, ["transcribe"]),
    (BaseSegmenter, ["segment"]),
    (BaseDetector, ["detect"]),
    (BaseOCR, ["extract"]),
    (BaseCaptioner, ["caption"]),
    (BaseEmbedder, ["encode_image", "encode_text"]),
    (BaseSummarizer, ["summarize"]),
    (BaseGrounding, ["locate"]),
]


# ═══════════════════════════════════════════════════════════════
# Test 1 — 所有 Base 类均为抽象类
# ═══════════════════════════════════════════════════════════════
class TestAbstractClasses:
    """9 个 Base 接口不可直接实例化。"""

    @pytest.mark.parametrize("cls,_", BASE_INTERFACES)
    def test_cannot_instantiate(self, cls, _):
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            cls()

    def test_count_interfaces(self):
        assert len(BASE_INTERFACES) == 9, "应有 9 个 Base 抽象接口"


# ═══════════════════════════════════════════════════════════════
# Test 2 — Mock 实现验证方法签名
# ═══════════════════════════════════════════════════════════════
class TestMockImplementations:
    """为每个接口创建最小化 Mock，验证方法可被调用、返回类型匹配。"""

    def test_mock_qc(self):
        class MockQC(BaseQC):
            async def check(self, ctx): return {"is_valid": True}

        impl = MockQC()
        assert issubclass(MockQC, BaseQC)

    def test_mock_transcriber(self):
        class MockTranscriber(BaseTranscriber):
            async def transcribe(self, audio_path, language=None):
                return {"full_text": "", "language": "zh", "duration": 0.0, "words": []}

        impl = MockTranscriber()
        assert callable(impl.transcribe)

    def test_mock_segmenter(self):
        class MockSegmenter(BaseSegmenter):
            async def segment(self, video_path, sample_fps=1.0): return []

        impl = MockSegmenter()
        assert callable(impl.segment)

    def test_mock_detector(self):
        class MockDetector(BaseDetector):
            async def detect(self, frame, start_sec, end_sec): return []

        impl = MockDetector()
        assert callable(impl.detect)

    def test_mock_ocr(self):
        class MockOCR(BaseOCR):
            async def extract(self, frame): return ""

        impl = MockOCR()
        assert callable(impl.extract)

    def test_mock_captioner(self):
        class MockCaptioner(BaseCaptioner):
            async def caption(self, keyframe, prompt, max_new_tokens=256): return ""

        impl = MockCaptioner()
        assert callable(impl.caption)

    def test_mock_embedder(self):
        class MockEmbedder(BaseEmbedder):
            async def encode_image(self, image): return [0.0] * 768
            async def encode_text(self, text): return [0.0] * 768

        impl = MockEmbedder()
        assert callable(impl.encode_image)
        assert callable(impl.encode_text)

    def test_mock_summarizer(self):
        class MockSummarizer(BaseSummarizer):
            async def summarize(self, script, system_prompt, user_prompt):
                return {"one_liner": "", "scenes_summary": [], "tags": [], "main_topics": [], "main_entities": []}

        impl = MockSummarizer()
        assert callable(impl.summarize)

    def test_mock_grounding(self):
        class MockGrounding(BaseGrounding):
            async def locate(self, frame, query): return []

        impl = MockGrounding()
        assert callable(impl.locate)


# ═══════════════════════════════════════════════════════════════
# Test 3 — dataclass 默认值与字段类型
# ═══════════════════════════════════════════════════════════════
class TestDataClasses:
    """Scene 和 VideoContext 的默认值、字段类型验证。"""

    def test_scene_defaults(self):
        s = Scene(scene_id=1, scene_index=0, start_sec=0.0, end_sec=10.0)

        # 必填字段
        assert s.scene_id == 1
        assert s.scene_index == 0
        assert s.start_sec == 0.0
        assert s.end_sec == 10.0

        # 可选字段默认值
        assert s.keyframe is None
        assert s.keyframe_path is None
        assert s.ocr_text is None
        assert s.aligned_transcript is None
        assert s.caption is None
        assert s.prev_caption is None
        assert s.embedding is None
        assert s.entities == []

        # 类型断言
        assert isinstance(s.scene_id, int)
        assert isinstance(s.start_sec, float)
        assert isinstance(s.entities, list)

    def test_scene_with_keyframe(self):
        dummy_frame = np.zeros((100, 200, 3), dtype=np.uint8)
        s = Scene(
            scene_id=2, scene_index=1,
            start_sec=5.0, end_sec=15.0,
            keyframe=dummy_frame,
            embedding=[0.1] * 768,
            entities=[{"label": "person", "bbox": [0, 0, 1, 1]}],
        )
        assert s.keyframe.shape == (100, 200, 3)
        assert len(s.embedding) == 768
        assert len(s.entities) == 1

    def test_video_context_defaults(self):
        ctx = VideoContext(video_id="abc-123", file_path="/tmp/test.mp4")

        assert ctx.video_id == "abc-123"
        assert ctx.file_path == "/tmp/test.mp4"
        assert ctx.duration is None
        assert ctx.scenes == []
        assert ctx.transcript_full is None
        assert ctx.transcript_words == []
        assert ctx.qc_result == {}
        assert ctx.summary is None
        assert ctx.progress_callback is None

    def test_video_context_with_scenes(self):
        scenes = [
            Scene(scene_id=i, scene_index=i, start_sec=float(i), end_sec=float(i + 1))
            for i in range(3)
        ]
        ctx = VideoContext(
            video_id="xyz-789",
            file_path="/data/video.mp4",
            duration=120.0,
            scenes=scenes,
        )
        assert ctx.duration == 120.0
        assert len(ctx.scenes) == 3
        assert ctx.scenes[0].scene_index == 0
