#!/usr/bin/env python3
"""
deploy/download_qwen25_3b.py
═══════════════════════════════════════════════════════════
Qwen2.5-3B-Instruct 底座模型下载（v0.37 LLM 增强子系统用）。

完全沿用 deploy/download_models.py 的下载风格：
  - ModelScope API 单文件直链
  - 单文件断点续传（.incomplete → 原子 rename）
  - 强制直连（_NoProxy），不绕国际
  - safetensors 头部校验（防断点续传拼接出损坏文件）
  - 校验完整性后才算完成

为什么不用 modelscope.snapshot_download：
  实测魔搭 snapshot_download 在某些网络环境下对 Qwen2.5 系列报 404
  （tokenizer.json 路径错误），但单文件 API 直链是稳定的。

用法:
    # 下载到 models/Qwen/Qwen2.5-3B-Instruct/
    python deploy/download_qwen25_3b.py

    # 自定义目标
    python deploy/download_qwen25_3b.py --target models/Qwen2.5-3B

    # 只校验不下载
    python deploy/download_qwen25_3b.py --verify-only

    # 完成后可清理 .incomplete 残留
    python deploy/download_qwen25_3b.py --cleanup
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

# 沿用 deploy/download_models.py 的 _NoProxy 思路
class _NoProxy:
    """国内源（modelscope）绝不走代理——绕国际反而更慢更易断。"""

    def __enter__(self):
        self._old = (os.environ.get("NO_PROXY"), os.environ.get("no_proxy"))
        os.environ["NO_PROXY"] = "*"
        os.environ["no_proxy"] = "*"

    def __exit__(self, *exc):
        if self._old[0] is None:
            os.environ.pop("NO_PROXY", None)
        else:
            os.environ["NO_PROXY"] = self._old[0]
        if self._old[1] is None:
            os.environ.pop("no_proxy", None)
        else:
            os.environ["no_proxy"] = self._old[1]


# 魔搭 API 单文件直链
MODELSCOPE_FILE_URL = "https://www.modelscope.cn/api/v1/models/{model_id}/repo?Revision={rev}&FilePath={file}"

# Qwen2.5-3B-Instruct 实际文件清单（13 个，从魔搭 API 实测）
Qwen2_5_3B_FILES = [
    ".gitattributes",
    "LICENSE",
    "README.md",
    "config.json",
    "configuration.json",
    "generation_config.json",
    "merges.txt",
    "vocab.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "model.safetensors.index.json",
    "model-00001-of-00002.safetensors",
    "model-00002-of-00002.safetensors",
]

MODEL_ID = "Qwen/Qwen2.5-3B-Instruct"
DEFAULT_TARGET = Path("models/Qwen/Qwen2.5-3B-Instruct")


def _retry(msg: str, retries: int, fn, *args, **kwargs):
    """带指数退避的重试包装"""
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            print(f"[download] {msg} (attempt {attempt}/{retries})")
            fn(*args, **kwargs)
            return
        except Exception as exc:
            last_error = exc
            print(f"[warn] {msg} failed: {exc}", file=sys.stderr)
            if attempt < retries:
                time.sleep(min(10 * attempt, 30))
    raise RuntimeError(f"{msg} failed after {retries} attempts") from last_error


def _download_modelscope_file(url: str, target: Path) -> None:
    """ModelScope 单文件断点续传（.incomplete → 原子改名）。"""
    import requests

    partial = target.with_name(target.name + ".incomplete")
    start = partial.stat().st_size if partial.exists() else 0
    headers = {"User-Agent": "zhiying-llm-enhancement/1.0"}
    if start:
        headers["Range"] = f"bytes={start}-"

    with _NoProxy(), requests.get(
        url, headers=headers, stream=True, timeout=(30, 300), allow_redirects=True
    ) as resp:
        resp.raise_for_status()
        if start and resp.status_code != 206:
            start = 0
            partial.unlink(missing_ok=True)
        content_length = resp.headers.get("Content-Length")
        total = (int(content_length) + start) if content_length else None
        downloaded = start
        last_pct = -1
        with partial.open("ab" if start else "wb") as out:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                out.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = int(downloaded * 100 / total)
                    if pct != last_pct:
                        print(
                            f"\r[progress] {target.name} {pct:3d}% "
                            f"({downloaded/1048576:.0f}/{total/1048576:.0f} MiB)",
                            end="",
                            flush=True,
                        )
                        last_pct = pct
    print()
    if downloaded <= 0:
        raise RuntimeError(f"{target.name}: download produced no data")
    # safetensors 头部校验
    if target.name.endswith(".safetensors"):
        try:
            from safetensors import safe_open
            with safe_open(str(partial), framework="pt") as _f:
                _ = len(_f.keys())
        except Exception as exc:
            partial.unlink(missing_ok=True)
            raise RuntimeError(f"{target.name}: 下载文件损坏（{exc}），删除重下")
    os.replace(partial, target)


def download_file(model_id: str, file_name: str, target: Path, retries: int) -> None:
    """下载单个文件（带重试）"""
    if target.is_file():
        print(f"[skip] {file_name} already exists ({target.stat().st_size} bytes)")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    url = MODELSCOPE_FILE_URL.format(model_id=model_id, rev="master", file=file_name)
    _retry(
        f"{file_name}",
        retries,
        _download_modelscope_file,
        url,
        target,
    )


def model_complete(target: Path) -> bool:
    """校验模型完整性：必须有大模型分片 + config.json + tokenizer.json"""
    if not (target / "config.json").is_file():
        return False
    if not (target / "tokenizer.json").is_file():
        return False
    # 检查 model.safetensors（单文件）或分片
    if (target / "model.safetensors").is_file():
        return True
    index_path = target / "model.safetensors.index.json"
    if index_path.is_file():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
            required = set(index.get("weight_map", {}).values())
            return bool(required) and all(
                (target / Path(p).name).is_file() for p in required
            )
        except (OSError, json.JSONDecodeError, TypeError):
            return False
    return False


def download_qwen25_3b(target: Path, retries: int) -> None:
    """下载整个 Qwen2.5-3B-Instruct"""
    if model_complete(target):
        print(f"[skip] Qwen2.5-3B-Instruct already complete: {target}")
        return

    target.mkdir(parents=True, exist_ok=True)
    print(f"[1/2] 下载 {len(Qwen2_5_3B_FILES)} 个文件到 {target}")
    for i, fname in enumerate(Qwen2_5_3B_FILES, 1):
        print(f"\n[{i}/{len(Qwen2_5_3B_FILES)}] {fname}")
        download_file(MODEL_ID, fname, target / fname, retries)

    if not model_complete(target):
        raise RuntimeError("download finished but model files are incomplete")
    print(f"\n[ok] Qwen2.5-3B-Instruct verified: {target}")


def cleanup(target: Path) -> None:
    """清理 .incomplete 残留"""
    removed = 0
    for p in target.rglob("*.incomplete"):
        p.unlink()
        print(f"[cleanup] removed {p}")
        removed += 1
    for p in target.rglob("*.part"):
        p.unlink()
        print(f"[cleanup] removed {p}")
        removed += 1
    if not removed:
        print("[cleanup] no residue found")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        type=Path,
        default=DEFAULT_TARGET,
        help="下载目标目录（默认 models/Qwen/Qwen2.5-3B-Instruct）",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="每个文件的重试次数（默认 3）",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="只校验完整性，不下载",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="清理 .incomplete / .part 残留",
    )
    args = parser.parse_args()

    target = args.target.resolve()

    if args.cleanup:
        cleanup(target)
        return 0

    if args.verify_only:
        ok = model_complete(target)
        print(f"Qwen2.5-3B-Instruct at {target}: {'OK' if ok else 'MISSING/INCOMPLETE'}")
        return 0 if ok else 2

    download_qwen25_3b(target, args.retries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
