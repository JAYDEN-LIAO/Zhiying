<#
Zhiying Windows 一键安装器（裸机 → 环境就绪）
═══════════════════════════════════════════════════════════
目标：在全新 Windows + NVIDIA GPU 机器上，自动安装 Zhiying 运行所需的
一切基础设施：
  系统级  Python / FFmpeg(CUDA) / WSL2 / Docker Desktop
  依赖级  CUDA torch(按 GPU 选源) + 匹配 torchvision + requirements 全部包
  模型级  embedding / yolo / reid / face / plate / segmenter

特性：
  - 智能探测：已有且兼容的组件直接复用；缺失/不兼容的自动安装对的版本
  - 网络智能：代理必填；需要代理的走代理、国内源直连、超时回退代理
  - 交互：开始时醒目提示注意事项 + 输入代理地址并测试
  - 健壮：错误如实反映到终端，绝不闪退（所有探测性命令 try/catch 包裹）
  - WSL2 缺失 → 自动放最后安装并提示重启（幂等续跑；重启后按打印清单操作）
  - 安装 + 自校验完成后，打印 db / 后端 / 前端 启动指令（由用户自行启动）

用法：
  Set-ExecutionPolicy -Scope Process Bypass
  .\deploy\setup_windows.ps1                                          # 交互式
  .\deploy\setup_windows.ps1 -Proxy http://127.0.0.1:7897 -NonInteractive  # 全自动
#>

param(
    [string]$Proxy = "",          # 代理地址（必填）；为空则交互输入
    [switch]$NonInteractive,      # 全自动（需同时传 -Proxy）
    [switch]$SkipDeps,            # 跳过依赖安装（torch/requirements，仅排障用）
    [switch]$SkipModels,          # 跳过模型下载（仅排障用）
    [switch]$SkipDocker,          # 跳过 Docker/WSL2/建库相关（仅排障用）
    [switch]$NoElevate,           # 不请求管理员（测试/排障用）
    [switch]$SkipProxyTest,       # 跳过代理可用性测试（排障用；正常安装必须真实代理）
    [int]$DownloadRetries = 3,
    [string]$PythonVersion = ""   # 空 = 自动探测 3.13→3.12→3.11
)

# ═══════════════════════════════════════════════════════════
# 0. 引导：目录 / 编码 / 提权
# ═══════════════════════════════════════════════════════════

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$PipIni = Join-Path $env:APPDATA "pip\pip.ini"

# 终端编码 → UTF-8（中文日志不乱码）
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

