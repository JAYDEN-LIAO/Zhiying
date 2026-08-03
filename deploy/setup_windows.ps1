<#
Cerno Windows 部署向导
═══════════════════════════════════════════════════════════════
目标：本机 Python venv + Docker PostgreSQL/pgvector + 本机模型。
不打包 Electron，不做 CUDA 容器。

两种安装模式：
  full       全功能（除本地视觉摘要大模型）：embedding + yolo + face + plate
             + segmenter + 摘要 API (vlm_llm)
  searchless 同 full，但不装 embedding（不做向量语义检索）

必装环境：NVIDIA GPU + CUDA 驱动（nvidia-smi）、FFmpeg。
音频转录（faster-whisper）为参数面板置灰的 opt-in 功能，部署默认不装。

特点：
  - 交互式（可跳过/重试/断点续传，失败可重跑继续）
  - 幂等：已完成的步骤自动跳过
  - 智能探测：Python 版本自动选用 3.13→3.12→3.11；torch 按驱动 CUDA 版本选源；
    已可用的 torch / onnxruntime-gpu 直接复用（不重复下载）
  - 绝不覆盖 .env；API key 只写 data/settings.json（或之后在设置页填）
  - 模型完整性校验，缺什么补什么

用法：
  Set-ExecutionPolicy -Scope Process Bypass
  .\deploy\setup_windows.ps1
  .\deploy\setup_windows.ps1 -Mode full -NonInteractive
  .\deploy\setup_windows.ps1 -Mode searchless -SkipModels
  .\deploy\setup_windows.ps1 -PythonVersion 3.13        # 手动指定（默认自动探测）
#>

param(
    [string]$Mode = "",
    [switch]$NonInteractive,
    [switch]$SkipDependencies,
    [switch]$SkipModels,
    [switch]$NoDb,
    [switch]$SkipConfig,
    [int]$DownloadRetries = 3,
    [string]$PythonVersion = "",   # 空 = 自动探测（3.13→3.12→3.11）
    [switch]$StartAfter
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ConfigFile = Join-Path $ProjectRoot "config\config.windows.yaml"

function Write-Step([string]$Index, [string]$Title) {
    Write-Host ""
    Write-Host "────────────────────────────────────────────" -ForegroundColor DarkGray
    Write-Host "[$Index] $Title" -ForegroundColor Cyan
    Write-Host "────────────────────────────────────────────" -ForegroundColor DarkGray
}

function Write-Info([string]$Message) { Write-Host "  $Message" -ForegroundColor Gray }
function Write-Ok([string]$Message)   { Write-Host "  [ok] $Message" -ForegroundColor Green }
function Write-Warn([string]$Message) { Write-Host "  [warn] $Message" -ForegroundColor Yellow }
function Write-Fail([string]$Message) { Write-Host "  [error] $Message" -ForegroundColor Red }

function Ask-YesNo([string]$Prompt, [bool]$Default = $true) {
    if ($NonInteractive) { return $Default }
    $suffix = if ($Default) { "[Y/n]" } else { "[y/N]" }
    while ($true) {
        $answer = Read-Host "$Prompt $suffix"
        if ([string]::IsNullOrWhiteSpace($answer)) { return $Default }
        if ($answer -match "^(y|yes)$") { return $true }
        if ($answer -match "^(n|no)$") { return $false }
        Write-Host "  请输入 y 或 n。" -ForegroundColor Yellow
    }
}

function Get-SelectedMode {
    if ($Mode -eq "full" -or $Mode -eq "searchless") { return $Mode }
    if ($Mode -ne "") { throw "无效的 -Mode 参数: $Mode（可选 full / searchless）" }
    if ($NonInteractive) { return "full" }
    Write-Host ""
    Write-Host "请选择安装模式：" -ForegroundColor White
    Write-Host "  1. 全功能（推荐）—— 语义检索 + 检测 + 人脸 + 车牌 + 摘要API"
    Write-Host "     仅不含本地视觉摘要大模型（用 DashScope + DeepSeek API 代替）"
    Write-Host "  2. 无向量检索   —— 同上，但不装 embedding 模型（不做语义/图搜）"
    while ($true) {
        $choice = Read-Host "选择 [1]"
        if ([string]::IsNullOrWhiteSpace($choice) -or $choice -eq "1") { return "full" }
        if ($choice -eq "2") { return "searchless" }
        Write-Host "  请输入 1 或 2。" -ForegroundColor Yellow
    }
}

function Require-Command([string]$Name, [string]$Hint) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name 未找到。$Hint"
    }
}

