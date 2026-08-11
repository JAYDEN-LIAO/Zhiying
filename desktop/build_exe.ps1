# ═══════════════════════════════════════════════════════════
#  智影桌面端 · Windows EXE 构建脚本（PyInstaller, onedir）
#  用法（Windows，项目根）：
#    powershell -ExecutionPolicy Bypass -File desktop/build_exe.ps1
#  产物：dist\智影桌面端\智影桌面端.exe
#  分发：dist\智影桌面端\ 整个文件夹 + 项目代码目录（缺的 .venv/模型/ffmpeg 由 exe 引导补）
# ═══════════════════════════════════════════════════════════
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
Write-Host "项目根: $Root"

$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    throw "未找到 .venv\Scripts\python.exe —— 先跑 deploy/setup_windows.ps1（或手动建 .venv）"
}

Write-Host "安装 pyinstaller（构建期依赖，不进运行时）…"
& $Py -m pip install --quiet pyinstaller

Write-Host "构建 智影桌面端.exe …"
& $Py -m PyInstaller desktop\build_exe.spec --noconfirm --clean

Write-Host ""
Write-Host "✅ 构建完成: dist\智影桌面端\智影桌面端.exe"
Write-Host "分发 = dist\智影桌面端\ 文件夹 + 项目代码目录"
Write-Host "（目标机首次双击 exe → 准备模式引导：Python 复用/建 .venv/装依赖/下载模型/ffmpeg → 就绪后自动变启动器）"
