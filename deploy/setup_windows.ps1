# ============================================================================
#  Zhiying 新机一键部署安装器（交互式）
#
#  用途：全新 Windows（可能只有 git、连 python 都没有）→ 双击本脚本 →
#        命令行窗口交互（选 2B/8B 模型 + 输代理）→ 自动托管：
#          Python → .venv+依赖 → 内嵌 PostgreSQL(vendor/pg) → 模型(按档位)
#          → config.yaml 生成 → 建表 → 校验
#        完成后无缝交给根目录 install2.bat（前端构建 / 打 exe 的日常更新走它）。
#
#  用法： 双击本文件，或
#         powershell -ExecutionPolicy Bypass -File deploy\setup_windows.ps1
#  调试：  -SkipModels 跳过模型下载；-SkipPg 跳过内嵌 postgres 组装
# ============================================================================
param(
    [switch]$SkipModels,
    [switch]$SkipPg,
    [switch]$NoElevate
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
# UAC 提权会把进程工作目录重置到 C:\Windows\System32，必须切回项目根（否则 .venv 等相对路径全建错地方）
Set-Location $ProjectRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$DownloadRetries = 5

# ── 全局异常兜底：任何终止性错误落盘 + 屏显，避免闪退后无据可查 ──
$InstallLog = Join-Path $ProjectRoot "vendor\install.log"
trap {
    $msg = "[$(Get-Date -Format 'MM-dd HH:mm:ss')] TRAP L$($_.InvocationInfo.ScriptLineNumber): $($_.Exception.Message)"
    try {
        New-Item -ItemType Directory -Force -Path (Split-Path $InstallLog) | Out-Null
        Add-Content -Path $InstallLog -Value $msg -Encoding UTF8
    } catch {}
    Write-Host "`n[安装异常] $msg（已写入 $InstallLog，请把该文件发我）" -ForegroundColor Red
    Read-Host "`n按回车关闭此窗口（日志已写入 $InstallLog）"
    break
}

# ── 内嵌 postgres 下载源（本地 vendor/pg-zips 有则优先，避免依赖第三方在线） ──
$PgZipUrl      = "https://get.enterprisedb.com/postgresql/postgresql-17.5-1-windows-x64-binaries.zip"
$PgvectorUrl   = "https://github.com/andreiramani/pgvector_pgsql_windows/releases/download/0.8.6_17/vector.v0.8.6-pg17.zip"
$PgZipLocal    = Join-Path $ProjectRoot "vendor\pg-zips\postgresql-17.5-1-windows-x64-binaries.zip"
$PgvectorLocal = Join-Path $ProjectRoot "vendor\pg-zips\vector.v0.8.6-pg17.zip"

# ── FFmpeg 下载源（Gyan 完整版，含 h264_nvenc/h264_cuvid CUDA 编解码；主源 + ghfast 镜像兜底） ──
$FfmpegUrl = @(
    "https://github.com/GyanD/codexffmpeg/releases/download/9.0/ffmpeg-9.0-full_build.zip",
    "https://ghfast.top/https://github.com/GyanD/codexffmpeg/releases/download/9.0/ffmpeg-9.0-full_build.zip"
)
$FfmpegZip = Join-Path $ProjectRoot "vendor\ffmpeg-9.0-full_build.zip"

# 管理员权限（装 python / 写 Program Files 等需要）
if (-not $NoElevate) {
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) {
        Write-Host "需要管理员权限，正在请求 UAC 提权..." -ForegroundColor Yellow
        $extra = @()
        if ($SkipModels) { $extra += "-SkipModels" }
        if ($SkipPg)     { $extra += "-SkipPg" }
        Start-Process -FilePath "powershell.exe" -ArgumentList (@(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`""
        ) + $extra) -Verb RunAs
        exit
    }
}

# ───────────────────────────── 输出 helpers ─────────────────────────────
function Write-Step([string]$Index, [string]$Title) {
    Write-Host ""
    Write-Host "─── [$Index] $Title ───" -ForegroundColor Cyan
}
function Write-Ok([string]$Msg)   { Write-Host "  ✔ $Msg" -ForegroundColor Green }
function Write-Warn([string]$Msg) { Write-Host "  ⚠ $Msg" -ForegroundColor Yellow }
function Write-Info([string]$Msg) { Write-Host "  · $Msg" -ForegroundColor Gray }

# 执行命令；$UseProxy 决定是否注入代理环境。返回 exit code。
function Invoke-Native {
    param([string[]]$Cmd, [bool]$UseProxy = $false, [string]$Cwd = $ProjectRoot)
    $envOld = $null
    if ($UseProxy -and $script:Proxy) {
        $envOld = @($env:HTTP_PROXY, $env:HTTPS_PROXY)
        $env:HTTP_PROXY  = $script:Proxy
        $env:HTTPS_PROXY = $script:Proxy
    }
    Write-Info ("$ " + ($Cmd -join " "))
    # PS5.1: EAP=Stop 时原生命令写 stderr（pip 进度/torch import 警告）会抛 NativeCommandError 中止，
    # 需临时切 Continue（deploy_feedback §2 / §14(2)）
    $eap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        # 2>&1：合并 stderr，进度/警告不再被吞，也不会触发 NativeCommandError（stderr 变普通输出）
        & $Cmd[0] @($Cmd[1..($Cmd.Length-1)]) 2>&1 | ForEach-Object { Write-Host "      $_" -ForegroundColor DarkGray }
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $eap
    }
    if ($envOld -ne $null) { $env:HTTP_PROXY, $env:HTTPS_PROXY = $envOld }
    return $code
}

# 校验 zip 完整性（EOCD 签名 PK\x05\x06：完整 zip 结尾 22 字节内必有该签名）
function Test-CompleteZip([string]$Path) {
    if (-not (Test-Path $Path)) { return $false }
    try {
        $fs = [System.IO.File]::Open($Path, 'Open', 'Read', 'ReadWrite')
        try {
            if ($fs.Length -lt 22) { return $false }
            $fs.Seek(-22, [System.IO.SeekOrigin]::End) | Out-Null
            $buf = New-Object byte[] 22
            $null = $fs.Read($buf, 0, 22)
            return ($buf[0] -eq 0x50 -and $buf[1] -eq 0x4B -and $buf[2] -eq 0x05 -and $buf[3] -eq 0x06)
        } finally { $fs.Close() }
    } catch { return $false }
}

# 下载文件（走代理 + 断点续传 + 超时 + 实时进度）。返回 $true/$false。
function Invoke-Download {
    param([string]$Url, [string]$Dest, [bool]$UseProxy, [int]$TimeoutSec = 1800)
    $DestDir = Split-Path -Parent $Dest
    New-Item -ItemType Directory -Force -Path $DestDir | Out-Null
    $leaf = Split-Path -Leaf $Dest
    if (Test-Path $Dest) {
        $sz = (Get-Item $Dest).Length
        if ($sz -eq 0) { Remove-Item $Dest -Force; Write-Info "$leaf 为空文件，重下..." }
        else { Write-Ok "$leaf 已存在 ($([math]::Round($sz/1MB,1)) MB)，跳过"; return $true }
    }
    Write-Info "下载 $leaf ..."
    $proxyArgs = @()
    if ($UseProxy -and $script:Proxy) { $proxyArgs = @("-x", $script:Proxy) }
    for ($i = 0; $i -lt $DownloadRetries; $i++) {
        # 后台 curl：-C - 断点续传 + 连接/总超时兜底；前台轮询文件大小 = 实时进度 + 停滞检测
        $curlArgs = @("-L", "-s", "-S", "-C", "-", "-o", $Dest,
                      "--connect-timeout", "30", "--max-time", "$TimeoutSec",
                      "--retry", "2", "--retry-delay", "2") + $proxyArgs + @($Url)
        # 下载放子进程 job 执行（隔离：子进程崩了只算本次失败，不会拖垮安装器）+ 前台轮询进度
        $job = Start-Job -ScriptBlock {
            param($ca)
            & curl.exe @ca 2>$null
            "CURL_EXIT=$LASTEXITCODE"
        } -ArgumentList (,$curlArgs)
        $last = 0L; $stall = 0; $sw = [System.Diagnostics.Stopwatch]::StartNew()
        while ($job.State -eq "Running") {
            Start-Sleep -Milliseconds 1000
            $now = if (Test-Path $Dest) { (Get-Item $Dest).Length } else { 0L }
            if ($now -gt $last) { $last = $now; $stall = 0 } else { $stall++ }
            $el = $sw.Elapsed.TotalSeconds
            $spd = if ($el -gt 0) { $now / 1MB / $el } else { 0 }
            Write-Host "`r    $leaf 已下载 $([math]::Round($now/1MB,1)) MB（$([math]::Round($spd,2)) MB/s）    " -NoNewline
            if ($stall -ge 30) {
                Write-Warn "`r    停滞（$([math]::Round($last/1MB,1)) MB 不再增长），中止本次"
                Stop-Job $job -ErrorAction SilentlyContinue; break
            }
            if ($el -gt $TimeoutSec) {
                Write-Warn "`r    超时 ${TimeoutSec}s，中止本次（下次自动续传）"
                Stop-Job $job -ErrorAction SilentlyContinue; break
            }
        }
        $sw.Stop()
        Write-Host ""
        $jobOut = Receive-Job $job -ErrorAction SilentlyContinue
        Remove-Job $job -Force -ErrorAction SilentlyContinue
        $exitCode = -1
        if ($jobOut) {
            $m = [regex]::Match(($jobOut -join "`n"), "CURL_EXIT=(-?\d+)")
            if ($m.Success) { $exitCode = [int]$m.Groups[1].Value }
        }
        $dlOk = ($exitCode -eq 0 -and (Test-Path $Dest) -and (Get-Item $Dest).Length -gt 0)
        if ($dlOk) {
            Write-Ok "下载完成 ($([math]::Round((Get-Item $Dest).Length/1MB,1)) MB)"
            return $true
        }
        Write-Warn "本次下载失败（退出码 $exitCode），重试 $($i+1)/$DownloadRetries ..."
        Start-Sleep -Seconds 2
    }
    return $false
}

# ───────────────────────────── 交互：选模型 + 代理 ─────────────────────────────
Write-Host ""
Write-Host "═══ Zhiying 新机一键部署（命令行交互安装）═══" -ForegroundColor Cyan
Write-Host ""
Write-Host "请选择 embedding 模型档位（决定向量维度 + 装哪个模型）："
Write-Host "  [1] 8B  Qwen3-VL-Embedding-8B  → 4096 维（默认；需 ~16GB 显存）"
Write-Host "  [2] 2B  Qwen3-VL-Embedding-2B  → 2048 维（低显存机器平替）"
$choice = Read-Host "输入 1 或 2"
$script:EmbeddingProfile = if ($choice -eq "2") { "2b" } else { "8b" }
Write-Ok "已选档位: $script:EmbeddingProfile"

$proxyInput = Read-Host "输入代理地址（如 http://127.0.0.1:7897；能直连可留空）"
$script:Proxy = ($proxyInput.Trim() -replace '/$', '')
if ($script:Proxy) { Write-Ok "代理: $script:Proxy" } else { Write-Warn "未使用代理（国内源直连，GitHub 组件可能失败）" }
# 保存代理到 data/proxy.txt，供 install2.bat 复用（机器相关，data/ 已 gitignore）
$proxyFile = Join-Path $ProjectRoot "data\proxy.txt"
New-Item -ItemType Directory -Force -Path (Split-Path $proxyFile) | Out-Null
[System.IO.File]::WriteAllText($proxyFile, [string]$script:Proxy)
Write-Ok "代理已保存到 data/proxy.txt（install2.bat 自动读取）"

# ───────────────────────────── 1/6 Python ─────────────────────────────
Write-Step "1/6" "Python + FFmpeg + Node.js 环境"
# winget 装的新命令要刷新 PATH 才在本会话可用（读注册表机器/用户 PATH）
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

$py = Get-Command python -ErrorAction SilentlyContinue
if ($py) {
    $ver = (& python --version 2>&1) -replace "Python ", ""
    Write-Ok "检测到 Python $ver"
} else {
    Write-Info "未检测到 Python，用 winget 安装 Python 3.13 ..."
    # winget 走 WinINET（系统代理）；若失败给出明确指引（手动装或开系统代理）
    $null = & winget install --id Python.Python.3.13 --accept-source-agreements --accept-package-agreements --disable-interactivity 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Python 安装失败（请检查网络/系统代理后重试，或手动安装 Python 3.13 并勾选 Add to PATH）" }
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
    Write-Ok "Python 3.13 已安装"
}

# FFmpeg（视频处理必装：转码/抽帧/导出/流媒体都依赖它；需带 CUDA 编解码）
# 用 curl 下载 Gyan 完整版（走代理 + 断点续传 + 超时 + 实时进度），不依赖 winget/github 直连
Write-Info "检查 FFmpeg ..."
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    # 残留/不完整 zip 先清掉（若上一次被中断）
    if ((Test-Path $FfmpegZip) -and -not (Test-CompleteZip $FfmpegZip)) {
        Write-Warn "FFmpeg 压缩包不完整，删除后重下..."
        Remove-Item $FfmpegZip -Force
    }
    $ffmpegOk = $false
    foreach ($u in $FfmpegUrl) {
        if (Invoke-Download $u $FfmpegZip $true) { $ffmpegOk = $true; break }
        Write-Warn "该 FFmpeg 源下载失败，换下一个源..."
    }
    if (-not $ffmpegOk) { throw "FFmpeg 下载失败（所有源均失败）" }
    # 解压 → 找 bin 目录 → 加 PATH（会话 + 用户级持久化，供 ffmpeg/ffprobe/ffplay 使用）
    $ffmpegRoot = Join-Path $ProjectRoot "vendor\ffmpeg"
    Remove-Item $ffmpegRoot -Recurse -Force -ErrorAction SilentlyContinue
    Write-Info "解压 FFmpeg ..."
    Expand-Archive -Path $FfmpegZip -DestinationPath $ffmpegRoot -Force
    $ffmpegExe = Get-ChildItem $ffmpegRoot -Recurse -Filter "ffmpeg.exe" -ErrorAction SilentlyContinue |
        Where-Object { $_.DirectoryName -like "*bin*" } | Select-Object -First 1
    if (-not $ffmpegExe) { throw "FFmpeg 解压后未找到 ffmpeg.exe" }
    $ffmpegBin = $ffmpegExe.DirectoryName
    Write-Ok "FFmpeg 就绪: $ffmpegBin"
    $env:Path = "$ffmpegBin;" + $env:Path
    [Environment]::SetEnvironmentVariable("Path", "$ffmpegBin;" + [Environment]::GetEnvironmentVariable("Path", "User"), "User")
} else {
    Write-Ok "已检测到 FFmpeg"
}
$ffEnc = (& ffmpeg -hide_banner -encoders 2>&1 | Out-String)
$ffDec = (& ffmpeg -hide_banner -decoders 2>&1 | Out-String)
if ($ffEnc -notmatch "h264_nvenc" -or $ffDec -notmatch "h264_cuvid") {
    Write-Warn "FFmpeg 缺少 CUDA 编解码（h264_nvenc/h264_cuvid）——会静默回退 CPU，性能骤降；建议用 Gyan 完整版重装后重跑"
} else {
    Write-Ok "FFmpeg CUDA 能力正常（h264_nvenc + h264_cuvid）"
}