# 检测是否管理员；不是则提权重启（UAC）
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $isAdmin -and -not $NoElevate) {
    Write-Host "需要管理员权限，正在请求 UAC 提权..." -ForegroundColor Yellow
    $argsFlat = ($PSBoundParameters.GetEnumerator() | ForEach-Object {
        if ($_.Value -is [bool]) { if ($_.Value) { "-$($_.Key)" } }
        else { "-$($_.Key) `"$($_.Value)`"" }
    }) -join " "
    Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", "`"$PSCommandPath`"", $argsFlat
    ) -Verb RunAs
    exit
}

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

# ═══════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════

function Test-Cmd([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

# 运行原生命令并返回真实退出码。
# PS5.1 + $ErrorActionPreference=Stop 会在"命令写 stderr（如 torch import 警告）"时、进程尚未退出
# 就抛 NativeCommandError，导致 $LASTEXITCODE 还是上一条命令的残留值。
# 正确做法：执行期间临时切 Continue，杜绝该错误，命令跑完后 $LASTEXITCODE 即为真实退出码。
function Invoke-Native {
    param([string]$FilePath, [string[]]$ArgumentList)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        # 捕获输出后经 Out-Host 显示，避免 stdout 泄漏成函数返回值（污染退出码判断）
        $output = & $FilePath @ArgumentList 2>&1
        if ($null -ne $output) { $output | Out-Host }
    } finally {
        $ErrorActionPreference = $prev
    }
    return $LASTEXITCODE
}

# 捕获原生命令首行非空输出（探针用）。同样临时切 Continue 防 NativeCommandError。
function Get-CaptureLine {
    param([string]$FilePath, [string[]]$ArgumentList)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        return (& $FilePath @ArgumentList 2>$null | Select-Object -First 1)
    } catch {
        return $null
    } finally {
        $ErrorActionPreference = $prev
    }
}

# 创建虚拟 onnxruntime dist-info 桩：
# hyperlpr3/insightface 声明依赖 onnxruntime 发行版，但部署用 onnxruntime-gpu（两者无法共存——共用模块目录）。
# Provides-Dist 不被 pip check 识别；建一个"无文件"的 dist-info 桩让 pip 认为 onnxruntime 已装，
# 避免后续安装/重跑时把 CPU 版 onnxruntime 拉回来抢占 GPU 模块（导致人脸/车牌静默跑 CPU）。
function New-OnnxruntimeStub {
    param([string]$PythonExe)
    $code = @'
import sys
from pathlib import Path
import importlib.metadata as m
site = Path(sys.prefix) / "Lib" / "site-packages"
ver = m.version("onnxruntime-gpu")
distinfo = site / f"onnxruntime-{ver}.dist-info"
distinfo.mkdir(exist_ok=True)
(distinfo / "METADATA").write_text(
    f"Metadata-Version: 2.1\nName: onnxruntime\nVersion: {ver}\n"
    "Summary: Virtual package provided by onnxruntime-gpu\n", encoding="utf-8")
(distinfo / "top_level.txt").write_text("", encoding="utf-8")
(distinfo / "RECORD").write_text("METADATA,,\ntop_level.txt,,\nRECORD,,\n", encoding="utf-8")
print(f"onnxruntime virtual stub OK ({ver})")
'@
    $exit = Invoke-Native $PythonExe @("-c", $code)
    if ($exit -ne 0) { Write-Warn "onnxruntime 虚拟桩创建失败（pip check 会警告 onnxruntime 缺失，不影响运行）" }
}

# 该 host 需要走代理（GitHub / PyTorch 官方源）；其余（国内镜像）直连更快
function Test-HostNeedsProxy([string]$Url) {
    return $Url -match "github\.com|download\.pytorch\.org|pypi\.org|files\.pythonhosted"
}

function Invoke-Checked([string]$FilePath, [string[]]$ArgumentList, [string]$FailureMessage) {
    $exit = Invoke-Native $FilePath $ArgumentList
    if ($exit -ne 0) { throw $FailureMessage }
}

function Get-BestPythonVersion {
    if ($PythonVersion -ne "") {
        & py "-$PythonVersion" --version 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "指定的 Python $PythonVersion 不可用" }
        return $PythonVersion
    }
    $installed = @()
    (& py -0p 2>$null) | ForEach-Object { if ($_ -match '-V:([0-9]+\.[0-9]+)') { $installed += $Matches[1] } }
    foreach ($pref in "3.13", "3.12", "3.11") { if ($installed -contains $pref) { return $pref } }
    if ($installed.Count -gt 0) {
        return ($installed | Sort-Object { [version]$_ } -Descending)[0]
    }
    throw "未检测到 Python 3.11/3.12/3.13。请先安装 python.org 的 3.12/3.13（勾选 py launcher）。"
}

# 探测已安装 Python 的可执行路径（winget 装完 PATH 不刷新，需按已知位置找）
function Find-PythonExe {
    $cands = @(
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:ProgramFiles\Python313\python.exe"
    )
    foreach ($c in $cands) { if (Test-Path $c) { return $c } }
    # 回退：从 PATH 找 python.exe
    $fromPath = (Get-Command python.exe -ErrorAction SilentlyContinue)
    if ($fromPath) { return $fromPath.Source }
    return $null
}

# 探测已安装 FFmpeg 的 bin 目录（winget Gyan.FFmpeg → WinGet Packages 下）
function Find-FfmpegBin {
    $links = "$env:LOCALAPPDATA\Microsoft\WinGet\Links"
    if (Test-Path (Join-Path $links "ffmpeg.exe")) { return $links }
    $pkg = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "Gyan.FFmpeg*" } | Select-Object -First 1
    if ($pkg) {
        $bin = Get-ChildItem $pkg.FullName -Recurse -Filter "ffmpeg.exe" -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($bin) { return $bin.DirectoryName }
    }
    return $null
}

# 需要代理的下载：curl -x；否则直连。timeout 秒后失败自动切代理重试一次。
function Invoke-CurlDownload {
    param(
        [string]$Url,
        [string]$OutPath,
        [switch]$ForceProxy,
        [switch]$ForceDirect,
        [int]$TimeoutSec = 90,
        [int]$Retries = 2
    )
    $dir = Split-Path -Parent $OutPath
    if ($dir) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $useProxy = $ForceProxy -or (-not $ForceDirect -and (Test-HostNeedsProxy $Url))
    for ($i = 0; $i -lt $Retries; $i++) {
        $argList = @("-L", "-o", $OutPath, "--max-time", "$TimeoutSec", $Url)
        if ($useProxy) { $argList = @("-x", $Script:ProxyUrl) + $argList }
        $proc = Start-Process -FilePath "curl.exe" -ArgumentList $argList -NoNewWindow -Wait -PassThru
        if ($proc.ExitCode -eq 0) { return $true }
        # 失败 → 若还没试代理，则强制切代理重试
        if (-not $useProxy) {
            Write-Warn "直连超时 ($Url)，改用代理重试..."
            $useProxy = $true
        } else {
            Start-Sleep -Seconds 3
        }
    }
    return $false
}

