@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem DSH Pet 素材定制插帧工具 —— Windows 图形界面启动
rem 用 pythonw 启动，不会弹出黑色命令行窗口。

set "PYW="
where pyw >nul 2>nul && set "PYW=pyw"
if not defined PYW where pythonw >nul 2>nul && set "PYW=pythonw"

if defined PYW (
    start "" %PYW% "gui.py"
    exit /b 0
)

rem 没找到 pythonw 就退回普通 python（会带一个黑框，但功能一样）
set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY where python >nul 2>nul && set "PY=python"

if not defined PY (
    echo ============================================================
    echo   没找到 Python
    echo ============================================================
    echo.
    echo 请先去 https://www.python.org/downloads/ 装一个 Python 3.8 以上，
    echo 安装时记得勾选 "Add Python to PATH"，装完重开这个窗口。
    echo.
    pause
    exit /b 1
)

%PY% "gui.py"
if errorlevel 1 (
    echo.
    echo 界面没能启动，上面有原因。
    pause
)
exit /b %errorlevel%