# Node.js（前端构建必需：Vite/React 编译需要 Node 运行时 + npm 包管理器）
Write-Info "检查 Node.js ..."
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Info "未检测到 Node，用 winget 安装 Node.js（含 npm）..."
    $null = & winget install --id OpenJS.NodeJS --accept-source-agreements --accept-package-agreements --disable-interactivity 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Node.js 安装失败（请检查代理/网络后重试，或手动安装 Node.js LTS）" }
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
}
$nodeVer = (& node --version 2>&1)
Write-Ok "Node.js $nodeVer"
# npm 国内镜像（中国网络免代理拉依赖；写入用户配置持久生效）
if (Get-Command npm -ErrorAction SilentlyContinue) {
    $null = & npm config set registry https://registry.npmmirror.com 2>&1
    Write-Ok "npm 镜像已配置：registry.npmmirror.com（install2 拉依赖免代理）"
}

# ───────────────────────────── 2/6 .venv + 依赖 ─────────────────────────────
Write-Step "2/6" "虚拟环境 + 依赖"
if (-not (Test-Path $VenvPython)) {
    Write-Info "创建 .venv ..."
    $rc = Invoke-Native @("python", "-m", "venv", (Join-Path $ProjectRoot ".venv"))
    if ($rc -ne 0) { throw ".venv 创建失败" }
} else {
    Write-Ok ".venv 已存在"
}
Write-Info "升级 pip ..."
$pipArgs = @("-m", "pip", "install", "--upgrade", "pip", "--progress-bar", "raw")
if ($script:Proxy) { $pipArgs += @("--proxy", $script:Proxy) }
$rc = Invoke-Native (@($VenvPython) + $pipArgs)

