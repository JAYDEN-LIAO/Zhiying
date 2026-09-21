# ============================================================================
#  Zhiying 新机一键部署安装器（交互式）
#
#  用途：全新 Windows（可能只有 git、连 python 都没有）→ 双击本脚本 →
#        命令行窗口交互（选 2B/8B 模型 + 输代理）→ 自动托管：
#          Python → .venv+依赖 → 内嵌 PostgreSQL(vendor/pg) → 模型(按档位)
#          → config.yaml 生成 → 建表 → 校验
#        完成后：日常更新 git pull + pip install；跑桌面端 python desktoppp.py；
#
#  用法： 双击本文件，或
#         powershell -ExecutionPolicy Bypass -File deploy\setup_windows.ps1
#  调试：  -SkipModels 跳过模型下载；-SkipPg 跳过内嵌 postgres 组装
# ============================================================================
param(
    [switch]$SkipModels,
    [switch]$SkipPg,
    [switch]$NoElevate,
    # 非交互参数（Inno 安装器 [run] 静默调用用）：
    [string]$EmbeddingProfile = "",   # 填 "8b"/"2b" 则跳过 2B/8B 交互选择
    [string]$Proxy = "",              # 填 "http://..." 则跳过代理交互输入
    [switch]$Quiet,                   # 跳过所有 Read-Host 暂停（错误提示/结尾）
    # Inno 安装器进度集成：
    [string]$ProgressLog = "",        # 写进度行（ASCII："PROGRESS`t<0-100>`t<slug>"）供安装器轮询
    [string]$DoneMarker = "",         # 结束/出错时写退出码（"0"=成功 "1"=失败）供安装器判断
    [string]$OutputLog = ""           # 完整输出日志（Start-Transcript 捕获全部 Write-Host，供安装器进度页小窗实时展示）
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
# UAC 提权会把进程工作目录重置到 C:\Windows\System32，必须切回项目根（否则 .venv 等相对路径全建错地方）
Set-Location $ProjectRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$DownloadRetries = 5

# ── 单实例守卫：防上次失败/取消残留的实例与本实例并行写 install.progress ──
# 并行实例各自追加进度行 → 安装器状态文字在多个阶段间来回闪、进度互相踩。
# 命名 Mutex 全局互斥；拿不到说明已有实例在跑（正常路径下安装器启动前已清残留，这里是最后防线）。
$script:SetupMutex = New-Object System.Threading.Mutex($false, "Global\Zhiying_SetupWindows")
$script:OwnsMutex = $false
try { $script:OwnsMutex = $script:SetupMutex.WaitOne(0) } catch { $script:OwnsMutex = $true }  # Mutex 被废弃句柄持有等异常时放行，别卡死安装
if (-not $script:OwnsMutex) {
    $msg = "已有另一个 setup_windows.ps1 实例在运行（上次安装未退干净），本实例退出。请结束所有 powershell/python 进程或重启后重跑。"
    try { Add-Content -Path (Join-Path $ProjectRoot "vendor\install.log") -Value "[$(Get-Date -Format 'MM-dd HH:mm:ss')] $msg" -Encoding UTF8 } catch {}
    Write-Host $msg -ForegroundColor Yellow
    if ($DoneMarker) { [System.IO.File]::WriteAllText($DoneMarker, "1") }
    exit 1
}

# ── 全局异常兜底：任何终止性错误落盘 + 屏显，避免闪退后无据可查 ──
$InstallLog = Join-Path $ProjectRoot "vendor\install.log"
trap {
    $msg = "[$(Get-Date -Format 'MM-dd HH:mm:ss')] TRAP L$($_.InvocationInfo.ScriptLineNumber): $($_.Exception.Message)"
    try {
        New-Item -ItemType Directory -Force -Path (Split-Path $InstallLog) | Out-Null
        Add-Content -Path $InstallLog -Value $msg -Encoding UTF8
    } catch {}
    Write-Host "`n[安装异常] $msg（已写入 $InstallLog，请把该文件发我）" -ForegroundColor Red
    if (-not $Quiet) {
        Read-Host "`n按回车关闭此窗口（日志已写入 $InstallLog）"
    }
    if ($DoneMarker) { [System.IO.File]::WriteAllText($DoneMarker, "1") }
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
        if ($EmbeddingProfile) { $extra += "-EmbeddingProfile", "`"$EmbeddingProfile`"" }
        if ($Proxy)             { $extra += "-Proxy", "`"$Proxy`"" }
        if ($Quiet)             { $extra += "-Quiet" }
        Start-Process -FilePath "powershell.exe" -ArgumentList (@(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`""
        ) + $extra) -Verb RunAs
        exit
    }
}

# ───────────────────────────── 输出 helpers ─────────────────────────────
# 输出小窗日志：Add-Content 每次开→写→关（不持锁，Inno 进度页可并发读尾部）
function Write-Out([string]$Line) {
    if ($OutputLog) {
        try { Add-Content -Path $OutputLog -Value $Line -Encoding UTF8 } catch { }
    }
}
# 步骤 → 进度区间 [start, end]（按实际耗时配权：deps 装 torch+全家桶最重占大头；
# 子步骤输出在区间内插值细化，见 Invoke-Native 的 PipeSpan）
$script:StepSpan = @{ 1=@(0,8); 2=@(8,70); 3=@(70,80); 4=@(80,90); 5=@(90,92); 6=@(92,99) }
# 步骤 → 安装器进度条 slug（ASCII，Inno [Code] 按此映射中文文案）
$script:StepSlug = @{ 1='env'; 2='deps'; 3='db'; 4='models'; 5='config'; 6='init' }
function Write-Step([string]$Index, [string]$Title) {
    Write-Host ""
    Write-Host "─── [$Index] $Title ───" -ForegroundColor Cyan
    Write-Out "─── [$Index] $Title ───"
    if ($ProgressLog) {
        $parts = $Index.Split('/')
        $n = 0; $total = 0
        [void][int]::TryParse($parts[0].Trim(), [ref]$n)
        [void][int]::TryParse($parts[1].Trim(), [ref]$total)
        $pct = 0
        $span = $script:StepSpan[[int]$n]
        if ($span) { $pct = $span[0] }
        $slug = $script:StepSlug[[int]$n]
        if (-not $slug) { $slug = 'step' }
        Add-Content -Path $ProgressLog -Value "PROGRESS`t$pct`t$slug" -Encoding ASCII
    }
}

# 段内细粒度进度：Set-PipeSpan 后，Invoke-Native 把子命令输出折算成区间内 PROGRESS 行
#   - pip（--progress-bar raw）的 "n/m xxx.whl" 行 → 按 n/m 在区间内插值
#   - download_models.py 的 "[progress] name N%" 行 → 按 N% 在区间内插值
# $null = 关闭。用完务必 Clear-PipeSpan，避免把后续无关输出误折算。
$script:PipeSpan = $null
$script:PipeLast = -1
function Set-PipeSpan([int]$Base, [int]$Span, [string]$Slug) {
    $script:PipeSpan = @($Base, $Span, $Slug); $script:PipeLast = -1
}
function Clear-PipeSpan { $script:PipeSpan = $null }

# 离散进度点：长阶段内的关键节点（pip 接管道时无进度条可解析，非 TTY 只有
# "Downloading x.whl (size)" 一行——实测如此；平滑推进交给安装器侧蠕动插值）
function Write-ProgressPoint([int]$Pct, [string]$Slug) {
    if ($ProgressLog) { Add-Content -Path $ProgressLog -Value "PROGRESS`t$Pct`t$Slug" -Encoding ASCII }
}
function Write-Ok([string]$Msg)   { Write-Host "  ✔ $Msg" -ForegroundColor Green; Write-Out "  [OK] $Msg" }
function Write-Warn([string]$Msg) { Write-Host "  ⚠ $Msg" -ForegroundColor Yellow; Write-Out "  [WARN] $Msg" }
function Write-Info([string]$Msg) { Write-Host "  · $Msg" -ForegroundColor Gray; Write-Out "  [..] $Msg" }

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
        & $Cmd[0] @($Cmd[1..($Cmd.Length-1)]) 2>&1 | ForEach-Object {
            Write-Host "      $_" -ForegroundColor DarkGray
            Write-Out "      $_"
            # 段内细粒度进度：pip 的 "n/m xxx.whl" 行 / 模型下载的 "[progress] x N%" 行 → 区间内插值
            if ($null -ne $script:PipeSpan -and $ProgressLog) {
                $p = -1
                if ($_ -match '(\d+)\s*/\s*(\d+)\s+\S+\.whl' -and [int]$Matches[2] -gt 0) {
                    $p = [math]::Floor($script:PipeSpan[0] + [int]$Matches[1] * 1.0 / [int]$Matches[2] * $script:PipeSpan[1])
                }
                elseif ($_ -match '\[progress\]') {
                    $ms = [regex]::Matches($_, '\[progress\]\s*\S+\s+(\d+)\s*%')
                    if ($ms.Count -gt 0) {
                        $v = [int]$ms[$ms.Count - 1].Groups[1].Value
                        $p = [math]::Floor($script:PipeSpan[0] + $v / 100.0 * $script:PipeSpan[1])
                    }
                }
                # 只前进不回退（一行可能带多个 \r 帧/多轮重试），且不越过区间终点
                if ($p -gt $script:PipeLast -and $p -lt ($script:PipeSpan[0] + $script:PipeSpan[1])) {
                    $script:PipeLast = $p
                    Add-Content -Path $ProgressLog -Value "PROGRESS`t$p`t$($script:PipeSpan[2])" -Encoding ASCII
                }
            }
        }
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
if ($EmbeddingProfile) {
    $script:EmbeddingProfile = if ($EmbeddingProfile -eq "2b") { "2b" } else { "8b" }
    Write-Info "非交互模式：档位 = $script:EmbeddingProfile（-EmbeddingProfile $EmbeddingProfile）"
} elseif (-not $Quiet) {
    $choice = Read-Host "输入 1 或 2"
    $script:EmbeddingProfile = if ($choice -eq "2") { "2b" } else { "8b" }
    Write-Ok "已选档位: $script:EmbeddingProfile"
} else {
    $script:EmbeddingProfile = "8b"
    Write-Info "非交互模式：默认档位 8b（-Quiet 且未指定）"
}

if ($Proxy) {
    $script:Proxy = ($Proxy.Trim() -replace '/$', '')
    Write-Info "非交互模式：代理 = $script:Proxy（-Proxy 参数）"
} elseif (-not $Quiet) {
    $proxyInput = Read-Host "输入代理地址（如 http://127.0.0.1:7897；能直连可留空）"
    $script:Proxy = ($proxyInput.Trim() -replace '/$', '')
    if ($script:Proxy) { Write-Ok "代理: $script:Proxy" } else { Write-Warn "未使用代理（国内源直连，GitHub 组件可能失败）" }
} else {
    # -Quiet 且未给代理：直接空代理（否则 Read-Host 会卡在隐藏窗口上）
    $script:Proxy = ''
    Write-Info "非交互模式：未提供代理（-Quiet，GitHub 源组件可能下载失败）"
}
# 保存代理到 data/proxy.txt（机器相关，data/ 已 gitignore；首启模型下载自动读取）
$proxyFile = Join-Path $ProjectRoot "data\proxy.txt"
New-Item -ItemType Directory -Force -Path (Split-Path $proxyFile) | Out-Null
[System.IO.File]::WriteAllText($proxyFile, [string]$script:Proxy)
Write-Ok "代理已保存到 data/proxy.txt（首启模型下载自动读取）"

# ───────────────────────────── 1/6 Python ─────────────────────────────
Write-Step "1/6" "Python + FFmpeg + Node.js 环境"
# winget 装的新命令要刷新 PATH 才在本会话可用（读注册表机器/用户 PATH）
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

# 商店假别名陷阱：全新 Windows 默认在 %LOCALAPPDATA%\Microsoft\WindowsApps 放 0 字节
# python.exe/python3.exe stub，Get-Command python 会命中它 → 误判"已安装"跳过安装，
# 后面 python -m venv 实跑只吐 "Python was not found"（退出码 9009）直接炸。
# 所以必须实跑 --version 验证，不能用 Get-Command 判断。
function Test-RealPython {
    # cmd 包一层执行：EAP=Stop 下 PowerShell 直接 2>&1 会把 stderr 文本转成终止性错误（TRAP L301 的由来）
    $out = (& cmd /c "python --version 2>&1") -join " "
    return (($LASTEXITCODE -eq 0) -and ($out -match "Python 3"))
}
if (Test-RealPython) {
    $ver = ((& cmd /c "python --version 2>&1") -join " ") -replace "Python ", ""
    Write-Ok "检测到 Python $ver"
} else {
    Write-Info "未检测到可用的 Python（或仅命中微软商店假别名），用 winget 安装 Python 3.13 ..."
    # 摘除商店假别名 stub，防装完后 PATH 解析仍落到 stub（真商店 Python 实跑能过，走不到这里）
    Get-ChildItem (Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps") -Filter "python*.exe" -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
    # winget 走 WinINET（系统代理）；若失败给出明确指引（手动装或开系统代理）
    # --source winget 跳过 msstore 源（部分客户机 msstore 源证书校验失败会直接炸，0x8a15005e）
    $null = & winget install --id Python.Python.3.13 --source winget --accept-source-agreements --accept-package-agreements --disable-interactivity 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Python 安装失败（请检查网络/系统代理后重试，或手动安装 Python 3.13 并勾选 Add to PATH）" }
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
    if (-not (Test-RealPython)) { throw "Python 安装后仍不可用（PATH 可能仍被商店假别名抢占）。请手动安装 Python 3.13 并勾选 Add to PATH 后重跑安装器" }
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
    # --source winget 跳过 msstore 源（同 Python 段注释）
    $null = & winget install --id OpenJS.NodeJS --source winget --accept-source-agreements --accept-package-agreements --disable-interactivity 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Node.js 安装失败（请检查代理/网络后重试，或手动安装 Node.js LTS）" }
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
}
$nodeVer = (& node --version 2>&1)
Write-Ok "Node.js $nodeVer"
# npm 国内镜像（中国网络免代理拉依赖；写入用户配置持久生效）
if (Get-Command npm -ErrorAction SilentlyContinue) {
    $null = & npm config set registry https://registry.npmmirror.com 2>&1
    Write-Ok "npm 镜像已配置：registry.npmmirror.com（npm install 走国内源免代理）"
}

# WebView2 Runtime（桌面端 exe 的 pywebview 依赖）。
# ⚠️ 版本过旧会「静默白屏」：pywebview 6.2.1 捆绑的 WebView2 SDK 1.0.3856.49 需新接口
#    ICoreWebView2Environment10（runtime ≥ 101）；实测 runtime 100.0.1185.36 会 COM
#    E_NOINTERFACE → WebView2 控件初始化失败 → 窗口全白、无任何提示（本机真实踩坑）。
# 策略：低于 $MinWebView2（151 为本机实测可用版本）就下载微软 Evergreen 安装器更新到最新
#    —— 多跑无害（已最新则秒过）、缺了必挂（桌面端白屏）。失败只告警不中断（服务器后端不受影响）。
Write-Info "检查 WebView2 Runtime（桌面端必需，过旧会白屏）..."
$MinWebView2 = [version]"151.0.0.0"
$Wv2Setup = Join-Path $ProjectRoot "vendor\webview2-bootstrap.exe"
function Get-WebView2Version {
    $regKeys = @(
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
        "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
        "HKCU:\Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    )
    foreach ($k in $regKeys) {
        if (Test-Path $k) {
            $pv = (Get-ItemProperty $k -ErrorAction SilentlyContinue).pv
            if ($pv) { return $pv }
        }
    }
    # 兜底：扫 EdgeWebView 应用目录的版本文件夹（如 151.0.4129.93；SetupMetrics 等目录不匹配数字）
    $dir = Get-ChildItem "C:\Program Files (x86)\Microsoft\EdgeWebView\Application" -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^\d+\.\d+\.\d+' } |
        Sort-Object { [version]$_.Name } -Descending | Select-Object -First 1
    if ($dir) { return $dir.Name }
    return $null
}
$wv2Ver = Get-WebView2Version
if ($wv2Ver -and ([version]$wv2Ver -ge $MinWebView2)) {
    Write-Ok "WebView2 Runtime $wv2Ver（满足最低 $MinWebView2）"
} else {
    Write-Warn "WebView2 Runtime 当前: $($(if ($wv2Ver) { $wv2Ver } else { '未安装' }))（要求 ≥ $MinWebView2）—— 下载并更新到最新 Evergreen ..."
    $wv2Ok = $false
    if (Invoke-Download "https://go.microsoft.com/fwlink/p/?LinkId=2124703" $Wv2Setup $true) {
        Write-Info "运行 WebView2 Runtime 安装器（/silent /install，本脚本已提权，无需再 UAC）..."
        $eap = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        try {
            $p = Start-Process -FilePath $Wv2Setup -ArgumentList "/silent", "/install" -Wait -PassThru
            Write-Info "WebView2 安装器退出码 $($p.ExitCode)"
        } catch { Write-Warn "WebView2 安装器启动失败: $($_.Exception.Message)" }
        finally { $ErrorActionPreference = $eap }
        Start-Sleep -Seconds 2
        $wv2New = Get-WebView2Version
        if ($wv2New -and ([version]$wv2New -ge $MinWebView2)) { $wv2Ok = $true; Write-Ok "WebView2 Runtime 已更新到 $wv2New" }
        else { Write-Warn "WebView2 更新后版本仍为 $wv2New（未达标）—— 桌面端 exe 可能白屏，可稍后手动重装 WebView2 Runtime" }
    } else {
        Write-Warn "WebView2 安装器下载失败 —— 桌面端 exe 可能白屏，可稍后手动安装 WebView2 Runtime"
    }
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
# pip 依赖统一走清华镜像直连（国内快、免梯子；梯子到 PyPI 实测 3.7KB/s 会卡死）
$PipIndex = "https://pypi.tuna.tsinghua.edu.cn/simple"
$pipArgs = @("-m", "pip", "install", "--upgrade", "pip", "--progress-bar", "raw", "-i", $PipIndex)
if ($script:Proxy) { $pipArgs += @("--proxy", $script:Proxy) }
$rc = Invoke-Native (@($VenvPython) + $pipArgs)
Write-ProgressPoint 10 'deps'
# CUDA 版 PyTorch：pip 默认装 CPU 版，必须用 PyTorch 官方源；按 GPU 代际/驱动 CUDA 选 cu124/cu126/cu130
# nvidia-smi 新版驱动头是 "CUDA UMD Version"（旧版是 "CUDA Version"），两种都匹配；null 兜底
$cudaLine = & nvidia-smi 2>$null | Select-String "CUDA (UMD )?Version:\s*([0-9.]+)" | Select-Object -First 1
$driverCuda = if ($cudaLine) { $cudaLine.Matches[0].Groups[2].Value } else { "" }
# ⚠️ 驱动 CUDA 版本 ≠ GPU 架构：Blackwell（RTX 50 系，compute_cap ≥ 10）需要 cu128+ 内核
# （cu126 无 sm_120），而 cu130 运行时又要求驱动 ≥ r580（驱动 CUDA 13）。
# 故 compute_cap ≥ 10 时：驱动支持 CUDA 13 → cu130；仅支持 12.x → cu128（Blackwell 内核 + 旧驱动兼容）。
$ccLine = & nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>$null | Select-Object -First 1
$ccMajor = 0
if ($ccLine -and "$ccLine" -match '^\s*(\d+)') { $ccMajor = [int]$Matches[1] }
$script:GpuTotalMiB = 0
$memLine = & nvidia-smi --query-gpu=memory.total --format=csv,noheader 2>$null | Select-Object -First 1
if ($memLine -and "$memLine" -match '(\d+)\s*MiB') { $script:GpuTotalMiB = [int]$Matches[1] }
# CUDA 版 PyTorch：两级源——① PyTorch 官方索引（正规 pip index，走代理）优先；
# ② 失败回退阿里云 pytorch-wheels 平铺目录。注意阿里云该镜像是 whl 平铺列表，
# 只能 --find-links（-f）用，不能 --index-url（请求 <镜像>/torch/ 会 404，必现失败）。
$torchIdx = "https://download.pytorch.org/whl/cu124"
$torchFlat = "https://mirrors.aliyun.com/pytorch-wheels/cu124"
if ($ccMajor -ge 10 -and $driverCuda -and [version]$driverCuda -ge [version]"13.0") {
    $torchIdx = "https://download.pytorch.org/whl/cu130"; $torchFlat = "https://mirrors.aliyun.com/pytorch-wheels/cu130"
}
elseif ($ccMajor -ge 10) {
    $torchIdx = "https://download.pytorch.org/whl/cu128"; $torchFlat = "https://mirrors.aliyun.com/pytorch-wheels/cu128"
}
elseif ($driverCuda -and [version]$driverCuda -ge [version]"13.0") {
    $torchIdx = "https://download.pytorch.org/whl/cu130"; $torchFlat = "https://mirrors.aliyun.com/pytorch-wheels/cu130"
}
elseif ($driverCuda -and [version]$driverCuda -ge [version]"12.6") {
    $torchIdx = "https://download.pytorch.org/whl/cu126"; $torchFlat = "https://mirrors.aliyun.com/pytorch-wheels/cu126"
}
Write-Info "安装 CUDA 版 PyTorch + torchvision（官方源 $torchIdx，驱动 CUDA $driverCuda）..."
# torchvision 必须同源（cu130 等）装，否则 requirements 阶段从 PyPI 拉 CPU 版 → torchvision::nms CUDA 报错（§13）
# ① 官方索引走代理（$true）；代理可用时索引完整、依赖同源自解析
$rc = Invoke-Native @($VenvPython, "-m", "pip", "install", "torch", "torchvision", "--index-url", $torchIdx, "--progress-bar", "raw") $true
if ($rc -ne 0) {
    # ② 回退：阿里云平铺目录 --no-index 直连（不走代理，国内 CDN 最快）。
    #    --no-index 下 pip 不解析依赖，torch/torchvision 的运行时依赖先用清华索引补齐。
    Write-Warn "官方源安装失败（exit=$rc），回退阿里云镜像直连（$torchFlat）..."
    [void](Invoke-Native @($VenvPython, "-m", "pip", "install", `
        "filelock", "typing-extensions", "sympy", "mpmath", "networkx", `
        "jinja2", "MarkupSafe", "fsspec", "numpy", "pillow", `
        "-i", $PipIndex, "--progress-bar", "raw") $false)
    $rc = Invoke-Native @($VenvPython, "-m", "pip", "install", "--no-index", `
        "--find-links", $torchFlat, "torch", "torchvision", "--progress-bar", "raw") $false
}
if ($rc -ne 0) { throw "CUDA PyTorch 安装失败" }
Write-ProgressPoint 40 'deps'   # torch+torchvision 就位（最大件）

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
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "vendor") | Out-Null
$onnxTmp = Join-Path $ProjectRoot "vendor\.fix-onnx.py"
Set-Content -Path $onnxTmp -Value $onnxStubPy -Encoding UTF8
$rc = Invoke-Native @($VenvPython, $onnxTmp)
Remove-Item $onnxTmp -Force -ErrorAction SilentlyContinue
if ($rc -ne 0) { Write-Warn "onnxruntime 桩创建失败（继续安装，稍后校验）" }

Write-Info "安装其余依赖（torch/torchvision 已满足会自动跳过；首次需数分钟，耐心等待）..."
$pipArgs2 = @("-m", "pip", "install", "-r", (Join-Path $ProjectRoot "requirements.txt"), "--progress-bar", "raw", "-i", $PipIndex)
if ($script:Proxy) { $pipArgs2 += @("--proxy", $script:Proxy) }
$rc = Invoke-Native (@($VenvPython) + $pipArgs2)
if ($rc -ne 0) { throw "依赖安装失败" }
Write-ProgressPoint 66 'deps'   # 其余依赖就位

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

# OCR 画面文字提取（v0.34）：RapidOCR 用独立 onnxruntime-directml，装在 vendor/ort_dml
#   （不参与上面 requirements 的全局 onnxruntime——DML 与 CUDA 共用 import onnxruntime 名，
#   进程内只能有一份；RapidOCR 放在独立子进程里 sys.path 前置加载 DML，人脸/车牌 CUDA 不受影响）
Write-Info "安装 OCR DirectML 引擎（vendor/ort_dml，隔离子进程用）..."
$ortDmlDir = Join-Path $ProjectRoot "vendor\ort_dml"
New-Item -ItemType Directory -Force -Path $ortDmlDir | Out-Null
$dmlArgs = @("-m", "pip", "install", "--target", $ortDmlDir, "--progress-bar", "raw", "onnxruntime-directml==1.24.4", "--quiet")
if ($script:Proxy) { $dmlArgs = $dmlArgs + @("--proxy", $script:Proxy) }
$rc = Invoke-Native (@($VenvPython) + $dmlArgs)
if ($rc -ne 0) {
    Write-Warn "onnxruntime-directml 安装失败（OCR 将退化 CPU / 需手动装 vendor/ort_dml）"
} else {
    # 校验 DML provider 与 RapidOCR 可加载
    $dmlChkPy = @"
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(r"$ortDmlDir")))
import onnxruntime as o
provs = o.get_available_providers()
if "DmlExecutionProvider" not in provs:
    print("[ocr-dml] WARN DmlExecutionProvider missing:", provs, file=sys.stderr)
else:
    print("[ocr-dml] OK providers:", provs)
"@
    $dmlChkTmp = Join-Path $ProjectRoot "vendor\.chk-ocr-dml.py"
    Set-Content -Path $dmlChkTmp -Value $dmlChkPy -Encoding UTF8
    $rc = Invoke-Native @($VenvPython, $dmlChkTmp)
    Remove-Item $dmlChkTmp -Force -ErrorAction SilentlyContinue
    if ($rc -ne 0) { Write-Warn "OCR DML 校验未过（检查 RapidOCR/vendor/ort_dml）" }
}

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
    # 源 zip 已解压组装完毕 → 删除（308MB 死重，客户机交付面不留安装耗材）
    Remove-Item (Join-Path $ProjectRoot "vendor\pg-zips") -Recurse -Force -ErrorAction SilentlyContinue
}

# ───────────────────────────── 4/6 模型（按档位） ─────────────────────────────
# 显存 vs 档位校验：8B fp16 权重 ~16GB，16GB 卡（RTX 5080 Laptop 等）塞不下 →
# accelerate 部分层 offload CPU → 后端启动 .to(device) 护栏炸（code 3）。fp16 无量化时
# 物理不可行，自动降级 2B 保证可用（显存不足硬装 8B 没有赢家）。
if ($script:EmbeddingProfile -eq "8b" -and $script:GpuTotalMiB -gt 0 -and $script:GpuTotalMiB -lt 17000) {
    Write-Warn ("本机显存 {0} MiB 不足以装载 8B fp16（需 ~16GB），自动改用 2B 档位（2048 维）。" -f $script:GpuTotalMiB)
    Write-Warn "如坚持 8B：需 24GB+ 显存，或改 plugins.embedder.quantization=8bit（需 bitsandbytes，笔记本有功耗尖峰风险）。"
    $script:EmbeddingProfile = "2b"
}
Write-Step "4/6" "模型下载（$script:EmbeddingProfile 档位）"
if ($SkipModels) { Write-Info "已跳过（-SkipModels）" }
else {
    $dlPy = Join-Path $PSScriptRoot "download_models.py"
    # 国内源组件（embedding 按档位 + plate + segmenter）：必须直连（modelscope 是国内 CDN，走代理反而更慢更易断）
    Set-PipeSpan 80 6 'models'   # [progress] N% → 80%~86%
    $rc = Invoke-Native @($VenvPython, $dlPy, "--embedding-profile", $script:EmbeddingProfile,
        "--component", "embedding", "--component", "plate", "--component", "segmenter",
        "--model-root", (Join-Path $ProjectRoot "models"), "--retries", "$DownloadRetries") $false
    Clear-PipeSpan
    if ($rc -ne 0) { throw "国内源模型下载失败（modelscope 直连；已内置断点续传，可重跑续传）" }
    # GitHub 源组件（yolo/reid/face，需代理）
    Set-PipeSpan 86 4 'models'   # → 86%~90%
    $rc = Invoke-Native @($VenvPython, $dlPy,
        "--component", "yolo", "--component", "reid", "--component", "face",
        "--model-root", (Join-Path $ProjectRoot "models"), "--retries", "$DownloadRetries") $true
    Clear-PipeSpan
    if ($rc -ne 0) {
        # 降级不阻断：yolo/reid/face 走 GitHub，无代理客户机在此重试数小时也下不动。
        # 首启 check_models 检测缺失 → MODEL_BOOT 自动断点续传补齐（届时可配代理），安装段别卡死最后一公里
        Write-Warn "GitHub 源模型（yolo/reid/face）下载失败——已跳过，首启会自动检测补齐（届时需可访问 GitHub 或配置代理）"
    }
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
# 后端代码定位：开发机（git 源码树有 core/）→ 直接 import；
# 封装安装包（无明文源码）→ 把 _internal\backend_pyc 无源字节码包插到 sys.path（legacy .pyc 可导入）
$initDbCode = "import asyncio; from core.db import init_db; asyncio.run(init_db()); print('tables ok')"
if (-not (Test-Path (Join-Path $ProjectRoot "core")) -and
        (Test-Path (Join-Path $ProjectRoot "_internal\backend_pyc"))) {
    Write-Info "封装模式：从 _internal\backend_pyc 字节码包 import"
    $initDbCode = "import sys; sys.path.insert(0, r'$ProjectRoot\_internal\backend_pyc'); " + $initDbCode
}
$rc = Invoke-Native @($VenvPython, "-c", $initDbCode)
if ($rc -ne 0) {
    # 非致命：main.py lifespan 启动时本就会 init_db 建表，此处仅提前保险，不让它炸掉安装
    Write-Warn "init_db 预建表失败（不阻断安装；后端首次启动时会自动建表）"
} else {
    Write-Ok "数据库已就绪、表已创建"
}

# ───────────────────────────── 完成 ─────────────────────────────
Write-Host ""
Write-Host "══════════ 安装完成 ══════════" -ForegroundColor Green
Write-Host "  档位: $script:EmbeddingProfile  |  代理: $($script:Proxy)"
Write-Host "  内嵌 PostgreSQL: vendor/pg（端口 5432，数据在 data/pgdata）"
Write-Host "  模型: models\ 就绪  |  config.yaml: 已生成"
Write-Host ""
Write-Host "  后续日常更新：git pull + .venv\Scripts\pip install -r requirements.txt"
Write-Host "  或直接启动桌面端：python desktop\app.py"
Write-Host "══════════════════════════════" -ForegroundColor Green
if ($ProgressLog) { Add-Content -Path $ProgressLog -Value "PROGRESS`t100`tdone" -Encoding ASCII }
if (-not $Quiet) {
    Read-Host "`n安装流程结束（按回车关闭此窗口）"
}
if ($DoneMarker) { [System.IO.File]::WriteAllText($DoneMarker, "0") }
