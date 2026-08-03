"""Generate a Windows deployment config from config/config.yaml.

Two deployment modes:

  full        — 全功能（除本地视觉摘要大模型）：embedding + yolo + face + plate
                + segmenter + 摘要 API(vlm_llm: DashScope + DeepSeek)
  searchless  — 同 full，但关闭 embedding（不做向量语义检索）

面板置灰的功能（音频转录 / OCR / Grounding）不配置：transcriber 保持 null，
与基础 config.yaml 一致；本地视觉摘要大模型同样不配置（走 DashScope API）。

The generated file is written to config/config.windows.yaml and is loaded by the
backend when the CERNO_CONFIG environment variable points at it
(see core/config_loader.py). The original config.yaml is never modified.

The local caption model (Qwen3-VL-8B-Instruct) is intentionally NOT configured:
captioning always goes through the DashScope API (qwen_api), and summary always
through vlm_llm mode. API keys are injected at runtime from the frontend
settings page (data/settings.json) or environment variables.
"""

from __future__ import annotations

import argparse
import copy
import os
import sys
from pathlib import Path

import yaml

DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"


def build_config(base: dict, project_root: Path, mode: str) -> dict:
    cfg = copy.deepcopy(base)
    plugins = cfg.setdefault("plugins", {})

    # ── captioner：无本地模型 → 一律走 DashScope API ──
    plugins["captioner"] = {
        "backend": "qwen_api",
        "params": {
            "base_url": DASHSCOPE_BASE_URL,
            "api_key": "placeholder",  # 运行时由 .env / settings.json 注入
            "model_name": "qwen-vl-max",
            "with_context": True,
        },
    }

    # ── summarizer：DeepSeek API（vlm_llm 模式）──
    plugins["summarizer"] = {
        "backend": "vllm",
        "base_url": DEEPSEEK_BASE_URL,
        "api_key": "placeholder",
        "model_name": "deepseek-chat",
        "max_tokens": 2048,
        "temperature": 0.1,
    }

    # ── embedder：full 启用，searchless 关闭 ──
    if mode == "searchless":
        plugins["embedder"] = {"backend": None}
    else:
        embed = plugins.get("embedder") or {}
        embed["backend"] = "qwen3_vl_embedding_8b"
        embed.setdefault("params", {})
        embed["params"]["model_name"] = str(
            project_root / "models" / "Qwen" / "Qwen3-VL-Embedding-8B"
        ).replace("\\", "/")
        plugins["embedder"] = embed

    # ── 其他插件（segmenter/detector/face/plate/ocr/grounding/transcriber）沿用 base ──
    # transcriber 在 base 中是 null（面板置灰、opt-in），部署保持关闭。
    for keep in ("segmenter", "detector", "face", "plate", "ocr", "grounding", "transcriber"):
        if keep in base.get("plugins", {}) and keep not in plugins:
            plugins[keep] = base["plugins"][keep]

    # ── storage：绝对路径，避免 cwd 漂移 ──
    storage = cfg.setdefault("storage", {})
    storage["video_dir"] = str(project_root / "data" / "videos").replace("\\", "/")
    storage["artifact_dir"] = str(project_root / "data" / "artifacts").replace("\\", "/")

    # ── database：POSTGRES_URI 环境变量优先，否则默认本机 Docker db ──
    db = cfg.setdefault("database", {})
    db["uri"] = os.environ.get(
        "POSTGRES_URI",
        "postgresql+asyncpg://cerno:cerno@localhost:5432/cerno",
    )

    # ── pipeline：默认 vlm_llm 摘要模式（无本地 caption 模型）──
    pipeline = cfg.setdefault("pipeline", {})
    pipeline["default_summary_mode"] = "vlm_llm"

    return cfg


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=["full", "searchless"], default="full",
        help="full=全功能(默认)；searchless=不含 embedding",
    )
    parser.add_argument(
        "--project-root", type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Cerno 项目根目录",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="输出路径（默认 config/config.windows.yaml）",
    )
    parser.add_argument("--base", type=Path, default=None, help="基础配置路径")
    args = parser.parse_args()

    root = args.project_root.resolve()
    base_path = args.base or (root / "config" / "config.yaml")
    output = args.output or (root / "config" / "config.windows.yaml")

    if not base_path.is_file():
        print(f"error: base config not found: {base_path}", file=sys.stderr)
        return 1

    with open(base_path, encoding="utf-8") as f:
        base = yaml.safe_load(f)

    cfg = build_config(base, root, args.mode)

    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)

    embedder_backend = cfg["plugins"].get("embedder", {}).get("backend")
    print(f"written: {output}")
    print(f"mode: {args.mode} | embedder: {embedder_backend or 'disabled'}")
    print(f"captioner: qwen_api | transcriber: disabled (面板置灰功能不装)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