# CUDA 版 PyTorch：pip 默认装 CPU 版，必须用 PyTorch 官方源；按驱动 CUDA 版本选 cu124/cu126/cu130
# nvidia-smi 新版驱动头是 "CUDA UMD Version"（旧版是 "CUDA Version"），两种都匹配；null 兜底
$cudaLine = & nvidia-smi 2>$null | Select-String "CUDA (UMD )?Version:\s*([0-9.]+)" | Select-Object -First 1
$driverCuda = if ($cudaLine) { $cudaLine.Matches[0].Groups[2].Value } else { "" }
$torchIdx = "https://download.pytorch.org/whl/cu124"
if ($driverCuda -and [version]$driverCuda -ge [version]"13.0") { $torchIdx = "https://download.pytorch.org/whl/cu130" }
elseif ($driverCuda -and [version]$driverCuda -ge [version]"12.6") { $torchIdx = "https://download.pytorch.org/whl/cu126" }
Write-Info "安装 CUDA 版 PyTorch + torchvision（$torchIdx，驱动 CUDA $driverCuda）..."
# torchvision 必须同源（cu130）装，否则 requirements 阶段从 PyPI 拉 CPU 版 → torchvision::nms CUDA 报错（§13）
$rc = Invoke-Native @($VenvPython, "-m", "pip", "install", "torch", "torchvision", "--index-url", $torchIdx, "--progress-bar", "raw") $true
if ($rc -ne 0) { throw "CUDA PyTorch 安装失败" }

