#!/usr/bin/env bash
# DSH Pet 素材定制插帧工具 —— Linux 图形界面启动
#
# 用法：双击，或者在终端里跑   bash 启动界面.sh
#
# ⚠️ 报 "$'\r': command not found" 的话，说明文件行尾被改成 CRLF 了。
#    在终端跑一次   python3 插帧.py   它会自动把行尾修好。

cd "$(dirname "$(readlink -f "$0")")" || exit 1

# 找一个能用的 python
PY=""
for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
done
if [ -z "$PY" ]; then
    echo "✗ 没找到 Python。请先装：sudo apt install python3 python3-tk"
    read -rp "按回车键关闭…" _
    exit 1
fi

# Linux 上 tkinter 常常是单独一个包，缺了会给一句人畜无害的 ImportError
if ! "$PY" -c "import tkinter" >/dev/null 2>&1; then
    echo "✗ 你的 Python 没带 tkinter（图形界面库）。装一下就好："
    echo "    Ubuntu / Debian : sudo apt install python3-tk"
    echo "    Fedora          : sudo dnf install python3-tkinter"
    echo "    Arch            : sudo pacman -S tk"
    echo
    echo "   （不想装也没关系，命令行版一样能用：bash 一键插帧.sh）"
    read -rp "按回车键关闭…" _
    exit 1
fi

if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
    echo "✗ 没检测到图形环境（DISPLAY 是空的）。"
    echo "  如果是 SSH 连过来的，得用图形转发或者在桌面上直接跑。"
    echo "  命令行版不受影响：bash 一键插帧.sh"
    read -rp "按回车键关闭…" _
    exit 1
fi

"$PY" gui.py
rc=$?
if [ $rc -ne 0 ]; then
    echo
    echo "（退出码 $rc，上面有原因）"
    read -rp "按回车键关闭…" _
fi
exit $rc