function Invoke-Checked([string]$FilePath, [string[]]$ArgumentList, [string]$FailureMessage) {
    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) { throw $FailureMessage }
}

function Get-BestPythonVersion {
    <# 探测可用 Python：优先 3.13（与开发机一致），其次 3.12/3.11。 #>
    if ($PythonVersion -ne "") {
        & py "-$PythonVersion" --version 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "指定的 Python $PythonVersion 不可用（py -$PythonVersion --version 失败）。" }
        return $PythonVersion
    }
    $installed = @()
    (& py -0p 2>$null) | ForEach-Object {
        if ($_ -match '-V:([0-9]+\.[0-9]+)') { $installed += $Matches[1] }
    }
    foreach ($pref in "3.13", "3.12", "3.11") {
        if ($installed -contains $pref) { return $pref }
    }
    if ($installed.Count -gt 0) {
        $best = ($installed | Sort-Object { [version]$_ } -Descending)[0]
        Write-Warn "未找到 3.13/3.12，自动使用 Python $best"
        return $best
    }
    throw "未检测到 Python 3.11/3.12/3.13。请从 python.org 安装 3.12 或 3.13（勾选 py launcher）。"
}

function Get-TorchIndex([string]$DriverCuda) {
    <# 按驱动支持的最大 CUDA 版本，选兼容的 PyTorch CUDA 源。
       最终是否可用仍由 torch.cuda.is_available() 实测兜底。 #>
    if (-not $DriverCuda) { return "https://download.pytorch.org/whl/cu124" }
    $v = [version]$DriverCuda
    if ($v -ge [version]"12.6") { return "https://download.pytorch.org/whl/cu126" }
    if ($v -ge [version]"12.4") { return "https://download.pytorch.org/whl/cu124" }
    if ($v -ge [version]"12.1") { return "https://download.pytorch.org/whl/cu121" }
    throw "驱动过旧（CUDA $DriverCuda < 12.1）。请升级 NVIDIA 驱动到 550+（CUDA 12.x）后重跑。"
}

function Wait-DatabaseHealthy([int]$TimeoutSeconds = 180) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $checked = 0
    do {
        $status = (& docker inspect --format '{{.State.Health.Status}}' cerno_postgres 2>$null | Select-Object -First 1)
        if ($status -eq "healthy") { return $true }
        $checked++
        if ($checked -eq 1) { Write-Info "等待数据库容器就绪 ..." }
        Start-Sleep -Seconds 3
    } while ((Get-Date) -lt $deadline)
    return $false
}

function Invoke-DownloadModels([string[]]$Components) {
    $dlArgs = @()
    foreach ($c in $Components) { $dlArgs += "--component"; $dlArgs += $c }
    $dlArgs += "--model-root";  $dlArgs += (Join-Path $ProjectRoot "models")
    $dlArgs += "--retries";     $dlArgs += "$DownloadRetries"
    Write-Info "组件：$($Components -join ' / ')"
    & $VenvPython (Join-Path $PSScriptRoot "download_models.py") @dlArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "模型准备未完成（失败步骤已保留，可直接重跑本脚本继续）。"
        return $false
    }
    return $true
}