# onnxruntime 处理（§14）：先清真实 CPU dist-info + 建虚拟桩，让 requirements 只装 onnxruntime-gpu
Write-Info "预置 onnxruntime 虚拟桩（防 CPU/GPU 双装冲突）..."
$onnxStubPy = @"
import sysconfig, pathlib, shutil
sp = pathlib.Path(sysconfig.get_paths()["purelib"])
# 移除真实 CPU 版 onnxruntime 的 dist-info（直接删目录，避免 pip uninstall 删共享的 onnxruntime/ 文件）
for d in sp.glob("onnxruntime-*.dist-info"):
    if d.name.startswith("onnxruntime_gpu"):
        continue
    print("[onnx] remove", d.name)
    shutil.rmtree(d, ignore_errors=True)
# 建虚拟桩：满足 hyperlpr3/insightface 的 Requires-Dist: onnxruntime，防止再拉 CPU 版
stub = sp / "onnxruntime-99.0.0.dist-info"
stub.mkdir(parents=True, exist_ok=True)
(stub / "METADATA").write_text("Metadata-Version: 2.1\nName: onnxruntime\nVersion: 99.0.0\n", encoding="utf-8")
print("[onnx] stub ready:", stub.name)
"@
$onnxTmp = Join-Path $ProjectRoot "vendor\.fix-onnx.py"
Set-Content -Path $onnxTmp -Value $onnxStubPy -Encoding UTF8
$rc = Invoke-Native @($VenvPython, $onnxTmp)
Remove-Item $onnxTmp -Force -ErrorAction SilentlyContinue
if ($rc -ne 0) { Write-Warn "onnxruntime 桩创建失败（继续安装，稍后校验）" }