# 在指定代理模式下运行 python/pip（设/清 HTTP(S)_PROXY）。
# 注意：形参名不能叫 $Args（内置自动变量，会失效导致无参调用进 REPL）。
function Invoke-PythonWithProxy {
    param([string]$PythonExe, [string[]]$ArgumentList, [bool]$UseProxy)
    if ($UseProxy) {
        $env:HTTP_PROXY = $Script:ProxyUrl; $env:HTTPS_PROXY = $Script:ProxyUrl
    } else {
        Remove-Item Env:HTTP_PROXY -ErrorAction SilentlyContinue
        Remove-Item Env:HTTPS_PROXY -ErrorAction SilentlyContinue
    }
    try {
        return (Invoke-Native $PythonExe $ArgumentList)
    } finally {
        Remove-Item Env:HTTP_PROXY -ErrorAction SilentlyContinue
        Remove-Item Env:HTTPS_PROXY -ErrorAction SilentlyContinue
    }
}

# 从 pytorch 索引页解析最新 wheel 文件名（torch/torchvision）
function Get-PytorchWheelName {
    param([string]$IndexUrl, [string]$Package, [string]$Pattern)
    $page = Invoke-CurlDownload $IndexUrl (Join-Path $env:TEMP "pt_index_$Package.html") -ForceProxy
    if (-not $page) { throw "无法获取 $Package 索引页" }
    $html = Get-Content (Join-Path $env:TEMP "pt_index_$Package.html") -Raw -ErrorAction SilentlyContinue
    $m = [regex]::Match($html, $Pattern)
    if (-not $m.Success) { throw "在索引页找不到匹配 $Package 的 wheel ($Pattern)" }
    return $m.Value
}

function Get-TorchIndex([string]$GpuName, [string]$DriverCuda) {
    # Blackwell (sm_120, RTX 50xx)：cu126 缺内核，需 cu130+
    if ($GpuName -match "RTX\s*5|Blackwell") { return "https://download.pytorch.org/whl/cu130" }
    if (-not $DriverCuda) { return "https://download.pytorch.org/whl/cu126" }
    $v = [version]$DriverCuda
    if ($v -ge [version]"13.0") { return "https://download.pytorch.org/whl/cu130" }
    if ($v -ge [version]"12.8") { return "https://download.pytorch.org/whl/cu128" }
    if ($v -ge [version]"12.6") { return "https://download.pytorch.org/whl/cu126" }
    if ($v -ge [version]"12.4") { return "https://download.pytorch.org/whl/cu124" }
    if ($v -ge [version]"12.1") { return "https://download.pytorch.org/whl/cu121" }
    throw "驱动过旧（CUDA $DriverCuda < 12.1），请升级 NVIDIA 驱动到 550+"
}

# ═══════════════════════════════════════════════════════════
# 1. 交互：注意事项 + 代理输入
# ═══════════════════════════════════════════════════════════

Write-Host "Zhiying Windows 一键安装器（裸机 → 环境就绪）" -ForegroundColor Cyan
Write-Host "目标：自动安装 Python / FFmpeg / WSL2 / Docker / CUDA torch / 全部依赖 / 全部模型"
Write-Host ""

Write-Host "━━━━ 注意事项（请先阅读）━━━━" -ForegroundColor Yellow
Write-Host "  1. 需要管理员权限（脚本会自动请求 UAC）"
Write-Host "  2. 需要 NVIDIA GPU + 驱动（脚本会检测 CUDA 版本）"
Write-Host "  3. 需要可用的代理（脚本强制要求，用于 GitHub / PyTorch 下载）"
Write-Host "  4. 总下载量约 25GB+（torch ~2.6GB + embedding 16GB + 其余模型），请保证磁盘空间"
Write-Host "  5. 若 WSL2 未安装：脚本会把 WSL2+Docker 放最后安装，装完需要重启一次"
Write-Host "  6. 装完仅打印启动指令；数据库/后端/前端由你自己手动启动"
Write-Host "  7. 摘要 API key（DashScope/DeepSeek）请在启动后于前端「设置页」填写"
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Yellow

