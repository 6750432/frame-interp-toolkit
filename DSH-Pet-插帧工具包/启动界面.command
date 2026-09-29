#!/usr/bin/env bash
# DSH Pet 素材定制插帧工具 —— macOS 图形界面启动
#
# 用法：在访达里双击本文件。
# 若提示「无法打开，因为它来自身份不明的开发者」：右键 → 打开 → 仍然打开；
# 或者先在终端里跑一次 chmod +x "启动界面.command"
#
# ⚠️ 报 "$'\r': command not found" 的话，说明行尾被改成 CRLF 了。
#    在终端跑一次   python3 插帧.py   它会自动把行尾修好。

cd "$(dirname "$0")" || exit 1

PY=""
for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
done
if [ -z "$PY" ]; then
    echo "✗ 没找到 Python3。先装一个："
    echo "    brew install python-tk     （需要先装 Homebrew）"
    echo "    或去 https://www.python.org/downloads/macos/ 下安装包"
    read -rp "按回车键关闭…" _
    exit 1
fi

if ! "$PY" -c "import tkinter" >/dev/null 2>&1; then
    echo "✗ 你的 Python 没带 tkinter（图形界面库）。"
    echo "    Homebrew 装的：brew install python-tk"
    echo "    官网安装包装的：重新跑一遍安装包，把 Tcl/Tk 勾上"
    echo
    echo "   （不想装也没关系，命令行版一样能用：bash 一键插帧.sh）"
    read -rp "按回车键关闭…" _
    exit 1
fi

# macOS 的 Gatekeeper 会给「从网上下载的」程序打隔离标记，不打掉的话
# rife 会被系统直接拒绝执行（而且报错很不直观）。这里顺手放行一下。
# 失败也不影响 —— 只是少一道保险。
for t in rife-ncnn-vulkan rife-ncnn-vulkan.app ffmpeg ffprobe; do
    [ -e "$t" ] && xattr -dr com.apple.quarantine "$t" 2>/dev/null || true
done

"$PY" gui.py
rc=$?
if [ $rc -ne 0 ]; then
    echo
    echo "（退出码 $rc，上面有原因）"
    read -rp "按回车键关闭…" _
fi
exit $rc
