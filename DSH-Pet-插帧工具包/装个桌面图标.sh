#!/usr/bin/env bash
# 在桌面上放一个「能双击的图标」（Linux / XFCE·GNOME·KDE 都行）
#
# 为什么需要这么个东西：
#   Linux 的文件管理器默认把 .sh 当**文本文件**，双击「启动界面.sh」
#   往往只会弹出一屏代码，程序一点动静都没有（Thunar 就是这样，
#   连问都不问）。这不是工具坏了，是文件管理器的默认策略。
#   .desktop 启动器不受这个策略影响 —— 双击它一定能跑起来。
#
# 用法：在这个文件夹里开终端，然后跑
#     bash 装个桌面图标.sh
#
# 想撤掉：把桌面上那个「DSH Pet 插帧工具.desktop」删了就行，
#         再顺手删 ~/.local/share/applications/ 里同名的那份。

HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"

if [ ! -f "$HERE/启动界面.sh" ]; then
    echo "✗ 找不到 $HERE/启动界面.sh"
    echo "  这个脚本要跟工具包放在同一个文件夹里。"
    read -rp "按回车键关闭…" _
    exit 1
fi

# 桌面目录：优先问 xdg-user-dir，问不到就猜常见名字
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null)"
for cand in "$DESKTOP_DIR" "$HOME/桌面" "$HOME/Desktop" "$HOME"; do
    [ -n "$cand" ] && [ -d "$cand" ] && { DESKTOP_DIR="$cand"; break; }
done

write_desktop() {
    cat > "$1" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=DSH Pet 插帧工具
GenericName=素材插帧
Comment=双击打开图形界面（等价于 bash 启动界面.sh）
Exec=bash "$HERE/启动界面.sh"
Path=$HERE
Icon=applications-multimedia
Terminal=false
Categories=AudioVideo;Utility;
StartupNotify=true
EOF
    chmod +x "$1"
}

TARGET="$DESKTOP_DIR/DSH-Pet-插帧工具.desktop"
write_desktop "$TARGET"

# 顺手也丢进应用菜单（以后搜「插帧」就能找到）
APPS="$HOME/.local/share/applications"
mkdir -p "$APPS"
write_desktop "$APPS/DSH-Pet-插帧工具.desktop"

# 有些文件管理器（GNOME 系的）要标记成「可信任」才让双击。
# 有 gio 就顺手标一下，标不上也不影响 XFCE / KDE。
if command -v gio >/dev/null 2>&1; then
    gio set "$TARGET" metadata::trusted true >/dev/null 2>&1
    gio set "$APPS/DSH-Pet-插帧工具.desktop" metadata::trusted true >/dev/null 2>&1
fi

echo "✔ 装好了："
echo "     $TARGET"
echo "     （应用菜单里也有一份，搜「插帧」就能找到）"
echo
echo "  以后双击那个图标就能开图形界面，不用再开终端了。"
echo "  工具包挪了地方的话，重新跑一次这个脚本就行。"
echo
read -rp "按回车键关闭…" _