# ── 代理（必填）──
if ([string]::IsNullOrWhiteSpace($Proxy)) {
    if ($NonInteractive) { throw "-NonInteractive 模式必须同时传 -Proxy" }
    Write-Host ""
    $Proxy = Read-Host "请输入代理地址（必填，如 http://127.0.0.1:7897）"
}
$Proxy = $Proxy.Trim().TrimEnd("/")
if ([string]::IsNullOrWhiteSpace($Proxy)) { throw "代理地址不能为空" }
$Script:ProxyUrl = $Proxy

# 测试代理
if ($SkipProxyTest) {
    Write-Warn "已跳过代理测试（-SkipProxyTest，仅排障用）"
} else {
    Write-Info "测试代理 $Proxy ..."
    $code = & curl.exe -x "$Proxy" -s -o NUL -w "%{http_code}" --max-time 15 https://github.com
    if ($code -notmatch "^[23]\d\d$") {
        throw "代理测试失败（github.com 返回 $code）。请确认代理软件已启动且地址正确。"
    }
    Write-Ok "代理可用（github.com → $code）"
}

$mode = "full"   # 全装模式
Write-Ok "安装模式：full（全量：embedding + yolo + reid + face + plate + segmenter + 全部依赖）"

# ═══════════════════════════════════════════════════════════
# 2. 环境探测
# ═══════════════════════════════════════════════════════════

Write-Step "1/10" "探测现有环境"
$hasPy   = Test-Cmd "py"
$hasFF   = Test-Cmd "ffmpeg"
$hasNv   = Test-Cmd "nvidia-smi"
$hasDocker = Test-Cmd "docker"
$gpuName = ""; $driverCuda = ""

if ($hasNv) {
    $gpuName = (& nvidia-smi --query-gpu=name --format=csv,noheader 2>$null | Select-Object -First 1)
    $cudaVer = (& nvidia-smi 2>$null | Select-String "CUDA Version" | Select-Object -First 1).ToString()
    if ($cudaVer -match "CUDA Version:\s*([0-9.]+)") { $driverCuda = $Matches[1] }
    Write-Ok "GPU: $gpuName | 驱动 CUDA: $driverCuda"
} else {
    Write-Fail "未检测到 nvidia-smi（NVIDIA 驱动）。Zhiying 依赖 GPU 推理，请先安装 NVIDIA 驱动。"
    throw "缺少 NVIDIA GPU / 驱动"
}

Write-Ok "Python: $(if($hasPy){'已装'}else{'缺失'}) | FFmpeg: $(if($hasFF){'已装'}else{'缺失'}) | Docker: $(if($hasDocker){'已装'}else{'缺失'})"

# WSL2 状态（决定是否走"两段式+重启"）
$wslOut = (& wsl --status 2>$null | Out-String)
$wslMissing = $wslOut -notmatch "WSL2|已安装|安装"
Write-Ok "WSL2: $(if($wslMissing){'缺失（将放最后安装，需重启）'}else{'已就绪'})"

# ═══════════════════════════════════════════════════════════
# 3. 安装 Python（缺失时）
# ═══════════════════════════════════════════════════════════

Write-Step "2/10" "Python 环境"
if (-not $hasPy) {
    Write-Info "Python 未安装，正在安装 Python 3.13 ..."
    $exit = Invoke-Native "winget" @("install", "--id", "Python.Python.3.13", "--accept-source-agreements", "--accept-package-agreements", "--disable-interactivity")
    if ($exit -ne 0) { throw "Python 安装失败" }
    # PATH 未刷新，按已知位置定位
    $pyExe = Find-PythonExe
    if (-not $pyExe) { throw "Python 装完但找不到 python.exe" }
    Write-Ok "Python 已安装: $pyExe"
} else {
    $pyExe = Find-PythonExe
    Write-Ok "Python 已存在: $(if($pyExe){$pyExe}else{'py launcher'})"
}
$pyVersion = Get-BestPythonVersion

# ── venv ──
if (Test-Path $VenvPython) {
    Write-Ok "venv 已存在，跳过创建"
} else {
    $exit = Invoke-Native "py" @("-$pyVersion", "-m", "venv", (Join-Path $ProjectRoot ".venv"))
    if ($exit -ne 0) { throw "venv 创建失败" }
    Write-Ok "已创建 .venv (Python $pyVersion)"
}

# ═══════════════════════════════════════════════════════════
# 4. 安装 FFmpeg（缺失或无 CUDA 编解码时）
# ═══════════════════════════════════════════════════════════

