#!/usr/bin/env bash
# DSH Pet 素材定制插帧工具 —— Linux 启动脚本
#
# 用法：双击，或者在终端里跑   bash 一键插帧.sh
#
# ⚠️ 如果运行时看到一堆 "$'\r': command not found"，
#    说明这个文件的行尾被 Windows 编辑器改成 CRLF 了（bash 只认 LF）。
#    修法：在终端里跑一次   python3 插帧.py
#    插帧.py 启动时会自动把同目录下的脚本行尾修好，然后再双击本文件即可。

cd "$(dirname "$(readlink -f "$0")")" || exit 1

echo "============================================================"
echo "  DSH Pet 素材定制插帧工具"
echo "============================================================"
echo

# 找一个能用的 python
PY=""
for cand in python3 python py; do
    if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
done
if [ -z "$PY" ]; then
    echo "✗ 没找到 Python。请先装 Python 3.8 以上："
    echo "    Ubuntu / Debian : sudo apt install python3"
    echo "    Fedora          : sudo dnf install python3"
    echo "    Arch            : sudo pacman -S python"
    read -rp "按回车键关闭…" _
    exit 1
fi

"$PY" 插帧.py "$@"
rc=$?

echo
if [ $rc -ne 0 ]; then
    echo "（退出码 $rc，上面有原因）"
fi
read -rp "按回车键关闭…" _
exit $rc
