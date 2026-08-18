# ═══════════════════════════════════════════════════════════
#  智影桌面端 · Windows EXE 构建脚本（PyInstaller, onedir）
#  用法（Windows，项目根）：
#    powershell -ExecutionPolicy Bypass -File desktop/build_exe.ps1            # 只构建到 dist\智影桌面端\
#    powershell -ExecutionPolicy Bypass -File desktop/build_exe.ps1 -Deploy    # 构建 + 自动部署到项目根（推荐）
#  -Deploy：构建后自动把 exe + _internal\ 拷到项目根（覆盖旧版），双击即用
#  产物：dist\智影桌面端\智影桌面端.exe
# ═══════════════════════════════════════════════════════════
param(
    [switch]$Deploy   # 构建后自动部署到项目根
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
Write-Host "项目根: $Root"

$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    throw "未找到 .venv\Scripts\python.exe —— 先跑 deploy/setup_windows.ps1（或手动建 .venv）"
}

# PyInstaller 版本钉：默认装最新。若遇 python313.dll 加载失败且排除杀软后仍复现，
# 改这里回退到之前能成功构建的版本（例：'pyinstaller==6.11.1'），避免每次构建静默升级导致 _internal 布局漂移。
$PyInstallerPin = ""
if ($PyInstallerPin) {
    & $Py -m pip install --quiet $PyInstallerPin
} else {
    & $Py -m pip install --quiet pyinstaller
}

Write-Host "构建 智影桌面端.exe …"
# 先编译后端字节码包（build/backend_pyc，封装模式客户端无明文源码），再由 spec 打进 _internal
& $Py deploy\build_backend_pyc.py
if ($LASTEXITCODE -ne 0) { throw "后端字节码打包失败 (exit=$LASTEXITCODE)" }

& $Py -m PyInstaller desktop\build_exe.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败 (exit=$LASTEXITCODE)，看上方输出" }

# ── 构建产物自检：dist 里必须存在 exe + python313.dll（否则说明被杀软隔离/构建异常，别再往下拷）──
$distExe = Join-Path $Root "dist\智影桌面端\智影桌面端.exe"
$distDll = Join-Path $Root "dist\智影桌面端\_internal\python313.dll"
if (-not (Test-Path $distExe)) { throw "构建产物缺失: $distExe（构建异常，看上方 PyInstaller 输出）" }
if (-not (Test-Path $distDll)) {
    throw "构建产物缺少 _internal\python313.dll —— 几乎可以肯定是杀毒软件实时防护把它隔离了。请到「Windows 安全中心 → 病毒和威胁防护 → 保护历史记录」还原 python313.dll，并把 '$Root' 加入「排除项」，然后重跑本脚本。"
}

