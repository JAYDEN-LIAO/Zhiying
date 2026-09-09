@echo off
REM ============================================================
REM  智影 · 一键出货（双击执行，四步全选）
REM  全路径：桌面前端 dist → 壳 exe + backend_pyc → dist\智影桌面端\
REM        → build 安装包 → build\green 打包材料目录（含 zhiying.iss）
REM  发版前置 ./bump（版本号自动取 core/version.py）
REM ============================================================
cd /d "%~dp0"

echo == 1/4 构建桌面前端 dist ...
cd frontend-desktop && call npm run build
if errorlevel 1 ( echo [X] npm build 失败 & pause & exit /b 1 )
cd ..

echo.
echo == 2/4 打包壳 exe + backend_pyc（dist\智影桌面端\）...
powershell -ExecutionPolicy Bypass -File desktop/build_exe.ps1
if errorlevel 1 ( echo [X] exe 构建失败 & pause & exit /b 1 )

echo.
echo == 3/4 编译安装包（build\视频快速智能检索平台 Ver *.exe）...
powershell -ExecutionPolicy Bypass -File desktop/build_installer.ps1
if errorlevel 1 ( echo [X] 安装包编译失败 & pause & exit /b 1 )

echo.
echo == 4/4 装配打包材料目录（build\green，含 zhiying.iss）...
powershell -ExecutionPolicy Bypass -File desktop/make_green.ps1
if errorlevel 1 ( echo [X] 材料装配失败 & pause & exit /b 1 )

echo.
echo == 清理构建中间产物（backend_pyc / build_exe，下次构建自动重建）...
rd /s /q "build\backend_pyc" 2>nul
rd /s /q "build\build_exe" 2>nul

echo.
echo [OK] 完成。build 下安装包：
dir /b /o-d "build/*.exe" 2>nul
echo.
pause
