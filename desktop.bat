@echo off
REM ============================================================
REM  智影视频分析 · 桌面启动器（Windows 入口）
REM  用法: desktop.bat           启动桌面端（GUI）
REM        desktop.bat --check   先做环境自检（模型/端口/Docker/config）
REM ============================================================
cd /d "%~dp0"

set PYTHON=python
if exist ".venv\Scripts\python.exe" set PYTHON="%CD%\.venv\Scripts\python.exe"

if "%1"=="--check" (
  %PYTHON% desktop\app.py --check %2 %3 %4
  goto :end
)

%PYTHON% desktop\app.py %*
:end
if errorlevel 1 pause