function Set-ApiKeysInteractive {
    Write-Host "  摘要 API 需要两个 key（也可之后在「设置页」填写，此处可跳过）:" -ForegroundColor White
    $dash = Read-Host "  DashScope API Key (画面描述, 回车跳过)"
    $deep = Read-Host "  DeepSeek  API Key (摘要生成, 回车跳过)"
    if ([string]::IsNullOrWhiteSpace($dash) -and [string]::IsNullOrWhiteSpace($deep)) {
        Write-Info "已跳过 key 配置。"
        return
    }
    Set-ApiKeys $dash $deep
}

function Set-ApiKeys([string]$DashKey, [string]$DeepKey) {
    $tmp = Join-Path $env:TEMP "cerno_keys.json"
    @{ dashscope = $DashKey; deepseek = $DeepKey } | ConvertTo-Json | Set-Content -Path $tmp -Encoding utf8
    try {
        & $VenvPython -c "from core.settings_service import update_keys; import json; update_keys(json.load(open(r'$($tmp.Replace('\','/'))', encoding='utf-8')))"
        if ($LASTEXITCODE -ne 0) { throw "settings.json 写入失败" }
        Write-Ok "API key 已保存到 data/settings.json"
    } finally {
        Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    }
}

# ════════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════════

Set-Location $ProjectRoot

Write-Host "Cerno Windows 部署向导" -ForegroundColor Cyan
Write-Host "目标：本机 Python 环境 + Docker 数据库 + 本机模型（不含 Electron）"

$mode = Get-SelectedMode
Write-Ok "安装模式：$mode"

# [1/9] 前置检查（GPU / FFmpeg / Docker / Python 均为必装）
Write-Step "1/9" "检查环境（GPU + FFmpeg 必装）"
Require-Command "py" "请先安装 Python Launcher（python.org 安装时勾选）。"
Require-Command "docker" "请先安装并启动 Docker Desktop。"
Require-Command "ffmpeg" "FFmpeg 是必装依赖（转码/抽帧/导出/流媒体都依赖它）。安装：winget install Gyan.FFmpeg 后重开终端。"
Require-Command "nvidia-smi" "未检测到 NVIDIA GPU / CUDA 驱动。Cerno 依赖 GPU 推理（Embedding/检测/人脸/车牌），请安装 NVIDIA 驱动（建议 CUDA 12.x，驱动 ≥550）。"
$pythonVer = Get-BestPythonVersion
Write-Ok "Python $pythonVer"
if (Get-Command docker -ErrorAction SilentlyContinue) {
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "Docker 守护进程未运行，请先启动 Docker Desktop 再重跑。"
        throw "Docker 未运行。"
    }
}
$gpuName = & nvidia-smi --query-gpu=name --format=csv,noheader | Select-Object -First 1
$cudaVer = (& nvidia-smi 2>$null | Select-String "CUDA Version" | Select-Object -First 1).ToString().Trim()
Write-Ok "GPU: $gpuName"
if ($cudaVer) { Write-Ok $cudaVer }
# 记录驱动最大 CUDA 版本，供 deps 步骤按兼容性选 torch 源；过旧给出提示（最终由 torch 实测兜底）
$driverCuda = ([regex]::Match($cudaVer, "CUDA Version:\s*([0-9.]+)")).Groups[1].Value
if ($driverCuda -and [version]$driverCuda -lt [version]"12.0") {
    Write-Warn "当前驱动支持的 CUDA 版本为 $driverCuda，建议升级驱动到 550+（CUDA 12.x）以获得 PyTorch 兼容。"
}

# ffmpeg 必须带 CUDA 能力：NVDEC 硬解(NVIDIA 解码) + NVENC(h264_nvenc 转码)。
# 缺失时 video_util 会静默回退 cv2(CPU 解码)、format_service 会静默回退 libx264(CPU 编码)。
$ffEnc = (& ffmpeg -hide_banner -encoders 2>&1 | Out-String)
$ffDec = (& ffmpeg -hide_banner -decoders 2>&1 | Out-String)
if ($ffEnc -notmatch "h264_nvenc" -or $ffDec -notmatch "h264_cuvid") {
    Write-Fail "当前 ffmpeg 缺少 CUDA 编解码能力（需含 h264_nvenc 编码器与 h264_cuvid/hevc_cuvid 解码器）。"
    Write-Info "Cerno 依赖 NVDEC 硬解抽帧与 NVENC 转码；缺失会静默回退 CPU，性能骤降。"
    Write-Info "请安装带 CUDA 的完整版 FFmpeg：winget install Gyan.FFmpeg，然后重开终端重跑。"
    throw "ffmpeg 缺少 CUDA 支持。"
}
Write-Ok "ffmpeg CUDA 能力正常（h264_nvenc + h264_cuvid）"

