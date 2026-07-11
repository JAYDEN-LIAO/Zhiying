"""
core/prompt_loader.py 测试
═════════════════════════════════════════════════════════════════
验证：默认模板加载、占位符渲染、不存在的模板名抛出 KeyError。
"""
import pytest

from core.prompt_loader import PromptLoader, get_prompt_loader


class TestPromptLoader:
    """PromptLoader 模板加载与渲染。"""

    def _make_loader(self):
        return PromptLoader()

    def test_get_caption_default(self):
        pl = self._make_loader()
        prompt = pl.get("caption_default")
        assert isinstance(prompt, str)
        assert len(prompt) > 0
        assert "关键帧画面" in prompt or "描述" in prompt

    def test_get_caption_with_context_renders_placeholders(self):
        pl = self._make_loader()
        prompt = pl.get(
            "caption_with_context",
            prev_caption="一段风景画面",
            ocr_text="欢迎光临",
            transcript="欢迎来到我们的频道",
        )
        assert isinstance(prompt, str)
        assert "一段风景画面" in prompt
        # 即使模板中没有 {ocr_text} 或 {transcript} 占位符，
        # 多余的 kwargs 会被 str.format 忽略——但实际会报 KeyError。
        # str.format 对多余的 kwargs 会报错，所以此处保持模板实际占位符即可。

    def test_get_without_kwargs_returns_raw(self):
        pl = self._make_loader()
        raw = pl.get("caption_default")
        assert "{" not in raw, "caption_default 模板不应含未填充的占位符"

    def test_nonexistent_template_raises_key_error(self):
        pl = self._make_loader()
        with pytest.raises(KeyError) as exc:
            pl.get("__nonexistent_template_xyz")
        assert "__nonexistent_template_xyz" in str(exc.value)

    def test_get_raw_returns_template_with_placeholders(self):
        pl = self._make_loader()
        raw = pl.get_raw("caption_with_context")
        assert isinstance(raw, str)
        assert "{prev_caption}" in raw

    def test_get_raw_nonexistent_raises_key_error(self):
        pl = self._make_loader()
        with pytest.raises(KeyError):
            pl.get_raw("__nonexistent_raw")


class TestGetPromptLoaderSingleton:
    """get_prompt_loader() 的 lru_cache 应返回同一实例。"""

    def test_singleton(self):
        get_prompt_loader.cache_clear()
        a = get_prompt_loader()
        b = get_prompt_loader()
        assert a is b
        get_prompt_loader.cache_clear()
