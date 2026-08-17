"""
core/prompt_loader.py
═══════════════════════════════════════════════════════════
Prompt 模板加载与渲染器。

所有 VLM/LLM 提示词从 config/prompts.yaml 加载，
不在业务代码中硬编码。切换 prompt 只需改 YAML，不碰代码。
"""

from pathlib import Path
from functools import lru_cache

import yaml

from core.paths import project_root

# 项目根：封装模式（字节码包）由启动器注入 ZHIYING_PROJECT_ROOT，源码模式回退推断。
_PROJECT_ROOT = project_root()
_DEFAULT_PROMPT_FILE = _PROJECT_ROOT / "config" / "prompts.yaml"


class PromptLoader:
    """提示词模板加载与渲染器。

    应用启动时加载一次（通过 get_prompt_loader() 单例工厂），
    业务代码通过 get() 获取并渲染模板。

    Usage:
        pl = get_prompt_loader()
        prompt = pl.get("caption_with_context",
            prev_caption="...",
            ocr_text="...",
            transcript="...",
        )
    """

    def __init__(self, prompt_path: str | Path = _DEFAULT_PROMPT_FILE):
        path = Path(prompt_path)
        if not path.exists():
            raise FileNotFoundError(f"Prompt file not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            self._templates: dict[str, str] = yaml.safe_load(f)

    def get(self, name: str, **kwargs: str) -> str:
        """获取模板并用 kwargs 渲染（str.format）。

        Args:
            name: 模板名（对应 prompts.yaml 中的键）。
            **kwargs: 模板变量值。

        Returns:
            渲染后的完整提示词字符串。
        """
        template = self._templates.get(name)
        if template is None:
            raise KeyError(
                f"Prompt template '{name}' not found in prompts.yaml"
            )
        return template.format(**kwargs) if kwargs else template

    def get_raw(self, name: str) -> str:
        """获取原始模板（不做 format 渲染）。"""
        template = self._templates.get(name)
        if template is None:
            raise KeyError(
                f"Prompt template '{name}' not found in prompts.yaml"
            )
        return template


@lru_cache(maxsize=1)
def get_prompt_loader() -> PromptLoader:
    """全局 PromptLoader 单例工厂。

    由于 lru_cache 的存在，整个进程生命周期内只加载一次 YAML，
    后续调用全部返回缓存实例。

    Returns:
        已加载好 prompts.yaml 的 PromptLoader 实例。
    """
    return PromptLoader()