# [2/9] 虚拟环境
Write-Step "2/9" "Python 虚拟环境"
if (Test-Path $VenvPython) {
    Write-Info "虚拟环境已存在，跳过创建。"
} else {
    & py "-$pythonVer" -m venv (Join-Path $ProjectRoot ".venv")
    if ($LASTEXITCODE -ne 0) { throw "虚拟环境创建失败。" }
    Write-Ok "已创建 .venv (Python $pythonVer)"
}

# [3/9] 依赖（含 CUDA 版 PyTorch）
Write-Step "3/9" "Python 依赖 + CUDA PyTorch"
if ($SkipDependencies) {
    Write-Info "已跳过（-SkipDependencies）。"
} else {
    Invoke-Checked $VenvPython @("-m", "pip", "install", "--upgrade", "pip") "pip 升级失败。"
    # ── torch：已可用（CUDA 实测 True）则直接复用，否则按驱动 CUDA 版本选源安装 ──
    Write-Info "检查现有 PyTorch GPU 支持 ..."
    $torchOk = (& $VenvPython -c "import torch; print(torch.cuda.is_available())" 2>$null | Select-Object -First 1)
    if ("$torchOk" -eq "True") {
        Write-Ok "PyTorch 已可用（CUDA），跳过安装。"
    } else {
        $torchIndex = Get-TorchIndex $driverCuda
        Write-Info "安装 CUDA 版 PyTorch（$torchIndex）——pip 默认装 CPU 版，必须用 PyTorch 官方源 ..."
        Invoke-Checked $VenvPython @("-m", "pip", "install", "torch", "--index-url", $torchIndex) "CUDA PyTorch 安装失败。"
    }
    Write-Info "安装其余依赖（首次可能需要数分钟）..."
    Invoke-Checked $VenvPython @("-m", "pip", "install", "-r", (Join-Path $ProjectRoot "requirements.txt")) "Python 依赖安装失败。"
    # ── onnxruntime：有 CUDA provider 则复用，否则替换为 onnxruntime-gpu ──
    Write-Info "检查 onnxruntime CUDA 支持（人脸/车牌需要）..."
    $ortOk = (& $VenvPython -c "import onnxruntime as ort; print('CUDAExecutionProvider' in ort.get_available_providers())" 2>$null | Select-Object -First 1)
    if ("$ortOk" -eq "True") {
        Write-Ok "onnxruntime-gpu 已可用，跳过替换。"
    } else {
        Write-Info "替换 onnxruntime → onnxruntime-gpu（否则人脸/车牌会静默跑 CPU）..."
        Invoke-Checked $VenvPython @("-m", "pip", "uninstall", "-y", "onnxruntime") "onnxruntime 卸载失败。"
        Invoke-Checked $VenvPython @("-m", "pip", "install", "onnxruntime-gpu") "onnxruntime-gpu 安装失败（人脸/车牌将回退 CPU 推理）。"
    }
    Write-Info "验证 PyTorch GPU 可用性 ..."
    & $VenvPython -c "import torch; assert torch.cuda.is_available(), 'cuda-unavailable'; print('torch', torch.__version__, '| cuda', torch.version.cuda, '| device', torch.cuda.get_device_name(0))"
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "PyTorch 检测不到 GPU。请确认：1) nvidia-smi 能列出 GPU；2) 驱动为 550+/CUDA 12.x；3) 未残留 CPU 版 torch。"
        throw "PyTorch GPU 验证失败。"
    }
    Write-Ok "PyTorch GPU 就绪"
}

