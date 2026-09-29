#!/usr/bin/env bash
# DSH Pet 素材定制插帧工具 —— macOS 启动脚本
#
# 用法：在访达里双击本文件。若提示「无法打开，因为它来自身份不明的开发者」，
#       右键 → 打开 → 仍然打开；或者先在终端里跑一次：
#       chmod +x "一键插帧.command"
#
# ⚠️ 如果运行时看到一堆 "$'\r': command not found"，说明行尾被改成 CRLF 了。
#    修法：在终端里跑一次   python3 插帧.py
#    插帧.py 启动时会自动把同目录下的脚本行尾修好，然后再双击本文件即可。

cd "$(dirname "$0")" || exit 1

echo "============================================================"
echo "  DSH Pet 素材定制插帧工具（macOS）"
echo "============================================================"
echo

PY=""
for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
done
if [ -z "$PY" ]; then
    echo "✗ 没找到 Python3。先装一个："
    echo "    方式一：brew install python3   （需要先装 Homebrew）"
    echo "    方式二：去 https://www.python.org/downloads/macos/ 下安装包"
    echo
    echo "  注意：macOS 自带的是 python3 命令（不是 python），装完重开终端再试。"
    read -rp "按回车键关闭…" _
    exit 1
fi

# macOS 的 Gatekeeper 会给「从网上下载的」程序打隔离标记，不打掉的话
# rife 会被系统直接拒绝执行（报错很不直观）。这里顺手放行一下，失败也无所谓。
for t in rife-ncnn-vulkan rife-ncnn-vulkan.app ffmpeg ffprobe; do
    [ -e "$t" ] && xattr -dr com.apple.quarantine "$t" 2>/dev/null || true
done

"$PY" 插帧.py "$@"
rc=$?

echo
if [ $rc -ne 0 ]; then
    echo "（退出码 $rc，上面有原因）"
fi
read -rp "按回车键关闭…" _
exit $rc