Write-Info "安装其余依赖（torch/torchvision 已满足会自动跳过；首次需数分钟，耐心等待）..."
$pipArgs2 = @("-m", "pip", "install", "-r", (Join-Path $ProjectRoot "requirements.txt"), "--progress-bar", "raw")
if ($script:Proxy) { $pipArgs2 += @("--proxy", $script:Proxy) }
$rc = Invoke-Native (@($VenvPython) + $pipArgs2)
if ($rc -ne 0) { throw "依赖安装失败" }

# onnxruntime-gpu 校验：get_device() 必须为 GPU；否则强制重装 gpu 版
Write-Info "校验 onnxruntime（应为 GPU 设备）..."
$onnxChkPy = @"
import sys, subprocess, importlib
import onnxruntime as o
if o.get_device() != "GPU":
    print("[onnx] device is CPU - force reinstalling onnxruntime-gpu", file=sys.stderr)
    r = subprocess.run([sys.executable, "-m", "pip", "install", "onnxruntime-gpu", "--no-deps", "--force-reinstall", "--progress-bar", "raw"], capture_output=True, text=True)
    if r.returncode != 0:
        print("[onnx] gpu reinstall FAILED:", r.stderr[-400:], file=sys.stderr)
        raise SystemExit(1)
    importlib.reload(o)
