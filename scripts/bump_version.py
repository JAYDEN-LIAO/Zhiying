#!/usr/bin/env python3
"""
scripts/bump_version.py — Cerno 版本号提升工具（交互式）

一条命令完成：改版本号 → 输入提交信息 → 确认提交 → 确认打 tag → 确认推送。
每一步发布相关操作都会问你是否执行（默认否），所以：
  - 不用复制粘贴命令（命令由脚本执行）
  - 但 提交 / 打 tag / 推送 都必须你亲手按 y 才做（不纯交给机器）

提交信息支持自定义（如 `feat: 车牌识别增强` + 多行详细描述），空行回车则用默认值。

用法：
  ./bump minor            # 0.22.0 → 0.23.0（新功能，中间位 +1）
  ./bump patch            # 0.22.0 → 0.22.1（修 bug，末位 +1）
  ./bump 0.24.0           # 直接指定完整版本号
  ./bump --dry-run minor  # 只预览，不改任何文件
  ./bump -m "feat: ..." minor  # 非交互：直接用 -m 指定的提交信息
  ./bump                  # 只看当前版本

提交采用 `git add .`（一次性提交你当前所有未提交改动）。
"""

import json
import re
import subprocess
import sys
from pathlib import Path

# 启用 GNU readline：否则 input() 退格/方向键失效（箭头会变成 ^[[D 乱码），
# 中文提交信息也容易被截断。装了 readline 模块的系统行编辑立即生效。
try:
    import readline  # noqa: F401
except ImportError:
    pass

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "core" / "version.py"
PKG_FILE = ROOT / "frontend" / "package.json"
LOCK_FILE = ROOT / "frontend" / "package-lock.json"
SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def read_version() -> str:
    m = re.search(r'__version__\s*=\s*"([^"]+)"', VERSION_FILE.read_text(encoding="utf-8"))
    if not m:
        sys.exit(f"[错误] {VERSION_FILE} 里找不到 __version__")
    return m.group(1)


def next_version(current: str, bump: str) -> str:
    m = SEMVER_RE.match(current)
    if not m:
        sys.exit(f"[错误] 当前版本号格式不对: {current}")
    major, minor, patch = (int(g) for g in m.groups())
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    if bump == "patch":
        return f"{major}.{minor}.{patch + 1}"
    if SEMVER_RE.match(bump):
        return bump
    sys.exit(f"[错误] 参数不认识: {bump}（支持 minor / patch / 三段式版本号）")


def edit_file(path: Path, pattern: re.Pattern, repl: str) -> None:
    text = path.read_text(encoding="utf-8")
    new_text, n = pattern.subn(repl, text, count=1)
    if n:
        path.write_text(new_text, encoding="utf-8")
    else:
        sys.exit(f"[错误] 在 {path} 里没找到要改的位置")


def edit_json_version(path: Path, new_ver: str) -> None:
    """精确改 JSON 版本号（保留原格式，indent=2）：
    package.json 改顶层 version；package-lock.json 还要改 packages[""].version
    （锁文件两处根版本不同步会让 npm ci 报错，依赖包版本不动）。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        sys.exit(f"[错误] 读 {path} 失败: {e}")
    data["version"] = new_ver
    if path.name == "package-lock.json":
        root_pkg = data.get("packages", {}).get("", {})
        if root_pkg:
            root_pkg["version"] = new_ver
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run(args: list) -> None:
    print(f"  $ git {' '.join(args)}")
    r = subprocess.run(["git", *args], cwd=ROOT)
    if r.returncode != 0:
        sys.exit(f"[错误] 命令失败: git {' '.join(args)}")


def ask(question: str) -> bool:
    try:
        ans = input(f"\n{question} [y/N] ").strip().lower()
    except EOFError:
        return False
    return ans in ("y", "yes")


def input_message(default: str) -> str:
    """交互式输入提交信息：先输标题（回车用默认），再可选补充多行描述。"""
    subject = ""
    try:
        print(f"\n提交标题（直接回车用默认「{default}」）: ", end="", flush=True)
        subject = input().strip()
        if not subject:
            return default
        print("补充描述（可选，可多行，直接空行结束）: ")
        body = []
        while True:
            line = input()
            if line == "":
                break
            body.append(line)
    except EOFError:
        return subject or default
    return subject + (("\n\n" + "\n".join(body)) if body else "")


def main() -> int:
    args = [a for a in sys.argv[1:] if a not in ("--dry-run",)]
    dry_run = "--dry-run" in sys.argv[1:]
    msg = None
    if "-m" in args:
        i = args.index("-m")
        if len(args) <= i + 1:
            sys.exit('[错误] -m 后面缺少提交信息，例如: ./bump minor -m "feat: xxx"')
        msg = args[i + 1]
        del args[i:i + 2]

    current = read_version()
    if not args:
        print(f"当前版本: {current}")
        return 0

    new_ver = next_version(current, args[0])
    if current == new_ver:
        print(f"版本没变化（{current}），无需操作。")
        return 0

    print(f"当前版本: {current}  →  新版本号: {new_ver}")

    if dry_run:
        print("[dry-run] 将修改: core/version.py, frontend/package.json, frontend/package-lock.json")
        print("[dry-run] 未改动任何文件。")
        return 0

    # ── 1. 改版本号文件 ─────────────────────────────
    edit_file(VERSION_FILE, re.compile(r'__version__\s*=\s*"[^"]+"'), f'__version__ = "{new_ver}"')
    edit_json_version(PKG_FILE, new_ver)
    if LOCK_FILE.exists():
        edit_json_version(LOCK_FILE, new_ver)
    print(f"✓ 版本号已改为 {new_ver}（core/version.py + frontend/package.json + package-lock.json）")

    # ── 2. 展示即将被提交的内容（git add . 会全带上）──
    print("\n以下是你当前所有未提交改动（将用 git add . 一起提交）：")
    run(["status", "--short"])

    # ── 3. 输入提交信息（可用默认，也可自定义 feat/fix 等）──
    default_msg = f"chore: bump {new_ver}"
    commit_msg = msg if msg is not None else input_message(default_msg)
    print(f"\n提交信息:\n{commit_msg}")

    # ── 4. 手动确认：提交 + 打 tag ──────────────────
    if not ask(f"确认用 git add . 提交上述改动并打 tag v{new_ver}？"):
        print("\n已跳过提交/tag。文件已改好，可稍后手动处理。")
        return 0

    run(["add", "."])
    run(["commit", "-m", commit_msg])
    # 附注 tag（-a -m）：git push --follow-tags 只跟随附注 tag，轻量 tag 不会被自动推
    run(["tag", "-a", f"v{new_ver}", "-m", f"Release {new_ver}"])

    # ── 5. 手动确认：推送 ──────────────────────────
    if ask("推送到 GitHub（main + tag）？"):
        run(["push", "origin", "main"])
        run(["push", "origin", f"v{new_ver}"])
        print(f"\n✓ v{new_ver} 已发布。")
    else:
        print(f"\n已在本地完成（提交 + tag v{new_ver}），未推送。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
