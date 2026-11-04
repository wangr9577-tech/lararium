@echo off
chcp 65001 >nul
title Kruskal Local Server
cd /d "%~dp0"

set "KRUSKAL_HOST=127.0.0.1"
set "KRUSKAL_LOCAL_NO_PASSWORD=1"
set "KRUSKAL_PORT=18080"
set "PYTHONIOENCODING=utf-8"

echo ===================================================
echo   正在启动 Kruskal 本地个人站点...
echo   本地访问地址: http://127.0.0.1:%KRUSKAL_PORT%
echo   数据存储目录: %~dp0backend\data
echo ===================================================

if exist "%~dp0venv\Scripts\python.exe" (
    set "PY_BIN=%~dp0venv\Scripts\python.exe"
) else (
    set "PY_BIN=python"
)

:: 启动并在 2 秒后自动打开默认浏览器
start /b "" cmd /c "timeout /t 2 /nobreak >nul && start http://127.0.0.1:%KRUSKAL_PORT%"

"%PY_BIN%" -m uvicorn app.main:app --app-dir backend --host %KRUSKAL_HOST% --port %KRUSKAL_PORT%
pause
