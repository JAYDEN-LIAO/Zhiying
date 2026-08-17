"""把后端源码编译成 .pyc 字节码包 → build/backend_pyc/（客户端无明文 .py）。

用途：PyInstaller 封装的后端子进程从该字节码包 import（藏代码：客户端盘上只有
字节码，没有可读的 .py 源码）。由 build_exe.ps1 在打 exe 前调用，产物作为
datas 打进 _internal。

产物结构（保持包结构，.py 删除，__pycache__/*.pyc 保留）：
    build/backend_pyc/
      main.pyc
      api/  core/  pipeline/  services/  plugins/  utils/
      config/prompts.yaml        # 运行时提示词模板（config.yaml 是机器相关，不打包）
"""
from __future__ import annotations

import compileall
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = ["api", "core", "pipeline", "services", "plugins", "utils"]
OUT = ROOT / "build" / "backend_pyc"


def _compile_tree(dst: Path) -> None:
    """编译目录下全部 .py 为 __pycache__/*.pyc，然后删除 .py。"""
    compileall.compile_dir(str(dst), force=True, quiet=1)
    for f in dst.rglob("*.py"):
        f.unlink()


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    # 包：拷贝（去旧字节码）→ 编译 → 删 .py
    for pkg in PACKAGES:
        src = ROOT / pkg
        if not src.is_dir():
            print(f"[skip] {pkg} 不存在")
            continue
        dst = OUT / pkg
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        _compile_tree(dst)
        print(f"[ok] {pkg} → {dst.relative_to(ROOT)}")

    # main.py：编译产物 → OUT/main.pyc（启动器 import main 用）
    main_src = ROOT / "main.py"
    if main_src.is_file():
        compileall.compile_file(str(main_src), force=True, quiet=1)
        pyc = ROOT / "__pycache__" / ("main" + _pyc_suffix())
        if pyc.is_file():
            shutil.move(str(pyc), OUT / "main.pyc")
        else:
            print("[warn] main.pyc 未找到")
    else:
        print("[warn] main.py 不存在")

    # prompts.yaml
    (OUT / "config").mkdir(parents=True, exist_ok=True)
    prompts = ROOT / "config" / "prompts.yaml"
    if prompts.is_file():
        shutil.copy(prompts, OUT / "config" / "prompts.yaml")
    else:
        print("[warn] config/prompts.yaml 不存在")

    total = sum(1 for _ in OUT.rglob("*.pyc"))
    print(f"完成：{total} 个字节码文件 → {OUT.relative_to(ROOT)}/")
    return 0


def _pyc_suffix() -> str:
    ver = f"cpython-{sys.version_info.major}{sys.version_info.minor}"
    return f".{ver}.pyc"


if __name__ == "__main__":
    raise SystemExit(main())
