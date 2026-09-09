#!/usr/bin/env python3
"""
scripts/svn_sync.py — SVN 双仓备份同步（源码 → AI_Ying，产品材料 → AI_Ying_TestVersion）

仓库约定（定版）：
  AI_Ying/trunk            = 纯净最新源代码（按 git ls-files 精确镜像，天然无中间编译产物）
  AI_Ying_TestVersion/trunk/v<版本>/ = build/green/ 打包材料目录全量（安装器 [Files] 输入集 + zhiying.iss）

用法（项目根）：
  python scripts/svn_sync.py source            # 源码镜像同步 + 提交
  python scripts/svn_sync.py product           # build\green → TestVersion trunk/v<版本>/ + 提交
  python scripts/svn_sync.py source product    # 两个都同步
  加 --no-commit 只装配不提交（演练）；product 对已存在版本目录默认拒绝，--force 原地镜像修复

凭证：config/svn.local.json（gitignored，勿提交）：
  {"username": "...", "password": "..."}
"""

import json
import subprocess
import sys
from pathlib import Path

# svn 输出按 UTF-8 解码后回显，GBK 控制台打印中文路径会 UnicodeEncodeError
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
CONF_FILE = ROOT / "config" / "svn.local.json"
URL_SOURCE = "https://10.0.0.233/svn/AI_Ying"
URL_TEST = "https://10.0.0.233/svn/AI_Ying_TestVersion"
WC_SOURCE = ROOT / "build" / "svn" / "ai_ying"
WC_TEST = ROOT / "build" / "svn" / "ai_ying_test"
GREEN = ROOT / "build" / "green"


def read_version() -> str:
    m = __import__("re").search(
        r'__version__\s*=\s*"([^"]+)"', (ROOT / "core" / "version.py").read_text(encoding="utf-8")
    )
    if not m:
        sys.exit("[错误] core/version.py 里找不到 __version__")
    return m.group(1)


def git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()


def svn(base, *args, **kw):
    """执行 svn 命令（--trust-server-cert 自签证书 + 非交互）。"""
    cmd = [
        "svn", "--non-interactive", "--trust-server-cert",
        "--username", base["username"], "--password", base["password"], *args,
    ]
    r = subprocess.run(cmd, cwd=kw.get("cwd", ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0 and not kw.get("tolerate"):
        sys.exit(f"[错误] svn {' '.join(args[:2])} 失败（exit={r.returncode}）:\n{r.stderr or r.stdout}")
    return r.stdout


def load_conf() -> dict:
    if not CONF_FILE.exists():
        sys.exit(f"[错误] 缺少凭证文件 {CONF_FILE}（gitignored）：\n"
                 '  {"username": "...", "password": "..."}')
    return json.loads(CONF_FILE.read_text(encoding="utf-8"))


def sync_source(base: dict, commit: bool) -> None:
    files = subprocess.run(["git", "-c", "core.quotepath=false", "ls-files", "-z"],
                           cwd=ROOT, capture_output=True).stdout.decode("utf-8").split("\0")
    files = [f.replace("\\", "/") for f in files if f]
    print(f"git 跟踪文件 {len(files)} 个 → 镜像到 {URL_SOURCE}/trunk")

    if not (WC_SOURCE / ".svn").exists():
        WC_SOURCE.parent.mkdir(parents=True, exist_ok=True)
        svn(base, "checkout", f"{URL_SOURCE}/trunk", str(WC_SOURCE))
    else:
        svn(base, "update", cwd=WC_SOURCE)

    # 1) 删除 git 已不跟踪的旧文件（上次快照的遗留，如已退役脚本）
    stale = []
    for p in WC_SOURCE.rglob("*"):
        if ".svn" in p.parts or not p.is_file():
            continue
        rel = p.relative_to(WC_SOURCE).as_posix()
        if rel not in files:
            stale.append(rel)
    if stale:
        for i in range(0, len(stale), 50):
            svn(base, "rm", "--force", *stale[i:i + 50], cwd=WC_SOURCE)
        print(f"svn rm 旧文件 {len(stale)} 个")

    # 2) 拷贝 git 跟踪文件全集（覆盖即更新，svn add --force 收编新文件）
    import shutil
    for rel in files:
        dst = WC_SOURCE / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, dst)
    svn(base, "add", "--force", "--no-ignore", ".", cwd=WC_SOURCE)

    if not commit:
        print("[no-commit] 装配完成，未提交。")
        return
    out = svn(base, "commit", "-m", f"纯净源代码备份 v{read_version()}（git {git_head()}）", cwd=WC_SOURCE,
              tolerate=True)
    print(out.strip() or "（无输出）")


def sync_product(base: dict, commit: bool, force: bool = False) -> None:
    if not (GREEN / "zhiying.iss").exists():
        sys.exit("[错误] build\\green 材料目录不完整（缺 zhiying.iss）——先跑 desktop/make_green.ps1")
    ver = read_version()
    tag_dir = f"v{ver}"
    print(f"build\\green → {URL_TEST}/trunk/{tag_dir}/")

    if not (WC_TEST / ".svn").exists():
        WC_TEST.parent.mkdir(parents=True, exist_ok=True)
        svn(base, "checkout", f"{URL_TEST}/trunk", str(WC_TEST))
    else:
        svn(base, "update", cwd=WC_TEST)

    dest = WC_TEST / tag_dir
    exists = bool(svn(base, "list", f"{URL_TEST}/trunk/{tag_dir}", tolerate=True).strip())
    if exists and not force:
        sys.exit(f"[错误] {URL_TEST}/trunk/{tag_dir} 已存在——版本号未 bump？删掉旧目录或先 ./bump，"
                 "或加 --force 原地镜像修复")

    if exists:
        # 原地镜像：删除远端有、green 没有的文件（防旧残留）
        local = {p.relative_to(GREEN).as_posix() for p in GREEN.rglob("*") if p.is_file()}
        stale = [p.relative_to(WC_TEST).as_posix() for p in dest.rglob("*")
                 if p.is_file() and p.relative_to(WC_TEST).as_posix() not in local]
        if stale:
            for i in range(0, len(stale), 50):
                svn(base, "rm", "--force", *stale[i:i + 50], cwd=WC_TEST)
            print(f"svn rm 旧文件 {len(stale)} 个")

    import shutil
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(GREEN, dest, dirs_exist_ok=True)
    # --no-ignore 必须：svn 默认忽略 *.pyc，而 backend_pyc 恰是封装后端的核心
    svn(base, "add", "--force", "--no-ignore", tag_dir, cwd=WC_TEST)

    if not commit:
        print(f"[no-commit] 装配完成（{dest}），未提交。")
        return
    out = svn(base, "commit", f"-m", f"交付材料 {tag_dir}（git {git_head()}）", cwd=WC_TEST, tolerate=True)
    print(out.strip() or "（无输出）")


def main() -> int:
    args = [a for a in sys.argv[1:] if a not in ("--no-commit", "--force")]
    if not args or any(a not in ("source", "product") for a in args):
        print(__doc__)
        return 1
    base = load_conf()
    commit = "--no-commit" not in sys.argv
    force = "--force" in sys.argv
    if "source" in args:
        sync_source(base, commit)
    if "product" in args:
        sync_product(base, commit, force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
