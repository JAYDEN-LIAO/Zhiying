# ═══════════════════════════════════════════════════════════
#  智影桌面端 · Windows EXE 构建脚本（PyInstaller, onedir）
#  用法（Windows，项目根）：
#    powershell -ExecutionPolicy Bypass -File desktop/build_exe.ps1            # 只构建到 dist\智影桌面端\
#    powershell -ExecutionPolicy Bypass -File desktop/build_exe.ps1 -Deploy    # 构建 + 自动部署到项目根（推荐）
#  -Deploy：构建后自动把 exe + _internal\ 拷到项目根（覆盖旧版），双击即用
#  产物：dist\智影桌面端\智影桌面端.exe
# ═══════════════════════════════════════════════════════════
param(
    [switch]$Deploy   # 构建后自动部署到项目根
)
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
if ($Deploy) {
    Write-Host "部署到项目根 …"
    $dst = Join-Path $Root "智影桌面端.exe"
    $dstInternal = Join-Path $Root "_internal"
    Remove-Item -Recurse -Force $dst, $dstInternal -ErrorAction SilentlyContinue
    Copy-Item -Force (Join-Path $Root "dist\智影桌面端\智影桌面端.exe") $dst
    Copy-Item -Recurse -Force (Join-Path $Root "dist\智影桌面端\_internal") $dstInternal
    Write-Host "✅ 已部署: $dst（双击即用）"
} else {
    Write-Host "分发 = dist\智影桌面端\ 文件夹 + 项目代码目录"
    Write-Host "（想一步到位加 -Deploy：自动把 exe + _internal 拷到项目根）"
}
