@echo off
rem ============================================================
rem  智影 新机一键部署安装器（双击运行）
rem  全新 Windows → 双击本文件 → 命令行窗口交互（选 2B/8B + 代理）
rem  → 自动装 Python/依赖/模型/内嵌 PostgreSQL/config/建表
rem  → 完成后交给 update.bat（日常更新/启动）
rem ============================================================
cd /d "%~dp0"
echo 正在启动智影一键安装器...
powershell -NoProfile -ExecutionPolicy Bypass -File "deploy\setup_windows.ps1"
if errorlevel 1 (
    echo.
    echo 安装未完成，请查看上方日志；或带 -SkipModels -SkipPg 分段调试。
)
pause