print("onnxruntime:", o.__version__, "| device:", o.get_device())
"@
$onnxChkTmp = Join-Path $ProjectRoot "vendor\.chk-onnx.py"
Set-Content -Path $onnxChkTmp -Value $onnxChkPy -Encoding UTF8
$rc = Invoke-Native @($VenvPython, $onnxChkTmp)
Remove-Item $onnxChkTmp -Force -ErrorAction SilentlyContinue
if ($rc -ne 0) { Write-Warn "onnxruntime-gpu 校验/修复失败（人脸/车牌可能走 CPU）" }

# 验证 PyTorch GPU 可用
$rc = Invoke-Native @($VenvPython, "-c",
    "import torch; assert torch.cuda.is_available(), 'cuda-unavailable'; print('torch', torch.__version__, '| cuda', torch.version.cuda, '|', torch.cuda.get_device_name(0))")
if ($rc -ne 0) { throw "PyTorch 检测不到 GPU（检查驱动 / 是否残留 CPU 版 torch）" }
Write-Ok "PyTorch GPU 就绪"

# ───────────────────────────── 3/6 内嵌 PostgreSQL ─────────────────────────────
Write-Step "3/6" "内嵌 PostgreSQL（vendor/pg）"
if ($SkipPg) { Write-Info "已跳过（-SkipPg）" }
else {
    $pgDir = Join-Path $ProjectRoot "vendor\pg"
    if (Test-Path (Join-Path $pgDir "bin\pg_ctl.exe")) {
        Write-Ok "vendor/pg 已存在"
    } else {
        # 本地 vendor/pg-zips 优先，否则在线下载
        $pgZip = if ((Test-Path $PgZipLocal) -and (Test-CompleteZip $PgZipLocal)) { $PgZipLocal } else { $null }
        $vecZip = if ((Test-Path $PgvectorLocal) -and (Test-CompleteZip $PgvectorLocal)) { $PgvectorLocal } else { $null }
        if ($pgZip) { Write-Ok "本地已有 postgres zip" } else {
            $pgDest = Join-Path $ProjectRoot "vendor\pg-zips\postgresql.zip"
            if ((Test-Path $pgDest) -and -not (Test-CompleteZip $pgDest)) { Remove-Item $pgDest -Force; Write-Warn "postgres zip 不完整，删除重下" }
            if (-not (Invoke-Download $PgZipUrl $pgDest $true)) { throw "postgres zip 下载失败" }
            $pgZip = $pgDest
        }
        if ($vecZip) { Write-Ok "本地已有 pgvector zip" } else {
            $vecDest = Join-Path $ProjectRoot "vendor\pg-zips\pgvector.zip"
            if ((Test-Path $vecDest) -and -not (Test-CompleteZip $vecDest)) { Remove-Item $vecDest -Force; Write-Warn "pgvector zip 不完整，删除重下" }
            if (-not (Invoke-Download $PgvectorUrl $vecDest $true)) { throw "pgvector zip 下载失败" }
            $vecZip = $vecDest
        }
        # 解压 postgres → vendor/pg（zip 内层是 pgsql/，取其内容）
        Write-Info "解压 PostgreSQL ..."
        $tmpPg = Join-Path $ProjectRoot "vendor\.tmp-pg"
        Remove-Item $tmpPg -Recurse -Force -ErrorAction SilentlyContinue
        Expand-Archive -Path $pgZip -DestinationPath $tmpPg -Force
        $inner = Get-ChildItem $tmpPg -Directory | Select-Object -First 1
        if ($inner) { Move-Item $inner.FullName $pgDir }
        else { Move-Item $tmpPg $pgDir }
        Remove-Item $tmpPg -Recurse -Force -ErrorAction SilentlyContinue
        # 解压 pgvector → vendor/pg（zip 内是 lib/ 与 share/extension/）
        Write-Info "安装 pgvector 扩展 ..."
        Expand-Archive -Path $vecZip -DestinationPath (Join-Path $ProjectRoot "vendor\.tmp-vec") -Force
        Copy-Item -Path (Join-Path $ProjectRoot "vendor\.tmp-vec\*") -Destination $pgDir -Recurse -Force
        Remove-Item (Join-Path $ProjectRoot "vendor\.tmp-vec") -Recurse -Force -ErrorAction SilentlyContinue
        if (Test-Path (Join-Path $pgDir "bin\pg_ctl.exe")) { Write-Ok "vendor/pg 就绪（含 pgvector）" }
        else { throw "vendor/pg 组装失败：bin\pg_ctl.exe 缺失" }
    }
}

