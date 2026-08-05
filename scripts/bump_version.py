#!/usr/bin/env python3
"""
scripts/bump_version.py — Cerno 一键版本号提升工具

替代「手动改两个文件 + 手打 git 命令」的重复劳动：
  1. 同步修改 core/version.py、frontend/package.json、frontend/package-lock.json 的版本号
  2. 打印配套的 git 命令（commit / tag / push），由你确认后执行（脚本不自动提交/推送）

用法：
  python scripts/bump_version.py minor      # 0.22.0 → 0.23.0（新功能：中间位 +1）
  python scripts/bump_version.py patch      # 0.22.0 → 0.22.1（修 bug：末位 +1）
  python scripts/bump_version.py 0.24.0     # 直接指定完整版本号（必须三段式，如 0.24.0）
  python scripts/bump_version.py --dry-run  # 只显示会改成什么，不改文件
  python scripts/bump_version.py            # 只显示当前版本

约定：改完版本号后，git tag 必须命名为 v<版本号>（如 v0.23.0），与 core/version.py 完全一致。
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "core" / "version.py"
PKG_FILE = ROOT / "frontend" / "package.json"
LOCK_FILE = ROOT / "frontend" / "package-lock.json"

SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def read_version() -> str:
    m = re.search(r'__version__\s*=\s*"([^"]+)"', VERSION_FILE.read_text(encoding="utf-8"))
    if not m:
        sys.exit(f"[ERROR] 找不到 {VERSION_FILE} 中的 __version__")
    return m.group(1)


def next_version(current: str, bump: str) -> str:
    m = SEMVER_RE.match(current)
    if not m:
        sys.exit(f"[ERROR] 当前版本号格式不合法: {current}")
    major, minor, patch = (int(g) for g in m.groups())
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    if bump == "patch":
        return f"{major}.{minor}.{patch + 1}"
    if SEMVER_RE.match(bump):
        return bump
    sys.exit(f"[ERROR] 未知的版本参数: {bump}（支持 minor / patch / 三段式版本号）")


def apply_text(path: Path, pattern: re.Pattern, repl: str) -> bool:
    """替换文件中第一处匹配；返回是否真的改动了。"""
    text = path.read_text(encoding="utf-8")
    new_text, n = pattern.subn(repl, text, count=1)
    if n:
        path.write_text(new_text, encoding="utf-8")
    return n > 0


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    dry_run = "--dry-run" in sys.argv[1:]

    current = read_version()
    if not args:
        print(f"当前版本: {current}")
        return 0

    new_ver = next_version(current, args[0])
    if current == new_ver:
        print(f"版本没变化（{current}），无需操作。")
        return 0

    print(f"当前版本: {current}")
    print(f"新版本号: {new_ver}")
    print()

    files = [VERSION_FILE, PKG_FILE]
    if LOCK_FILE.exists():
        files.append(LOCK_FILE)

    for f in files:
        if f == VERSION_FILE:
            pattern = re.compile(r'__version__\s*=\s*"[^"]+"')
            repl = f'__version__ = "{new_ver}"'
        else:
            pattern = re.compile(r'"version"\s*:\s*"[^"]+"')
            repl = f'"version": "{new_ver}"'
        if dry_run:
            print(f"[dry-run] 将修改 {f.relative_to(ROOT)}")
        else:
            changed = apply_text(f, pattern, repl)
            print(f"[{'OK' if changed else 'SKIP'}] {f.relative_to(ROOT)}")

    if dry_run:
        print()
        print("（dry-run 模式，未改动任何文件）")
        return 0

    print()
    print("接下来执行（可复制）：")
    print(f"  git add core/version.py frontend/package.json"
          + (f" frontend/package-lock.json" if LOCK_FILE.exists() else ""))
    print(f'  git commit -m "chore: bump {new_ver}"')
    print(f"  git tag v{new_ver} && git push origin main && git push origin v{new_ver}")
    print()
    print(f"tag 必须命名为 v{new_ver}，与 core/version.py 一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
