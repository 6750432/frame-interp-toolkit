@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo   DSH Pet 素材定制插帧工具（Windows）
echo ============================================================
echo.

rem 找一个能用的 Python。优先 py 启动器，其次 PATH 里的 python。
set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo [X] 没找到 Python。请先装 Python 3.8 以上：
    echo      https://www.python.org/downloads/
    echo      安装时记得勾选 "Add Python to PATH"
    echo.
    pause
    exit /b 1
)

"%PY%" "插帧.py" %*
set rc=%errorlevel%

echo.
if not "%rc%"=="0" echo ^(退出码 %rc%，上面有原因^)
echo.
pause
exit /b %rc%