# ───────────────────────────── 4/6 模型（按档位） ─────────────────────────────
Write-Step "4/6" "模型下载（$script:EmbeddingProfile 档位）"
if ($SkipModels) { Write-Info "已跳过（-SkipModels）" }
else {
    $dlPy = Join-Path $PSScriptRoot "download_models.py"
    # 国内源组件（embedding 按档位 + plate + segmenter）：必须直连（modelscope 是国内 CDN，走代理反而更慢更易断）
    $rc = Invoke-Native @($VenvPython, $dlPy, "--embedding-profile", $script:EmbeddingProfile,
        "--component", "embedding", "--component", "plate", "--component", "segmenter",
        "--model-root", (Join-Path $ProjectRoot "models"), "--retries", "$DownloadRetries") $false
    if ($rc -ne 0) { throw "国内源模型下载失败（modelscope 直连；已内置断点续传，可重跑续传）" }
    # GitHub 源组件（yolo/reid/face，需代理）
    $rc = Invoke-Native @($VenvPython, $dlPy,
        "--component", "yolo", "--component", "reid", "--component", "face",
        "--model-root", (Join-Path $ProjectRoot "models"), "--retries", "$DownloadRetries") $true
    if ($rc -ne 0) { throw "GitHub 源模型下载失败（检查代理）" }
    Write-Ok "全部模型就绪"
}

