<#
Cerno Windows 后端启动脚本
═══════════════════════════════════════════════════════════════
- 校验必要模型（yolo 必装；embedding 视部署配置而定）
- 确保 Docker 数据库容器 healthy
- 设置 CERNO_CONFIG / POSTGRES_URI
- 启动 uvicorn，轮询 /health 直到就绪

用法：
  .\deploy\start_windows.ps1
  .\deploy\start_windows.ps1 -NoVerify      # 跳过模型校验
  .\deploy\start_windows.ps1 -NoDb          # 不自动拉起数据库
  .\deploy\start_windows.ps1 -HealthTimeout 300
#>

param(
    [switch]$NoVerify,
    [switch]$NoDb,
    [int]$HealthTimeout = 180
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ConfigFile = Join-Path $ProjectRoot "config\config.windows.yaml"
$LogFile = Join-Path $ProjectRoot "data\backend.log"

if (-not (Test-Path $VenvPython)) {
    throw "虚拟环境不存在，请先运行 .\deploy\setup_windows.ps1。"
}
Set-Location $ProjectRoot
New-Item -ItemType Directory -Force (Join-Path $ProjectRoot "data") | Out-Null

function Write-Info([string]$Message) { Write-Host "  $Message" -ForegroundColor Gray }
function Write-Ok([string]$Message)   { Write-Host "  [ok] $Message" -ForegroundColor Green }
function Write-Warn([string]$Message) { Write-Host "  [warn] $Message" -ForegroundColor Yellow }
function Write-Fail([string]$Message) { Write-Host "  [error] $Message" -ForegroundColor Red }

function Get-DotEnvValue([string]$Key) {
    $envFile = Join-Path $ProjectRoot ".env"
    if (-not (Test-Path $envFile)) { return $null }
    foreach ($line in (Get-Content $envFile)) {
        $line = $line.Trim()
        if (-not $line -or $line.StartsWith("#") -or $line -notmatch "=") { continue }
        $k, $v = $line.Split("=", 2)
        if ($k.Trim() -eq $Key) { return $v.Trim().Trim('"').Trim("'") }
    }
    return $null
}

function Get-EmbedderEnabled {
    # 从部署配置读取 embedder 是否启用：输出 "0"=启用 / "1"=禁用 / "null"=无配置
    if (-not (Test-Path $ConfigFile)) { return "null" }
    $code = "import yaml,sys; c=yaml.safe_load(open(sys.argv[1],encoding='utf-8')); b=(c.get('plugins',{}).get('embedder') or {}).get('backend'); print('0' if b else '1')"
    $out = & $VenvPython -c $code $ConfigFile 2>$null
    if ($LASTEXITCODE -ne 0 -or $null -eq $out) { return "null" }
    return ([string]$out).Trim()
}

# ── 1. 模型校验 ──
Write-Host "Cerno 后端启动" -ForegroundColor Cyan
$embedderOn = Get-EmbedderEnabled
if (-not (Test-Path $ConfigFile)) {
    Write-Warn "未找到 $ConfigFile，将使用默认 config/config.yaml（可能不匹配部署预期）。"
}

if ($NoVerify) {
    Write-Info "已跳过模型校验（-NoVerify）。"
} else {
    $required = @("yolo")
    if ($embedderOn -eq "0") { $required += "embedding" }
    $verifyArgs = @()
    foreach ($c in $required) { $verifyArgs += "--component"; $verifyArgs += $c }
    $verifyArgs += "--model-root"; $verifyArgs += (Join-Path $ProjectRoot "models")
    $verifyArgs += "--verify-only"

    Write-Info "校验必需模型：$($required -join ' / ')"
    & $VenvPython (Join-Path $PSScriptRoot "download_models.py") @verifyArgs
    if ($LASTEXITCODE -ne 0) {
        throw "必需模型不完整。请运行 .\deploy\setup_windows.ps1 补齐（可断点续传）。"
    }

    # 可选组件只告警，不阻塞
    $optionalArgs = @("--component", "face", "--component", "plate",
                      "--model-root", (Join-Path $ProjectRoot "models"), "--verify-only")
    & $VenvPython (Join-Path $PSScriptRoot "download_models.py") @optionalArgs 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "存在未就绪的可选组件（face/plate）。运行 setup 可补齐。"
    }
}

