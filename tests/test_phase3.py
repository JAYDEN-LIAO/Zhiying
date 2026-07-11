"""
pipeline/phase3_alignment.py 单元测试
═════════════════════════════════════════════════════════════════
构造 3 个 Scene 和字词时间戳，验证模态交叉对齐正确性。
"""
from unittest.mock import AsyncMock

import pytest

from core.interfaces import VideoContext, Scene as SceneData
from pipeline.phase3_alignment import Phase3Alignment


def _make_scenes(boundaries: list[tuple[float, float]]) -> list[SceneData]:
    """从时间边界列表创建 Scene 列表。"""
    result = []
    for i, (start, end) in enumerate(boundaries):
        result.append(SceneData(
            scene_id=i,
            scene_index=i,
            start_sec=start,
            end_sec=end,
        ))
    return result


def _make_words(timestamps: list[tuple[str, float, float]]) -> list[dict]:
    """从 (word, start, end) 列表创建字词列表。"""
    return [
        {"word": w, "start": s, "end": e, "confidence": 0.9}
        for w, s, e in timestamps
    ]


class TestPhase3Alignment:
    """Phase3 模态交叉对齐。"""

    def _execute(self, scenes, words):
        """辅助：快速执行对齐并返回 scenes。"""
        ctx = VideoContext(video_id="test", file_path="/tmp/test.mp4")
        ctx.scenes = scenes
        ctx.transcript_words = words
        engine = Phase3Alignment(
            ctx=ctx, plugins={}, config={},
            tracker=AsyncMock(),
        )
        import asyncio
        asyncio.run(engine.execute())
        return ctx.scenes

    # ── 基本对齐测试 ──
    def test_words_assigned_to_correct_scenes(self):
        """属于不同时间窗口的词应分配到正确的 scene。"""
        scenes = _make_scenes([(0, 10), (10, 20), (20, 30)])
        words = _make_words([
            ("hello", 0.0, 1.0),       # scene 0
            ("world", 5.0, 6.0),       # scene 0
            ("foo",   12.0, 13.0),     # scene 1
            ("bar",   15.0, 16.0),     # scene 1
            ("baz",   22.0, 23.0),     # scene 2
            ("qux",   25.0, 26.0),     # scene 2
        ])
        result = self._execute(scenes, words)

        assert result[0].aligned_transcript == "hello world", (
            f"Scene 0 应为 'hello world'，实际 '{result[0].aligned_transcript}'"
        )
        assert result[1].aligned_transcript == "foo bar", (
            f"Scene 1 应为 'foo bar'，实际 '{result[1].aligned_transcript}'"
        )
        assert result[2].aligned_transcript == "baz qux", (
            f"Scene 2 应为 'baz qux'，实际 '{result[2].aligned_transcript}'"
        )

    def test_scene0_does_not_contain_later_words(self):
        """Scene 0 不应包含 Scene 1 时间窗口内的词。"""
        scenes = _make_scenes([(0, 10), (10, 20)])
        words = _make_words([
            ("scene0_word", 5.0, 6.0),
            ("scene1_word", 12.0, 13.0),
        ])
        result = self._execute(scenes, words)

        assert "scene1_word" not in (result[0].aligned_transcript or ""), (
            f"Scene 0 不应包含 scene1_word: '{result[0].aligned_transcript}'"
        )
        assert "scene1_word" in (result[1].aligned_transcript or ""), (
            f"Scene 1 应包含 scene1_word: '{result[1].aligned_transcript}'"
        )

    def test_boundary_exact_start(self):
        """word.start == scene.start_sec 应划入该 scene（<= 语义）。"""
        scenes = _make_scenes([(0, 10)])
        words = _make_words([("edge", 0.0, 1.0)])
        result = self._execute(scenes, words)
        assert "edge" in (result[0].aligned_transcript or ""), (
            "start=0.0 的词应划入 scene"
        )

    # ── 边界值与异常场景 ──

    def test_no_words(self):
        """没有 transcript_words 时，scenes 的 aligned_transcript 应为 None。"""
        scenes = _make_scenes([(0, 10)])
        result = self._execute(scenes, [])
        assert result[0].aligned_transcript is None

    def test_no_scenes(self):
        """没有 scenes 时不应崩溃。"""
        result = self._execute([], [{"word": "x", "start": 0.0, "end": 1.0}])
        assert result == []

    def test_word_start_before_first_scene(self):
        """word.start < 0 的词应被跳过。"""
        scenes = _make_scenes([(0, 10)])
        words = _make_words([
            ("before", -5.0, -2.0),   # 被跳过
            ("normal", 5.0, 6.0),     # 正常分配
        ])
        result = self._execute(scenes, words)
        assert "before" not in (result[0].aligned_transcript or ""), (
            "负时间词不应被分配"
        )
        assert "normal" in (result[0].aligned_transcript or "")

    def test_remaining_words_appended_to_last_scene(self):
        """超出所有 scene 时间范围的词应追加到最后一个 scene。"""
        scenes = _make_scenes([(0, 5), (5, 10)])
        words = _make_words([
            ("first", 1.0, 2.0),
            ("second", 12.0, 13.0),   # 超出 scene 1 范围
        ])
        result = self._execute(scenes, words)
        assert "first" in (result[0].aligned_transcript or "")
        assert "second" in (result[1].aligned_transcript or ""), (
            "超出范围的词应追加到最后一个 scene"
        )
