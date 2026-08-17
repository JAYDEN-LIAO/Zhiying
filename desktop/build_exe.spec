# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — 智影桌面端.exe（onedir，纯产品演示启动器）。

exe = 纯产品启动器（检测就绪 → 起 db + 后端 + 开窗），**不含任何安装引导**。
安装职责全在 deploy/setup_windows.ps1（裸机→就绪，脚本/终端）。
后端代码/模型/依赖**不在 exe 里**：
  - 后端依赖/模型由安装脚本装入 .venv 与 models/
  - 后端子进程用 .venv python 从项目根 `-m desktop.backend_child` 拉起（见 checks.runtime_python）
分发形态 = dist/智影桌面端/ 文件夹 + 项目代码目录。

构建（Windows）：powershell -ExecutionPolicy Bypass -File desktop/build_exe.ps1
"""

from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

# 注意：PyInstaller 执行 spec 时，Analysis 脚本路径相对 spec 目录（desktop/）解析，
# 但 pathex 相对「进程 cwd（项目根）」解析——所以 pathex 必须用绝对路径，
# 否则 desktop/ 的兄弟模块（state/checks/backend/db/logs/webview_panel）找不到、不打进 exe。
# 用 SPECPATH（PyInstaller 文档化的 spec 目录全局）而非 __file__——spec 由 exec 执行，
# 不保证 __file__ 存在（实测会 NameError）。
SPEC_DIR = Path(SPECPATH)
a = Analysis(
    ['app.py'],
    pathex=[str(SPEC_DIR)],
    binaries=[],
    datas=[
        ('assets/zhiying.ico', 'assets'),
        ('assets/zhiying.png', 'assets'),
        # 后端字节码包（build_backend_pyc.py 生成）：客户端盘上只有 .pyc，无明文源码
        (str(SPEC_DIR.parent / 'build' / 'backend_pyc'), 'backend_pyc'),
        # 后端子进程启动器（封装模式 shell 用它拉起后端）
        (str(SPEC_DIR.parent / 'backend_launcher.py'), '.'),
    ],
    hiddenimports=['webview'] + collect_submodules('webview.platforms'),
    # ↑ 把全部平台后端都打进（win32/edgechromium/winforms/mshtml…），运行时 pywebview 自选。
    #   只写 edgechromium/winforms 会「not found」——那是旧 pythonnet 后端（import clr，
    #   pythonnet 非 pywebview 依赖）；6.x Windows 默认用 win32（纯 ctypes WebView2）。
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # 后端重依赖不在 exe（运行时由 .venv 提供）
        'torch', 'transformers', 'onnxruntime', 'tensorflow',
        'numpy', 'PIL', 'sqlalchemy', 'fastapi', 'uvicorn', 'pgvector',
        'matplotlib', 'scipy', 'pandas', 'insightface', 'hyperlpr3',
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='智影桌面端',
    icon='assets/zhiying.ico',
    console=False,      # 窗口化（无 cmd 黑框）；--check/--status 调试用 python desktop/app.py
    upx=False,          # UPX 常未安装 + 压缩产物易触发杀软误报，默认关闭
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name='智影桌面端',
)