# ── 2. 数据库 ──
if (-not $NoDb) {
    & docker compose -f (Join-Path $ProjectRoot "docker-compose.yaml") up -d db
    if ($LASTEXITCODE -ne 0) { throw "数据库容器启动失败。" }
    $deadline = (Get-Date).AddSeconds($HealthTimeout)
    $checked = 0
    do {
        $status = (& docker inspect --format '{{.State.Health.Status}}' cerno_postgres 2>$null | Select-Object -First 1)
        if ($status -eq "healthy") { Write-Ok "数据库容器 healthy"; break }
        if ($checked -eq 0) { Write-Info "等待数据库容器就绪 ..." }
        $checked++
        Start-Sleep -Seconds 3
        if ((Get-Date) -ge $deadline) {
            throw "数据库容器未在 $HealthTimeout 秒内就绪。排查：docker logs cerno_postgres"
        }
    } while ($true)
}

# ── 3. 环境变量 ──
if (-not $env:POSTGRES_URI) {
    $dotEnv = Get-DotEnvValue "POSTGRES_URI"
    if ($dotEnv) {
        $env:POSTGRES_URI = $dotEnv
        Write-Info "使用 .env 中的 POSTGRES_URI"
    } else {
        $env:POSTGRES_URI = "postgresql+asyncpg://cerno:cerno@localhost:5432/cerno"
        Write-Info "POSTGRES_URI 未设置，使用默认本机 docker 数据库"
    }
}
if (Test-Path $ConfigFile) {
    $env:CERNO_CONFIG = $ConfigFile
    Write-Info "部署配置：$ConfigFile"
}

# ── 4. 启动后端 ──
Write-Host ""
Write-Host "  backend: http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "  health : http://127.0.0.1:8000/health" -ForegroundColor Green
Write-Host "  log    : $LogFile" -ForegroundColor DarkGray
Write-Host ""

$startInfo = New-Object System.Diagnostics.ProcessStartInfo
$startInfo.FileName = $VenvPython
$startInfo.Arguments = "-m uvicorn main:app --host 127.0.0.1 --port 8000"
$startInfo.WorkingDirectory = $ProjectRoot
$startInfo.UseShellExecute = $false
$startInfo.RedirectStandardOutput = $true
# stderr 不重定向 → 直出到控制台（实时可见错误），避免管道缓冲阻塞子进程
$proc = [System.Diagnostics.Process]::Start($startInfo)

# 边启动边把日志写到文件，供诊断
$job = Start-Job -ScriptBlock {
    param($p, $logPath)
    $sw = [System.IO.StreamWriter]::new($logPath, $true)
    try {
        while (-not $p.HasExited) {
            $line = $p.StandardOutput.ReadLine()
            if ($null -ne $line) { $sw.WriteLine($line); $sw.Flush() }
        }
    } catch { }
    # 进程退出后清空剩余输出
    while ($true) {
        $line = $p.StandardOutput.ReadLine()
        if ($null -eq $line) { break }
        $sw.WriteLine($line); $sw.Flush()
    }
    $sw.Dispose()
} -ArgumentList $proc, $LogFile

# ── 5. 健康检查轮询 ──
$deadline = (Get-Date).AddSeconds($HealthTimeout)
$ready = $false
while ((Get-Date) -lt $deadline) {
    if ($proc.HasExited) {
        Write-Fail "后端进程异常退出（exit=$($proc.ExitCode)）。"
        throw "后端启动失败，详见 $LogFile"
    }
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -TimeoutSec 3 -UseBasicParsing
        if ($r.StatusCode -eq 200) {
            Write-Ok "后端就绪：$($r.Content)"
            $ready = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 2
    }
}
if (-not $ready) {
    Write-Warn "后端未在 $HealthTimeout 秒内通过健康检查。查看日志：$LogFile"
}

# 前台挂住，Ctrl+C 退出时关闭后端
try {
    $proc.WaitForExit()
} finally {
    if (-not $proc.HasExited) { $proc.Kill() }
    Stop-Job $job -ErrorAction SilentlyContinue
    Remove-Job $job -Force -ErrorAction SilentlyContinue
}
