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

a = Analysis(
    ['desktop/app.py'],
    pathex=['desktop'],
    binaries=[],
    datas=[
        ('desktop/assets/zhiying.ico', 'assets'),
        ('desktop/assets/zhiying.png', 'assets'),
    ],
    hiddenimports=[
        'webview',                       # run_gui 内 lazy import，显式兜底
        'webview.platforms.edgechromium',  # Windows WebView2 后端
        'webview.platforms.winforms',
    ],
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
    icon='desktop/assets/zhiying.ico',
    console=False,      # 窗口化（无 cmd 黑框）；--check/--status 调试用 python desktop/app.py
    upx=False,          # UPX 常未安装 + 压缩产物易触发杀软误报，默认关闭
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name='智影桌面端',
)
