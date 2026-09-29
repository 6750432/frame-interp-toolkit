@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo   DSH Pet 插帧工具 - 快速自检
echo ============================================================
echo.
echo 跑完会在本目录生成「自检报告.txt」，
echo 把它发给作者就能定位问题。
echo.

set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY where python >nul 2>nul && set "PY=python"

if not defined PY (
    echo [X] 没找到 Python。
    echo.
    echo     去 https://www.python.org/downloads/ 装一个 Python 3.8 以上，
    echo     安装时**务必勾选 "Add Python to PATH"**。
    echo.
    echo     没有 Python 的话也没关系 —— 把这句话告诉作者就行。
    echo.
    pause
    exit /b 1
)

%PY% "自检.py"

echo.
echo ============================================================
echo 上面就是全部结果了。别忘了把「自检报告.txt」发出去。
echo ============================================================
pause