# ───────────────────────────── 5/6 config.yaml 生成 ─────────────────────────────
Write-Step "5/6" "生成 config.yaml"
$cfgPath = Join-Path $ProjectRoot "config\config.yaml"
$cfgGen = @"
import yaml, pathlib
root = pathlib.Path(r"$ProjectRoot")
cfg_path = root / "config" / "config.yaml"
example = root / "config" / "config.yaml.example"
if cfg_path.exists():
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
else:
    cfg = yaml.safe_load(example.read_text(encoding="utf-8")) or {}
cfg["embedding_profile"] = "$script:EmbeddingProfile"
cfg.setdefault("database", {})["uri"] = "postgresql+asyncpg://zhiying:zhiying@localhost:5432/zhiying"
cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
print("config.yaml: embedding_profile =", cfg["embedding_profile"])
"@
$cfgTmp = Join-Path $ProjectRoot "vendor\.gen-config.py"
Set-Content -Path $cfgTmp -Value $cfgGen -Encoding UTF8
$rc = Invoke-Native @($VenvPython, $cfgTmp)
Remove-Item $cfgTmp -Force -ErrorAction SilentlyContinue
if ($rc -ne 0) { throw "config.yaml 生成失败" }
Write-Ok "config.yaml 已生成（embedding_profile=$script:EmbeddingProfile）"

# ───────────────────────────── 6/6 起库 + 建表 ─────────────────────────────
Write-Step "6/6" "启动内嵌 PostgreSQL + 建表"
$initScript = @"
import sys
from pathlib import Path
root = Path(r"$ProjectRoot")
sys.path.insert(0, str(root))
import importlib.util
spec = importlib.util.spec_from_file_location("desktop_db", root / "desktop" / "db.py")
db = importlib.util.module_from_spec(spec); spec.loader.exec_module(db)
class Log:
    def write(self, s):
        if s.strip(): print("   [pg]", s)
log = Log()
if not db.start_db(root, log, timeout=180):
    print("FAIL start_db"); sys.exit(1)
if not db.wait_db_healthy(root, log, timeout=120):
    print("FAIL wait_db_healthy"); sys.exit(1)
print("DB ready")
"@
$initTmp = Join-Path $ProjectRoot "vendor\.start-pg.py"
Set-Content -Path $initTmp -Value $initScript -Encoding UTF8
$rc = Invoke-Native @($VenvPython, $initTmp)
Remove-Item $initTmp -Force -ErrorAction SilentlyContinue
if ($rc -ne 0) { throw "内嵌 PostgreSQL 启动失败" }

Write-Info "建表（init_db）..."
$rc = Invoke-Native @($VenvPython, "-c",
    "import asyncio; from core.db import init_db; asyncio.run(init_db()); print('tables ok')")
if ($rc -ne 0) { throw "init_db 建表失败" }
Write-Ok "数据库已就绪、表已创建"

# ───────────────────────────── 完成 ─────────────────────────────
Write-Host ""
Write-Host "══════════ 安装完成 ══════════" -ForegroundColor Green
Write-Host "  档位: $script:EmbeddingProfile  |  代理: $($script:Proxy)"
Write-Host "  内嵌 PostgreSQL: vendor/pg（端口 5432，数据在 data/pgdata）"
Write-Host "  模型: models\ 就绪  |  config.yaml: 已生成"
Write-Host ""
Write-Host "  后续日常更新/启动：双击根目录 install2.bat（git pull + 依赖 + 前端 + 打 exe）"
Write-Host "  或直接启动桌面端：python desktop\app.py"
Write-Host "══════════════════════════════" -ForegroundColor Green
Read-Host "`n安装流程结束（按回车关闭此窗口）"