Write-Step "3/10" "FFmpeg（CUDA 版）"
$ffBin = Find-FfmpegBin
$ffCudaOk = $false
if ($ffBin) {
    $enc = (& "$ffBin\ffmpeg.exe" -hide_banner -encoders 2>&1 | Out-String)
    $dec = (& "$ffBin\ffmpeg.exe" -hide_banner -decoders 2>&1 | Out-String)
    if ($enc -match "h264_nvenc" -and $dec -match "h264_cuvid") { $ffCudaOk = $true }
}
if ($ffCudaOk) {
    Write-Ok "FFmpeg CUDA 能力正常: $ffBin"
} else {
    Write-Info "安装/修复 FFmpeg（Gyan 完整版，含 CUDA 编解码）..."
    $exit = Invoke-Native "winget" @("install", "--id", "Gyan.FFmpeg", "--accept-source-agreements", "--accept-package-agreements", "--disable-interactivity")
    if ($exit -ne 0) { throw "FFmpeg 安装失败" }
    $ffBin = Find-FfmpegBin
    if (-not $ffBin) { throw "FFmpeg 装完但找不到二进制" }
    Write-Ok "FFmpeg 已安装: $ffBin"
}
# 全程用绝对路径调 ffmpeg/ffprobe（避免 PATH 依赖）
$Script:FfBin = $ffBin
$env:PATH = "$ffBin;$env:PATH"

# ═══════════════════════════════════════════════════════════
# 5. CUDA torch + torchvision
# ═══════════════════════════════════════════════════════════

Write-Step "4/10" "CUDA PyTorch + torchvision"
if ($SkipDeps) { Write-Info "已跳过（-SkipDeps）" }
else {
    # pip 国内镜像（requirements 非 torch 部分走 Aliyun 直连，免代理）
    & $VenvPython -m pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ 2>$null

    # ── torch：已可用则复用，否则 curl 下载 wheel + 本地安装 ──
    $torchOk = Get-CaptureLine $VenvPython @("-c", "import torch; print(torch.cuda.is_available())")
    if ("$torchOk" -eq "True") {
        Write-Ok "PyTorch 已可用（CUDA），跳过安装"
    } else {
        $torchIndex = Get-TorchIndex $gpuName $driverCuda
        Write-Info "安装 CUDA 版 PyTorch（$torchIndex）..."
        $wheel = Get-PytorchWheelName $torchIndex "torch" "torch-2\.[0-9.]+%2Bcu[0-9]+-cp313-cp313-win_amd64\.whl"
        $wheelUrl = "$torchIndex/$wheel"
        Write-Info "下载 torch wheel: $wheelUrl"
        if (-not (Invoke-CurlDownload $wheelUrl (Join-Path $ProjectRoot "models\.torch_dl\$wheel") -ForceProxy -TimeoutSec 600)) {
            throw "torch wheel 下载失败"
        }
        Invoke-Checked $VenvPython @("-m", "pip", "install", (Join-Path $ProjectRoot "models\.torch_dl\$wheel")) "torch 安装失败"
        Write-Ok "torch 已安装"
    }

    # ── torchvision：必须与 torch 同 CUDA 源（否则 torchvision::nms 无 CUDA 内核）──
    # 判定：直接尝试 nms on CUDA
    $tvCudaOk = Get-CaptureLine $VenvPython @("-c", "import torch, torchvision; boxes=torch.tensor([[0,0,10,10],[1,1,11,11]],dtype=torch.float32,device='cuda'); scores=torch.tensor([0.9,0.8],device='cuda'); torch.ops.torchvision.nms(boxes,scores,0.5); print('OK')")
    if ("$tvCudaOk" -eq "OK") {
        Write-Ok "torchvision CUDA 就绪，跳过安装"
    } else {
        Write-Info "torchvision CUDA 不可用，安装匹配版本（同 $torchIndex 源）..."
        $tvWheel = Get-PytorchWheelName $torchIndex "torchvision" "torchvision-0\.[0-9.]+%2Bcu[0-9]+-cp313-cp313-win_amd64\.whl"
        $tvUrl = "$torchIndex/$tvWheel"
        if (-not (Invoke-CurlDownload $tvUrl (Join-Path $ProjectRoot "models\.torch_dl\$tvWheel") -ForceProxy -TimeoutSec 300)) {
            throw "torchvision wheel 下载失败"
        }
        & $VenvPython -m pip uninstall -y torchvision 2>$null
        Invoke-Checked $VenvPython @("-m", "pip", "install", (Join-Path $ProjectRoot "models\.torch_dl\$tvWheel")) "torchvision 安装失败"
        Write-Ok "torchvision 已重装（CUDA 版）"
    }

    # ── 真实 CUDA kernel 验证（is_available 会假通过，kernel 缺失才炸）──
    Write-Info "验证真实 CUDA kernel ..."
    $exit = Invoke-Native $VenvPython @("-c", "import torch; x=torch.randn(1024,1024,device='cuda'); y=(x@x).sum().item(); print('cuda-ok')")
    if ($exit -ne 0) {
        throw "CUDA kernel 验证失败——torch 版本与该 GPU 不兼容，请升级驱动后重跑"
    }
    Write-Ok "PyTorch GPU 就绪"
}

