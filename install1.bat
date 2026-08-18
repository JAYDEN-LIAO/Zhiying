@echo off
chcp 65001 >nul
rem ============================================================
rem  智影 install1 — 新机首次一键部署（双击运行）
rem  全新 Windows → 双击本文件 → 命令行窗口交互（选 2B/8B + 代理）
rem  → 自动装 Python/Node/FFmpeg/依赖/模型/内嵌 PostgreSQL/config/建表
rem  → 之后云端有更新 → 双击 install2.bat（一键更新+打 exe）
rem ============================================================
cd /d "%~dp0"
echo 正在启动 智影 install1 一键安装器（首次安装）...
powershell -NoProfile -ExecutionPolicy Bypass -File "deploy\setup_windows.ps1"
if errorlevel 1 (
    echo.
    echo 安装未完成，请查看上方日志；或带 -SkipModels -SkipPg 分段调试。
)
pause
