#!/usr/bin/env bash
# DSH Pet 插帧工具 —— 快速自检（macOS）
#
# 用法：在访达里双击本文件。
# 若提示「无法识别开发者」：右键 → 打开 → 仍然打开。

cd "$(dirname "$0")" || exit 1

echo "============================================================"
echo "  DSH Pet 插帧工具 - 快速自检"
echo "============================================================"
echo

PY=""
for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done

if [ -z "$PY" ]; then
    echo "✗ 没找到 Python3。"
    echo "    brew install python3      （需要先装 Homebrew）"
    echo "    或去 https://www.python.org/downloads/macos/ 下安装包"
    echo
    echo "  没有 Python 也没关系 —— 把这句话告诉作者就行。"
    read -rp "按回车键关闭…" _
    exit 1
fi

# macOS 会给下载来的程序打隔离标记，顺手放行（失败无所谓）
for t in rife-ncnn-vulkan rife-ncnn-vulkan.app ffmpeg ffprobe; do
    [ -e "$t" ] && xattr -dr com.apple.quarantine "$t" 2>/dev/null || true
done

"$PY" 自检.py

echo
echo "============================================================"
echo " 上面就是全部结果了。别忘了把「自检报告.txt」发出去。"
echo "============================================================"
read -rp "按回车键关闭…" _