# ═══════════════════════════════════════════════════════════
# 6. requirements + 关键依赖（onnxruntime-gpu / accelerate / lap）
# ═══════════════════════════════════════════════════════════

Write-Step "5/10" "Python 依赖"
if ($SkipDeps) { Write-Info "已跳过（-SkipDeps）" }
else {
    Write-Info "安装 requirements（Aliyun 国内镜像直连，排除 onnxruntime——由 onnxruntime-gpu 单独处理）..."
    # onnxruntime(CPU) 与 onnxruntime-gpu 是不同发行版，同时装会让 CPU 版抢占 import 导致人脸/车牌跑 CPU；
    # 生成剔除 onnxruntime 行的临时 requirements，gpu 版由下面的 swap 逻辑统一处理（幂等）。
    $tmpReq = Join-Path $env:TEMP "requirements-no-onnx.txt"
    Get-Content (Join-Path $ProjectRoot "requirements.txt") -ErrorAction Stop |
        Where-Object { $_ -notmatch "^\s*onnxruntime" } |
        Set-Content $tmpReq -Encoding UTF8
    $rc = Invoke-PythonWithProxy $VenvPython @("-m", "pip", "install", "-r", $tmpReq) $false
    if ($rc -ne 0) { throw "requirements 安装失败" }

    # ── onnxruntime-gpu（人脸/车牌需要 CUDA provider）──
    $ortOk = Get-CaptureLine $VenvPython @("-c", "import onnxruntime as ort; print('CUDAExecutionProvider' in ort.get_available_providers())")
    if ("$ortOk" -eq "True") {
        Write-Ok "onnxruntime-gpu 已就绪"
    } else {
        Write-Info "替换 onnxruntime → onnxruntime-gpu（pip 大文件会卡死，走 curl 下载）..."
        # 从 Aliyun 索引解析 onnxruntime-gpu wheel 真实链接
        $null = Invoke-CurlDownload "https://mirrors.aliyun.com/pypi/simple/onnxruntime-gpu/" (Join-Path $env:TEMP "ort_index.html") -ForceDirect
        $ortHtml = Get-Content (Join-Path $env:TEMP "ort_index.html") -Raw -ErrorAction SilentlyContinue
        # href 形如 ../../packages/<hash>/onnxruntime_gpu-1.28.0-...whl#sha256=...
        $href = [regex]::Match($ortHtml, 'href="([^"]*onnxruntime_gpu-1\.[0-9.]+-cp313-cp313-win_amd64\.whl[^"]*)"').Groups[1].Value
        if (-not $href) { throw "找不到 onnxruntime-gpu wheel" }
        $ortClean = $href.Split('#')[0]
        if ($ortClean -like "http*") { $ortUrl = $ortClean }
        else { $ortUrl = $ortClean -replace "^\.\./\.\./", "https://mirrors.aliyun.com/pypi/" }
        $ortName = [IO.Path]::GetFileName($ortClean)
        if (-not (Invoke-CurlDownload $ortUrl (Join-Path $ProjectRoot "models\.torch_dl\$ortName") -ForceDirect -TimeoutSec 600)) {
            # 直连超时 → 代理重试
            if (-not (Invoke-CurlDownload $ortUrl (Join-Path $ProjectRoot "models\.torch_dl\$ortName") -ForceProxy -TimeoutSec 600)) {
                throw "onnxruntime-gpu 下载失败"
            }
        }
        $null = Invoke-Native $VenvPython @("-m", "pip", "uninstall", "-y", "onnxruntime")
        Invoke-Checked $VenvPython @("-m", "pip", "install", (Join-Path $ProjectRoot "models\.torch_dl\$ortName")) "onnxruntime-gpu 安装失败"
        Write-Ok "onnxruntime-gpu 已安装"
    }
    # 无论上面是"跳过"还是"重装"，都确保虚拟 onnxruntime 桩存在（hyperlpr3/insightface 依赖其发行版名）
    New-OnnxruntimeStub $VenvPython

    # ── accelerate（embedder device_map 必需）+ lap（BoT-SORT）──
    Invoke-Checked $VenvPython @("-m", "pip", "install", "accelerate", "lap") "accelerate/lap 安装失败"
    Write-Ok "accelerate + lap 已安装"
}

# ═══════════════════════════════════════════════════════════
# 7. 模型下载（embedding / yolo / reid / face / plate / segmenter）
# ═══════════════════════════════════════════════════════════

