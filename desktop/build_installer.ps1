# ═══════════════════════════════════════════════════════════
#  智影 · Windows 安装包构建（Inno Setup）
#  用法（项目根，Windows）：
#    powershell -ExecutionPolicy Bypass -File desktop/build_installer.ps1
#    可选：
#      -EmbeddingProfile 2b   安装器写死档位（默认 8b；2B 机器用 2b）
#      -Version 0.90         安装包版本（默认自动读 core/version.py；覆盖 zhiying.iss #define）
#  流程：build_exe.ps1（产出 dist\智影桌面端\，不经根目录中转）→ ISCC 编译 zhiying.iss
#  产物：build\视频快速智能检索平台 Ver <版本>.exe
#  前置：本机已装 Inno Setup 6（ISCC.exe），且已跑过 deploy\setup_windows.ps1 建好 .venv
# ═══════════════════════════════════════════════════════════
param(
    [string]$EmbeddingProfile = "8b",
    # 版本默认自动取 core/version.py（与项目 semver/tag 统一，bump 后直接构建即同步）
    [string]$Version = ""
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not $Version) {
    $verLine = Select-String -Path (Join-Path $Root "core\version.py") -Pattern '__version__\s*=\s*"([^"]+)"' |
        Select-Object -First 1
    if (-not $verLine) { throw "core/version.py 里找不到 __version__" }
    $Version = $verLine.Matches[0].Groups[1].Value
}

# ── 定位 ISCC（Inno Setup 6 编译器）───────────────────────
$ISCC = ""
foreach ($cand in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
                    "$env:ProgramFiles\Inno Setup 6\ISCC.exe")) {
    if (Test-Path $cand) { $ISCC = $cand; break }
}
if (-not $ISCC) {
    throw "未找到 ISCC.exe —— 请先安装 Inno Setup 6（winget install JRSoftware.InnoSetup）"
}

Write-Host "═ 1/2 构建桌面壳 exe（build_exe.ps1）═" -ForegroundColor Cyan
& "$Root\desktop\build_exe.ps1"
# 不判 $LASTEXITCODE：build_exe.ps1 内部 pg_ctl stop 等原生命令会残留非零退出码
# （PG 未运行即 exit 1），但脚本用 ErrorActionPreference=Stop，真失败会抛异常。
# 以产物存在性为判据。
if (-not (Test-Path "$Root\dist\智影桌面端\智影桌面端.exe") -or
    -not (Test-Path "$Root\dist\智影桌面端\_internal\python313.dll")) {
    throw "build_exe.ps1 未产出可用产物（dist\智影桌面端\智影桌面端.exe / _internal\python313.dll）"
}

Write-Host "═ 2/2 编译安装包（zhiying.iss · 档位=$EmbeddingProfile · 版本=$Version）═" -ForegroundColor Cyan
& $ISCC zhiying.iss "/DDefaultEmbeddingProfile=$EmbeddingProfile" "/DMyAppVersion=$Version" "/DVersionInfoVersion=$Version"
if ($LASTEXITCODE -ne 0) { throw "ISCC 编译失败（exit=$LASTEXITCODE），看上方输出" }

$setup = Get-ChildItem "build\*.exe" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $setup) { throw "未找到安装包产物（build\*.exe）" }
Write-Host "`n✅ 安装包: $($setup.FullName)（$([math]::Round($setup.Length/1MB,1)) MB）" -ForegroundColor Green
Write-Host "  分发 = 该 .exe 单个文件；模型 25GB 由首次启动引导下载。"