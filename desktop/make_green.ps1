# ═══════════════════════════════════════════════════════════
#  desktop/make_green.ps1 — 装配"打包材料"交付 zip（安装器 [Files] 完整输入集）
#
#  打包材料 = 安装器（zhiying.iss [Files]）的完整输入集（客户机需另装 .venv/模型/PG 才可运行）：
#    智影桌面端.exe + _internal/(含 backend_pyc) + frontend-desktop/dist +
#    config/(无 config.yaml，装机生成) + deploy 引导件 + iss-lang + desktop/db.py +
#    requirements.txt
#
#  用途：安装包编译/签名由打包方执行——我们交付打包材料 + iss 脚本，对方
#        直接在材料目录（zhiying.iss 已就位）→ ISCC 编译 → 签名 → 成品安装包。
#        -Zip 可选出 zip（外部交付场景）。
#
#  前置：已跑过 desktop/build_exe.ps1（dist\智影桌面端\ 有产物；无需 -Deploy）
#  用法：powershell -ExecutionPolicy Bypass -File desktop/make_green.ps1
#  产物：build\green\（材料目录，zhiying.iss 就位，可直接 ISCC 编译）；-Zip 时另出 build\智影打包材料 v<版本>.zip
# ═══════════════════════════════════════════════════════════
param(
    [string]$OutputDir = "",  # -Zip 时的输出目录，默认 <root>\build
    [switch]$Zip              # 额外压打包材料 zip（外部交付场景；默认只出 build\green 材料目录）
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

# ── 版本（自动取 core/version.py）─────────────────────────
$verLine = Select-String -Path (Join-Path $Root "core\version.py") -Pattern '__version__\s*=\s*"([^"]+)"' |
    Select-Object -First 1
if (-not $verLine) { throw "core/version.py 里找不到 __version__" }
$Version = $verLine.Matches[0].Groups[1].Value

# ── 前置检查：build_exe 产物必须在（dist，不经根目录中转）──
$DistDir = Join-Path $Root "dist\智影桌面端"
if (-not (Test-Path (Join-Path $DistDir "智影桌面端.exe")) -or
    -not (Test-Path (Join-Path $DistDir "_internal\python313.dll"))) {
    throw "缺少 build_exe 产物（dist\智影桌面端\）——先跑：powershell -ExecutionPolicy Bypass -File desktop/build_exe.ps1"
}

# ── 装配暂存目录（对齐 zhiying.iss [Files] 的 Source 集合）──
$Stage = Join-Path $Root "build\green"
if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path $Stage | Out-Null

# exe + _internal 放 dist\智影桌面端\ 层级（与 iss Source 路径一致，打包方解压后直接编译）
New-Item -ItemType Directory -Force -Path (Join-Path $Stage "dist\智影桌面端") | Out-Null
Copy-Item (Join-Path $DistDir "智影桌面端.exe") (Join-Path $Stage "dist\智影桌面端\")
Copy-Item (Join-Path $DistDir "_internal") (Join-Path $Stage "dist\智影桌面端\_internal") -Recurse
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

# 清理 __pycache__（若有）
Get-ChildItem $Stage -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

# iss 就位：编译基准 = iss 所在目录，放材料根目录后 Source 相对路径直接命中
Copy-Item "$Root\zhiying.iss" $Stage

# ── 可选：压 zip ──────────────────────────────────────────
if ($Zip) {
    if (-not $OutputDir) { $OutputDir = Join-Path $Root "build" }
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    $ZipPath = Join-Path $OutputDir "智影打包材料 v$Version.zip"
    if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
    Compress-Archive -Path "$Stage\*" -DestinationPath $ZipPath -CompressionLevel Optimal
    $mb = [math]::Round((Get-Item $ZipPath).Length / 1MB, 1)
    Write-Host "`n✅ 打包材料 zip: $ZipPath（$mb MB）" -ForegroundColor Green
}

Write-Host "`n✅ 打包材料目录: $Stage（含 zhiying.iss，ISCC/Inno Setup 直接编译即可）" -ForegroundColor Green
Write-Host "  编译产物: build\视频快速智能检索平台 Ver <版本>.exe → 打包方签名"