Write-Step "6/10" "模型准备"
if ($SkipModels) { Write-Info "已跳过（-SkipModels）" }
else {
    $dlPy = Join-Path $PSScriptRoot "download_models.py"
    # 直连组件（国内源）：embedding + plate + segmenter
    Write-Info "下载国内源模型（embedding / plate / segmenter）..."
    $rc = Invoke-PythonWithProxy $VenvPython @(($dlPy), "--component", "embedding", "--component", "plate", "--component", "segmenter", "--model-root", (Join-Path $ProjectRoot "models"), "--retries", "$DownloadRetries") $false
    if ($rc -ne 0) {
        # 超时 → 整组带代理重试（幂等，已完成组件自动跳过）
        Write-Warn "国内源下载失败，带代理重试..."
        $rc = Invoke-PythonWithProxy $VenvPython @(($dlPy), "--component", "embedding", "--component", "plate", "--component", "segmenter", "--model-root", (Join-Path $ProjectRoot "models"), "--retries", "$DownloadRetries") $true
    }
    if ($rc -ne 0) { throw "国内源模型下载失败" }

    # 代理组件（GitHub 源）：yolo + reid + face
    Write-Info "下载 GitHub 源模型（yolo / reid / face，走代理）..."
    $rc = Invoke-PythonWithProxy $VenvPython @(($dlPy), "--component", "yolo", "--component", "reid", "--component", "face", "--model-root", (Join-Path $ProjectRoot "models"), "--retries", "$DownloadRetries") $true
    if ($rc -ne 0) { throw "GitHub 源模型下载失败（检查代理）" }

    Write-Ok "全部模型就绪"
}

# ═══════════════════════════════════════════════════════════
# 8. 数据库 + Docker（自适应：WSL2 缺失 → 放最后装并提示重启）
# ═══════════════════════════════════════════════════════════

Write-Step "7/10" "数据库（PostgreSQL + pgvector）"
if ($SkipDocker) { Write-Info "已跳过（-SkipDocker）" }
else {
    if ($wslMissing) {
        Write-Warn "WSL2 未安装 → Docker 相关放到最后一步安装，装完需重启一次电脑"
    } else {
        # WSL2 已就绪：确保 Docker 引擎运行
        $dockerReady = $false
        try { & docker info *> $null; if ($LASTEXITCODE -eq 0) { $dockerReady = $true } } catch { $dockerReady = $false }
        if (-not $dockerReady) {
            Write-Info "启动 Docker Desktop ..."
            Start-Process -FilePath "C:\Program Files\Docker\Docker\Docker Desktop.exe"
            for ($i = 0; $i -lt 30; $i++) {
                try { & docker info *> $null; if ($LASTEXITCODE -eq 0) { $dockerReady = $true; break } } catch { }
                Start-Sleep -Seconds 5
            }
        }
        if (-not $dockerReady) { throw "Docker 引擎未就绪" }
        Write-Ok "Docker 引擎就绪"

        # 配置 Docker 代理 + 国内镜像（保证拉镜像顺利）
        Write-Info "配置 Docker 代理 / 国内镜像 ..."
        $dockerSettings = Join-Path $env:APPDATA "Docker\settings-store.json"
        if (Test-Path $dockerSettings) {
            try {
                $ds = Get-Content $dockerSettings -Raw | ConvertFrom-Json
                $ds | Add-Member -NotePropertyName ProxyHttpMode -NotePropertyValue "manual" -Force
                $ds | Add-Member -NotePropertyName OverrideProxyHTTP -NotePropertyValue $Proxy -Force
                $ds | Add-Member -NotePropertyName OverrideProxyHTTPS -NotePropertyValue $Proxy -Force
                $ds | ConvertTo-Json -Depth 10 | Set-Content $dockerSettings -Encoding UTF8
            } catch { Write-Warn "Docker 代理配置写入失败（可手动在 Docker Desktop 设置）" }
        }
        $daemonJson = Join-Path $env:USERPROFILE ".docker\daemon.json"
        try {
            $dj = if (Test-Path $daemonJson) { Get-Content $daemonJson -Raw | ConvertFrom-Json } else { [pscustomobject]@{} }
            $dj | Add-Member -NotePropertyName registry-mirrors -NotePropertyValue @("https://docker.m.daocloud.io") -Force
            $dj | ConvertTo-Json -Depth 10 | Set-Content $daemonJson -Encoding UTF8
        } catch { Write-Warn "Docker daemon.json 写入失败" }

        # 拉取 pgvector 镜像
        Write-Info "拉取 pgvector 镜像（约 630MB）..."
        $exit = Invoke-Native "docker" @("pull", "pgvector/pgvector:pg17")
        if ($exit -ne 0) {
            Write-Warn "pgvector 拉取失败，稍后由 docker compose 自动重试（见启动清单）"
        } else {
            Write-Ok "pgvector 镜像已就绪"
        }
    }
}