Write-Host "✅ 构建完成: $distExe"
if ($Deploy) {
    Write-Host "部署到项目根 …"
    $dst = Join-Path $Root "智影桌面端.exe"
    $srcInternal = Join-Path $Root "dist\智影桌面端\_internal"
    $dstInternal = Join-Path $Root "_internal"

    # ── 0) 先关掉正在运行的桌面壳 + 遗留的后端子进程 —— 否则 exe / _internal 里已加载的
    #    DLL（python313.dll / MSVCP140.dll）被进程锁住，Remove-Item 删不掉 → 旧目录残留 →
    #    Copy-Item 把新 _internal 整层嵌进旧目录（_internal\_internal\），自检就找不到顶层
    #    python313.dll —— 这正是过去被误判成「杀毒软件删除了」的真实原因。 ──
    $runningShell = Get-Process -Name "智影桌面端" -ErrorAction SilentlyContinue
    if ($runningShell) {
        Write-Host ("  关闭运行中的桌面壳（PID {0}）…" -f (($runningShell | ForEach-Object Id) -join ", "))
        $runningShell | Stop-Process -Force -ErrorAction SilentlyContinue
    }
    # 壳被强杀后，其后端子进程（.venv python -m desktop.backend_child）可能残留并占住
    # _internal 里 DLL 的句柄（实测 backend_child 会加载 _internal\MSVCP140.dll）——一并关掉。
    $leakedBackend = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "desktop\.backend_child" }
    if ($leakedBackend) {
        Write-Host ("  关闭遗留后端子进程（PID {0}）…" -f (($leakedBackend | ForEach-Object ProcessId) -join ", "))
        $leakedBackend | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    }
    if ($runningShell -or $leakedBackend) { Start-Sleep -Milliseconds 1000 }

    # ── 0.5) 停掉内嵌 postgres（常驻 daemon）：postgres 不依赖 _internal 目录句柄，
    #    但它从旧 _internal 加载了 MSVC 运行库（vendor\pg\bin 不自带 MSVCP140/VCRUNTIME，
    #    postgres 兜底从 PATH 里的 _internal 加载），进程活着就锁住那 3 个 DLL →
    #    壳和 backend_child 杀干净后 _internal 仍删不掉。必须一并 pg_ctl stop。 ──
    $pgCtl = Join-Path $Root "vendor\pg\bin\pg_ctl.exe"
    $pgData = Join-Path $Root "data\pgdata"
    $pgDataFwd = $pgData.Replace('\', '/')  # postgres 命令行里 -D 是正斜杠路径
    if ((Test-Path $pgCtl) -and (Test-Path (Join-Path $pgData "PG_VERSION"))) {
        Write-Host "  停止内嵌 postgres（释放 _internal 运行时 DLL）…"
        $prevEAP = $ErrorActionPreference
        try {
            # 关键：临时把 ErrorActionPreference 降到 Continue。PS 5.1 在 Stop 下会把原生命令
            # 的 stderr 升成 NativeCommandError 直接中止脚本（实测 2>&1 / 2>$null 都拦不住），
            # 而 pg_ctl 在 postgres「没在跑」时必然向 stderr 报错退出 1 —— 两种状态对部署等价
            # （该停/已停），都不该中断。Continue 下 stderr 只是非致命错误，正常静默丢弃。
            $ErrorActionPreference = 'Continue'
            & $pgCtl -D $pgData stop -m fast 2>$null
            $null = $LASTEXITCODE
            # 等 postmaster（命令行带 -D pgdata 的主进程）真正退出，DLL 句柄释放后 _internal 才删得掉。
            # forkchild 不匹配 -D 也不怕：它随主进程退出。轮询最多 ~6s。
            $pgAlive = @()
            for ($i = 0; $i -lt 12; $i++) {
                $pgAlive = @(Get-CimInstance Win32_Process -Filter "Name = 'postgres.exe'" -ErrorAction SilentlyContinue |
                    Where-Object { ($_.CommandLine -replace '\\', '/') -like "*$pgDataFwd*" })
                if ($pgAlive.Count -eq 0) { break }
                Start-Sleep -Milliseconds 500
            }
            # pg_ctl 停不干净 → 升级 immediate 强停（宁可下次启动做崩溃恢复，也不带着锁删 _internal）
            if ($pgAlive.Count -gt 0) {
                Write-Host "  pg_ctl 未能在 6s 内停掉 postgres，升级 immediate 强停…"
                & $pgCtl -D $pgData stop -m immediate 2>$null
                $null = $LASTEXITCODE
                Start-Sleep -Milliseconds 1000
            }
            # 极端残留（进程失联/PID 文件丢失等）→ 按 vendor/pg 定位整个嵌入式集群（含 forkchild）硬杀
            $pgRemain = @(Get-CimInstance Win32_Process -Filter "Name = 'postgres.exe'" -ErrorAction SilentlyContinue |
                Where-Object { ($_.CommandLine -replace '\\', '/') -like "*vendor/pg*" })
            if ($pgRemain.Count -gt 0) {
                Write-Host ("  强制结束残留 postgres（PID {0}）…" -f (($pgRemain | ForEach-Object ProcessId) -join ", "))
                $pgRemain | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
                Start-Sleep -Milliseconds 800
            }
        } catch {
            # 本步骤任何异常都不该炸掉部署 —— 真正的兜底在校验 _internal 是否删得掉那一步
            Write-Host "  停止 postgres 步骤异常（忽略，_internal 删除环节仍会兜底校验）：$($_.Exception.Message)"
        } finally {
            $ErrorActionPreference = $prevEAP
        }
    }

    # ── 1) 清旧 exe + _internal：删除重试 3 次（锁往往极短暂），仍删不掉就明确报错，
    #    绝不带着残留继续拷贝（残留正是嵌套的来源）。 ──
    Remove-Item -Recurse -Force $dst -ErrorAction SilentlyContinue
    if (Test-Path $dstInternal) {
        for ($i = 0; $i -lt 3; $i++) {
            Remove-Item -Recurse -Force $dstInternal -ErrorAction SilentlyContinue
            if (-not (Test-Path $dstInternal)) { break }
            Start-Sleep -Milliseconds 500
        }
        if (Test-Path $dstInternal) {
            throw "旧 _internal 目录删不掉（目录内文件仍被某进程占用）。请关闭智影桌面端及残留 backend_child 进程后重跑。残留: $dstInternal"
        }
    }

    # ── 2) 拷贝 exe + _internal：用 $src\* 拷「内容」而非把整个文件夹塞进目标 ——
    #    目标即便残留也绝不嵌套（已用临时目录实测：两种写法结果相反）。 ──
    Copy-Item -Force $distExe $dst
    New-Item -ItemType Directory -Force -Path $dstInternal | Out-Null
    Copy-Item -Path (Join-Path $srcInternal '*') -Destination $dstInternal -Recurse -Force

    # ── 3) 部署后自检：python313.dll 必须落在顶层 _internal\ ──
    if (-not (Test-Path (Join-Path $dstInternal "python313.dll"))) {
        if (Test-Path (Join-Path $dstInternal "_internal\python313.dll")) {
            throw "python313.dll 被拷进了嵌套目录 _internal\_internal\ —— 旧 _internal 未清空 + Copy-Item 整层嵌套所致，属脚本问题而非杀软。新版已修复拷贝逻辑，请直接重跑本脚本。"
        }
        throw "部署后 _internal\python313.dll 缺失（dist 自检通过，可排除构建产物问题）。多为旧 _internal 清理失败或文件被占用——请关闭智影桌面端 / backend_child 进程后重跑；仍复现再检查 '$Root' 是否被杀软实时防护盯上。"
    }
    Write-Host "✅ 已部署: $dst（双击即用，自检通过）"
} else {
    Write-Host "分发 = dist\智影桌面端\ 文件夹 + 项目代码目录"
    Write-Host "（想一步到位加 -Deploy：自动把 exe + _internal 拷到项目根）"
}
