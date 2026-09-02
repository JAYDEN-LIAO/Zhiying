# ═══════════════════════════════════════════════════════════
#  deploy/stop_runtime.ps1 — 卸载前停止运行中的运行时进程
#
#  用途：Inno 安装器 [UninstallRun] 调用（卸载前停桌面壳 + 内嵌 postgres），
#        避免正在运行的进程锁住 {app} 下的 exe/_internal DLL/数据库文件，
#        导致 Inno 删除失败或残留。
#  容忍全部错误（$ErrorActionPreference=SilentlyContinue + 退出 0）——
#        停服失败不应中断卸载流程（残留由用户重启机器后手动清）。
# ═══════════════════════════════════════════════════════════
param([string]$Root)

$ErrorActionPreference = "SilentlyContinue"
if (-not $Root) { $Root = Split-Path -Parent $PSScriptRoot }

# 1) 桌面壳（pywebview 主进程）
Get-Process -Name "智影桌面端" -ErrorAction SilentlyContinue | Stop-Process -Force

# 2) 内嵌 PostgreSQL（仅本数据目录；绝不误杀其它 postgres）
$pgCtl  = Join-Path $Root "vendor\pg\bin\pg_ctl.exe"
$pgData = Join-Path $Root "data\pgdata"
if ((Test-Path $pgCtl) -and (Test-Path (Join-Path $pgData "PG_VERSION"))) {
    & $pgCtl -D $pgData stop -m fast 2>$null
    Start-Sleep -Milliseconds 500
    # 未停干净升级 immediate 强停（卸载场景宁重启恢复也不带锁删除）
    $still = Get-CimInstance Win32_Process -Filter "Name = 'postgres.exe'" -ErrorAction SilentlyContinue |
        Where-Object { ($_.CommandLine -replace '\\', '/') -like ("*" + $pgData.Replace('\', '/') + "*") }
    if ($still) {
        & $pgCtl -D $pgData stop -m immediate 2>$null
    }
}

exit 0
