# ═══════════════════════════════════════════════════════════
#  desktop/make_green.ps1 — 装配"绿色版"交付 zip
#
#  绿色版 = 安装器（zhiying.iss [Files]）的完整输入集 = 解压即可运行的程序目录：
#    智影桌面端.exe + _internal/(含 backend_pyc) + frontend-desktop/dist +
#    config/(无 config.yaml，装机生成) + deploy 引导件 + iss-lang + desktop/db.py +
#    requirements.txt + manifest.json
#
#  用途：安装包编译/签名由打包方执行——我们交付绿色版 + iss 脚本，对方
#        解压 → 放入 zhiying.iss → ISCC 编译 → 签名 → 成品安装包。
#
#  前置：已跑过 desktop/build_exe.ps1 -Deploy（根目录有 智影桌面端.exe + _internal）
#  用法：powershell -ExecutionPolicy Bypass -File desktop/make_green.ps1
#  产物：Bin\智影绿色版 v<版本>.zip（版本自动取 core/version.py）
# ═══════════════════════════════════════════════════════════
param(
    [string]$OutputDir = ""   # 默认 <root>\Bin
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

# ── 版本（自动取 core/version.py）─────────────────────────
$verLine = Select-String -Path (Join-Path $Root "core\version.py") -Pattern '__version__\s*=\s*"([^"]+)"' |
    Select-Object -First 1
if (-not $verLine) { throw "core/version.py 里找不到 __version__" }
$Version = $verLine.Matches[0].Groups[1].Value

# ── 前置检查：build_exe 产物必须在 ────────────────────────
if (-not (Test-Path "$Root\智影桌面端.exe") -or -not (Test-Path "$Root\_internal\python313.dll")) {
    throw "缺少 build_exe 产物——先跑：powershell -ExecutionPolicy Bypass -File desktop/build_exe.ps1 -Deploy"
}

# ── 装配暂存目录（对齐 zhiying.iss [Files] 的 Source 集合）──
$Stage = Join-Path $Root "build\green"
if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path $Stage | Out-Null

Copy-Item "$Root\智影桌面端.exe" $Stage
Copy-Item "$Root\_internal" "$Stage\_internal" -Recurse
New-Item -ItemType Directory -Force -Path "$Stage\frontend-desktop" | Out-Null
Copy-Item "$Root\frontend-desktop\dist" "$Stage\frontend-desktop\dist" -Recurse
New-Item -ItemType Directory -Force -Path "$Stage\config" | Out-Null
Copy-Item "$Root\config\*" "$Stage\config\" -Recurse -Exclude "config.yaml"
New-Item -ItemType Directory -Force -Path "$Stage\deploy" | Out-Null
foreach ($f in @("download_models.py", "setup_windows.ps1", "stop_runtime.ps1")) {
    Copy-Item "$Root\deploy\$f" "$Stage\deploy\"
}
Copy-Item "$Root\deploy\iss-lang" "$Stage\deploy\iss-lang" -Recurse   # iss 编译期引用，不进安装 [Files]
New-Item -ItemType Directory -Force -Path "$Stage\desktop" | Out-Null
Copy-Item "$Root\desktop\db.py" "$Stage\desktop\"
Copy-Item "$Root\requirements.txt" $Stage
Copy-Item "$Root\manifest.json" $Stage

# 清理 __pycache__（若有）
Get-ChildItem $Stage -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

# ── 压 zip ────────────────────────────────────────────────
if (-not $OutputDir) { $OutputDir = Join-Path $Root "Bin" }
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$ZipPath = Join-Path $OutputDir "智影绿色版 v$Version.zip"
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Compress-Archive -Path "$Stage\*" -DestinationPath $ZipPath -CompressionLevel Optimal

$mb = [math]::Round((Get-Item $ZipPath).Length / 1MB, 1)
Write-Host "`n✅ 绿色版: $ZipPath（$mb MB）" -ForegroundColor Green
Write-Host "  打包方：解压 → 放入 zhiying.iss → ISCC 编译 → 签名（见交付目录打包说明.md）"
