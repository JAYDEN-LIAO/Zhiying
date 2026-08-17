# ============================================================================
#  Zhiying 新机一键部署安装器（交互式）
#
#  用途：全新 Windows（可能只有 git、连 python 都没有）→ 双击本脚本 →
#        命令行窗口交互（选 2B/8B 模型 + 输代理）→ 自动托管：
#          Python → .venv+依赖 → 内嵌 PostgreSQL(vendor/pg) → 模型(按档位)
#          → config.yaml 生成 → 建表 → 校验
#        完成后无缝交给根目录 update.bat（前端构建 / 打 exe 的日常更新走它）。
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
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$DownloadRetries = 5

# ── 内嵌 postgres 下载源（本地 vendor/pg-zips 有则优先，避免依赖第三方在线） ──
$PgZipUrl      = "https://get.enterprisedb.com/postgresql/postgresql-17.5-1-windows-x64-binaries.zip"
$PgvectorUrl   = "https://github.com/andreiramani/pgvector_pgsql_windows/releases/download/0.8.6_17/vector.v0.8.6-pg17.zip"
$PgZipLocal    = Join-Path $ProjectRoot "vendor\pg-zips\postgresql-17.5-1-windows-x64-binaries.zip"
$PgvectorLocal = Join-Path $ProjectRoot "vendor\pg-zips\vector.v0.8.6-pg17.zip"

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
    & $Cmd[0] @($Cmd[1..($Cmd.Length-1)]) | ForEach-Object { Write-Host "      $_" -ForegroundColor DarkGray }
    $code = $LASTEXITCODE
    if ($envOld -ne $null) { $env:HTTP_PROXY, $env:HTTPS_PROXY = $envOld }
    return $code
}

# 下载文件（本地已存在则跳过；走代理）。
function Invoke-Download {
    param([string]$Url, [string]$Dest, [bool]$UseProxy)
    $DestDir = Split-Path -Parent $Dest
    New-Item -ItemType Directory -Force -Path $DestDir | Out-Null
    if (Test-Path $Dest) { Write-Ok "已存在，跳过: $(Split-Path -Leaf $Dest)"; return $true }
    Write-Info "下载 $(Split-Path -Leaf $Dest) ..."
    $proxyArgs = @()
    if ($UseProxy -and $script:Proxy) { $proxyArgs = @("-x", $script:Proxy) }
    for ($i = 0; $i -lt $DownloadRetries; $i++) {
        $rc = & curl.exe @proxyArgs -L -s -S -o $Dest --retry 3 $Url 2>$null
        if ($LASTEXITCODE -eq 0 -and (Test-Path $Dest) -and (Get-Item $Dest).Length -gt 0) {
            Write-Ok "下载完成 ($([math]::Round((Get-Item $Dest).Length/1MB,1)) MB)"
            return $true
        }
        Write-Warn "下载失败，重试 $($i+1)/$DownloadRetries ..."
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

# ───────────────────────────── 1/6 Python ─────────────────────────────
Write-Step "1/6" "Python 环境"
$py = Get-Command python -ErrorAction SilentlyContinue
if ($py) {
    $ver = (& python --version 2>&1) -replace "Python ", ""
    Write-Ok "检测到 Python $ver"
} else {
    Write-Info "未检测到 Python，用 winget 安装 Python 3.13 ..."
    $rc = & winget install --id Python.Python.3.13 --accept-source-agreements --accept-package-agreements --disable-interactivity
    if ($LASTEXITCODE -ne 0) { throw "Python 安装失败" }
    Write-Ok "Python 3.13 已安装（请关闭本窗口，用新的管理员窗口重跑本脚本以刷新 PATH）"
}

# ───────────────────────────── 2/6 .venv + 依赖 ─────────────────────────────
Write-Step "2/6" "虚拟环境 + 依赖"
if (-not (Test-Path $VenvPython)) {
    Write-Info "创建 .venv ..."
    $rc = Invoke-Native @("python", "-m", "venv", ".venv")
    if ($rc -ne 0) { throw ".venv 创建失败" }
} else {
    Write-Ok ".venv 已存在"
}
Write-Info "升级 pip + 安装依赖（走代理，较大，耐心等待）..."
$pipArgs = @("-m", "pip", "install", "--upgrade", "pip")
if ($script:Proxy) { $pipArgs += @("--proxy", $script:Proxy) }
$rc = Invoke-Native (@($VenvPython) + $pipArgs)
$pipArgs2 = @("-m", "pip", "install", "-r", (Join-Path $ProjectRoot "requirements.txt"))
if ($script:Proxy) { $pipArgs2 += @("--proxy", $script:Proxy) }
$rc = Invoke-Native (@($VenvPython) + $pipArgs2)
if ($rc -ne 0) { throw "依赖安装失败" }

# ───────────────────────────── 3/6 内嵌 PostgreSQL ─────────────────────────────
Write-Step "3/6" "内嵌 PostgreSQL（vendor/pg）"
if ($SkipPg) { Write-Info "已跳过（-SkipPg）" }
else {
    $pgDir = Join-Path $ProjectRoot "vendor\pg"
    if (Test-Path (Join-Path $pgDir "bin\pg_ctl.exe")) {
        Write-Ok "vendor/pg 已存在"
    } else {
        # 本地 vendor/pg-zips 优先，否则在线下载
        $pgZip = if (Test-Path $PgZipLocal) { $PgZipLocal } else { $null }
        $vecZip = if (Test-Path $PgvectorLocal) { $PgvectorLocal } else { $null }
        if ($pgZip) { Write-Ok "本地已有 postgres zip" } else {
            if (-not (Invoke-Download $PgZipUrl (Join-Path $ProjectRoot "vendor\pg-zips\postgresql.zip") $true)) { throw "postgres zip 下载失败" }
            $pgZip = Join-Path $ProjectRoot "vendor\pg-zips\postgresql.zip"
        }
        if ($vecZip) { Write-Ok "本地已有 pgvector zip" } else {
            if (-not (Invoke-Download $PgvectorUrl (Join-Path $ProjectRoot "vendor\pg-zips\pgvector.zip") $true)) { throw "pgvector zip 下载失败" }
            $vecZip = Join-Path $ProjectRoot "vendor\pg-zips\pgvector.zip"
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
    # 国内源组件（embedding 按档位 + plate + segmenter）
    $rc = Invoke-Native @($VenvPython, $dlPy, "--embedding-profile", $script:EmbeddingProfile,
        "--component", "embedding", "--component", "plate", "--component", "segmenter",
        "--model-root", (Join-Path $ProjectRoot "models"), "--retries", "$DownloadRetries") $false
    if ($rc -ne 0) {
        Write-Warn "国内源下载失败，带代理重试..."
        $rc = Invoke-Native @($VenvPython, $dlPy, "--embedding-profile", $script:EmbeddingProfile,
            "--component", "embedding", "--component", "plate", "--component", "segmenter",
            "--model-root", (Join-Path $ProjectRoot "models"), "--retries", "$DownloadRetries") $true
    }
    if ($rc -ne 0) { throw "国内源模型下载失败" }
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
Write-Host "  后续日常更新/启动：双击根目录 update.bat（git pull + 依赖 + 前端 + 打 exe）"
Write-Host "  或直接启动桌面端：python desktop\app.py"
Write-Host "══════════════════════════════" -ForegroundColor Green
