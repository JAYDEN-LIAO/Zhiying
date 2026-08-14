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

# PyInstaller 版本钉：默认装最新。若遇 python313.dll 加载失败且排除杀软后仍复现，
# 改这里回退到之前能成功构建的版本（例：'pyinstaller==6.11.1'），避免每次构建静默升级导致 _internal 布局漂移。
$PyInstallerPin = ""
if ($PyInstallerPin) {
    & $Py -m pip install --quiet $PyInstallerPin
} else {
    & $Py -m pip install --quiet pyinstaller
}

Write-Host "构建 智影桌面端.exe …"
& $Py -m PyInstaller desktop\build_exe.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败 (exit=$LASTEXITCODE)，看上方输出" }

# ── 构建产物自检：dist 里必须存在 exe + python313.dll（否则说明被杀软隔离/构建异常，别再往下拷）──
$distExe = Join-Path $Root "dist\智影桌面端\智影桌面端.exe"
$distDll = Join-Path $Root "dist\智影桌面端\_internal\python313.dll"
if (-not (Test-Path $distExe)) { throw "构建产物缺失: $distExe（构建异常，看上方 PyInstaller 输出）" }
if (-not (Test-Path $distDll)) {
    throw "构建产物缺少 _internal\python313.dll —— 几乎可以肯定是杀毒软件实时防护把它隔离了。请到「Windows 安全中心 → 病毒和威胁防护 → 保护历史记录」还原 python313.dll，并把 '$Root' 加入「排除项」，然后重跑本脚本。"
}

Write-Host "✅ 构建完成: $distExe"
if ($Deploy) {
    Write-Host "部署到项目根 …"
    $dst = Join-Path $Root "智影桌面端.exe"
    $dstInternal = Join-Path $Root "_internal"
    Remove-Item -Recurse -Force $dst, $dstInternal -ErrorAction SilentlyContinue
    Copy-Item -Force $distExe $dst
    Copy-Item -Recurse -Force (Join-Path $Root "dist\智影桌面端\_internal") $dstInternal

    # ── 部署后二次自检：拷完立刻验证 python313.dll 落地（杀软常在拷贝瞬间再删一次）──
    if (-not (Test-Path (Join-Path $dstInternal "python313.dll"))) {
        throw "部署后 _internal\python313.dll 仍缺失 —— 被杀毒软件实时防护删除了。请先把 '$Root' 加入「排除项」（Windows 安全中心 → 病毒和威胁防护 → 排除项 → 添加文件夹），再重新 -Deploy。"
    }
    Write-Host "✅ 已部署: $dst（双击即用，自检通过）"
} else {
    Write-Host "分发 = dist\智影桌面端\ 文件夹 + 项目代码目录"
    Write-Host "（想一步到位加 -Deploy：自动把 exe + _internal 拷到项目根）"
}