# ═══════════════════════════════════════════════════════════
# 9. 校验
# ═══════════════════════════════════════════════════════════

Write-Step "8/10" "校验"
Write-Info "校验模型 ..."
$exit = Invoke-Native $VenvPython @((Join-Path $PSScriptRoot "download_models.py"), "--component", "embedding", "--component", "yolo", "--component", "reid", "--component", "face", "--component", "plate", "--component", "segmenter", "--model-root", (Join-Path $ProjectRoot "models"), "--verify-only")
if ($exit -ne 0) { Write-Fail "存在缺失模型"; throw "模型校验失败" }
Write-Ok "模型校验通过"

# ═══════════════════════════════════════════════════════════
# 10. WSL2 + Docker Desktop（缺失时最后装，需重启）
# ═══════════════════════════════════════════════════════════

Write-Step "9/10" "WSL2 + Docker Desktop（最后安装）"
if ($SkipDocker) { Write-Info "已跳过（-SkipDocker）" }
elseif ($wslMissing) {
    Write-Info "安装 WSL2 ..."
    $wslLog = Join-Path $env:TEMP "wsl_install.log"
    $inner = "cmd.exe /c `"wsl --install > `"$wslLog`" 2>&1`""
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "`"$inner`"" -Verb RunAs -Wait
    Write-Info "安装 Docker Desktop ..."
    $exit = Invoke-Native "winget" @("install", "--id", "Docker.DockerDesktop", "--accept-source-agreements", "--accept-package-agreements", "--disable-interactivity")
    if ($exit -ne 0) { Write-Warn "Docker Desktop 安装失败，请重启后手动 winget install Docker.DockerDesktop" }

    Write-Host ""
    Write-Host "════════════════════════════════════════════" -ForegroundColor Magenta
    Write-Host "  所有其他组件已安装并校验通过。" -ForegroundColor Magenta
    Write-Host "  WSL2 / Docker 需要重启一次电脑才能生效。" -ForegroundColor Magenta
    Write-Host "  请重启电脑，然后按下方清单启动服务。" -ForegroundColor Magenta
    Write-Host "  （可选）重启后再双击本脚本，可补拉 pgvector 镜像。" -ForegroundColor Magenta
    Write-Host "════════════════════════════════════════════" -ForegroundColor Magenta
} else {
    Write-Ok "WSL2 已就绪，跳过"
}

# ═══════════════════════════════════════════════════════════
# 11. 完成：启动指令
# ═══════════════════════════════════════════════════════════

Write-Step "10/10" "完成"
Write-Host ""
Write-Host "  ✅ 环境安装完成。以下服务由你自己启动：" -ForegroundColor Green
Write-Host ""
Write-Host "  【1】数据库（PostgreSQL + pgvector）" -ForegroundColor White
Write-Host "      启动 Docker Desktop 后，在项目根执行：" -ForegroundColor Gray
Write-Host "        docker compose up -d db" -ForegroundColor Yellow
Write-Host "      等待 healthy：docker ps | findstr zhiying_postgres" -ForegroundColor Gray
Write-Host ""
Write-Host "  【2】后端" -ForegroundColor White
Write-Host "      在项目根执行：" -ForegroundColor Gray
Write-Host "        .\.venv\Scripts\python -m uvicorn main:app --host 127.0.0.1 --port 8000" -ForegroundColor Yellow
Write-Host "      健康检查：http://127.0.0.1:8000/health" -ForegroundColor Gray
Write-Host ""
Write-Host "  【3】前端" -ForegroundColor White
Write-Host "      cd frontend && npm install --registry=https://registry.npmmirror.com" -ForegroundColor Gray
Write-Host "      npm run dev" -ForegroundColor Yellow
Write-Host "      访问：http://localhost:5173" -ForegroundColor Gray
Write-Host ""
Write-Host "  【4】API key（可选但推荐）" -ForegroundColor White
Write-Host "      前端 → 设置页 → 系统设置，填 DashScope + DeepSeek key（保存即生效）" -ForegroundColor Gray
Write-Host ""

# 清理下载的 wheel（释放 ~5GB）
if (Test-Path (Join-Path $ProjectRoot "models\.torch_dl")) {
    Remove-Item (Join-Path $ProjectRoot "models\.torch_dl") -Recurse -Force -ErrorAction SilentlyContinue
    Write-Ok "已清理临时 wheel 缓存"
}
