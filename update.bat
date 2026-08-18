@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
cd /d "%~dp0"

echo ==================================================
echo   智影桌面端 自动更新
echo   %date% %time%
echo ==================================================
echo.

echo [1/5] git pull（读取 install.bat 保存的代理，缺失则手动输入）...
set "PROXY="
if exist "data\proxy.txt" set /p PROXY=<data\proxy.txt
if "%PROXY%"=="" (
    echo   未找到已保存的代理（data\proxy.txt），请手动输入：
    set /p PROXY="  代理地址（如 http://127.0.0.1:7897，可留空）: "
    if not "!PROXY!"=="" (echo !PROXY!)>data\proxy.txt
)
REM 归一化：缺 http:// 前缀则补上（git http.proxy 需要 URL）
if not "%PROXY%"=="" (
    if /i not "%PROXY:~0,7%"=="http://" (
        if /i not "%PROXY:~0,8%"=="https://" (
            set "PROXY=http://%PROXY%"
        )
    )
)
if "%PROXY%"=="" (
    echo   未使用代理，git 直连...
    git pull
) else (
    echo   代理: %PROXY%
    git -c http.proxy=%PROXY% pull
)
if errorlevel 1 (
    echo.
    echo [错误] git pull 失败，请检查代理/网络后重试
    pause
    exit /b 1
)

echo.
echo [2/5] 安装桌面壳依赖（desktop\requirements.txt，含 psutil）...
.venv\Scripts\pip.exe install -r desktop\requirements.txt
if errorlevel 1 echo [警告] pip 依赖安装失败，继续后续步骤

echo.
echo [3/5] npm install（frontend-desktop）...
pushd frontend-desktop
call npm install
if errorlevel 1 (
    echo.
    echo [错误] npm install 失败
    popd
    pause
    exit /b 1
)

echo.
echo [4/5] npm run build（重建桌面前端 dist，gitignore 不入库必须本地构建）...
call npm run build
if errorlevel 1 (
    echo.
    echo [错误] 前端构建失败，见上方报错
    popd
    pause
    exit /b 1
)
popd

echo.
echo [5/5] 重打桌面壳 exe（desktop\build_exe.ps1 -Deploy）...
powershell -ExecutionPolicy Bypass -File desktop\build_exe.ps1 -Deploy
if errorlevel 1 (
    echo.
    echo [错误] exe 构建失败，见上方报错
    pause
    exit /b 1
)

echo.
echo ==================================================
echo   全部完成！双击「智影桌面端.exe」即可启动
echo ==================================================
pause