# [4/9] 数据目录
Write-Step "4/9" "数据目录"
New-Item -ItemType Directory -Force (Join-Path $ProjectRoot "data\videos")    | Out-Null
New-Item -ItemType Directory -Force (Join-Path $ProjectRoot "data\artifacts") | Out-Null
New-Item -ItemType Directory -Force (Join-Path $ProjectRoot "models")         | Out-Null
Write-Ok "data/videos · data/artifacts · models 已就绪"

# [5/9] 数据库
Write-Step "5/9" "PostgreSQL + pgvector (Docker)"
if ($NoDb) {
    Write-Info "已跳过（-NoDb），请确保数据库可用并设置 POSTGRES_URI。"
} else {
    Invoke-Checked "docker" @("compose", "-f", (Join-Path $ProjectRoot "docker-compose.yaml"), "up", "-d", "db") "数据库容器启动失败。"
    if (-not (Wait-DatabaseHealthy)) {
        Write-Fail "数据库容器 3 分钟内未就绪。"
        Write-Info "排查：docker logs cerno_postgres"
        throw "数据库未就绪。"
    }
    Write-Ok "数据库容器 healthy"
}

# [6/9] 部署配置
Write-Step "6/9" "生成部署配置 config/config.windows.yaml"
if ($SkipConfig) {
    Write-Info "已跳过（-SkipConfig）。"
} else {
    $cfgArgs = @("--mode", $mode, "--project-root", $ProjectRoot)
    Invoke-Checked $VenvPython (@(Join-Path $PSScriptRoot "write_windows_config.py") + $cfgArgs) "部署配置生成失败。"
    Write-Ok "已生成 $ConfigFile"
}

# [7/9] API key（可选）
Write-Step "7/9" "摘要 API key（可选）"
if ($NonInteractive) {
    Write-Info "非交互模式：跳过 key 输入（可在设置页填写）。"
} else {
    if (Ask-YesNo "现在配置 DashScope / DeepSeek API key？" $false) {
        Set-ApiKeysInteractive
    } else {
        Write-Info "已跳过（设置页 → 系统设置 可随时填写）。"
    }
}

# [8/9] 模型
Write-Step "8/9" "模型准备"
# 只装参数面板可用的功能：yolo 检测 / face 人脸 / plate 车牌 / segmenter 场景分割。
# 音频转录(faster-whisper)、OCR、Grounding 均为面板置灰或未实现，不装。
$modelComponents = @("yolo", "face", "plate", "segmenter")
if ($mode -eq "full") { $modelComponents = @("embedding") + $modelComponents }

if ($SkipModels) {
    Write-Info "已跳过（-SkipModels）。"
} else {
    Write-Info "已就绪的组件会自动跳过；断点续传；失败自动重试 $DownloadRetries 次。"
    if (-not (Invoke-DownloadModels $modelComponents)) {
        Write-Fail "模型准备未完成。重新运行本脚本可续传。"
        throw "模型准备失败。"
    }
}

# [9/9] 完成
Write-Step "9/9" "完成"
Write-Host ""
Write-Host "部署基础已就绪。下一步：" -ForegroundColor White
Write-Host "  启动后端：  .\deploy\start_windows.ps1" -ForegroundColor Green
Write-Host "  访问界面：  http://127.0.0.1:8000（前端另起 dev server）" -ForegroundColor Green
Write-Host "  健康检查：  http://127.0.0.1:8000/health" -ForegroundColor Green
Write-Host "  部署配置：  $ConfigFile" -ForegroundColor DarkGray
Write-Host "  （config.yaml 未改动；后端通过 CERNO_CONFIG 环境变量读取部署配置）" -ForegroundColor DarkGray

if ($StartAfter -and -not $NonInteractive) {
    if (Ask-YesNo "立即启动后端？") {
        & (Join-Path $PSScriptRoot "start_windows.ps1")
    }
}
