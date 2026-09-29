#!/usr/bin/env bash
# DSH Pet 插帧工具 —— 快速自检（Linux）
#
# 用法：双击，或者  bash 一键自检.sh

cd "$(dirname "$(readlink -f "$0")")" || exit 1

echo "============================================================"
echo "  DSH Pet 插帧工具 - 快速自检"
echo "============================================================"
echo

PY=""
for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done

if [ -z "$PY" ]; then
    echo "✗ 没找到 Python。装一个就行："
    echo "    sudo apt install python3          （Debian / Ubuntu / Mint）"
    echo "    sudo dnf install python3          （Fedora）"
    echo
    echo "  没有 Python 也没关系 —— 把这句话告诉作者就行。"
    read -rp "按回车键关闭…" _
    exit 1
fi

"$PY" 自检.py

echo
echo "============================================================"
echo " 上面就是全部结果了。别忘了把「自检报告.txt」发出去。"
echo "============================================================"
read -rp "按回车键关闭…" _
