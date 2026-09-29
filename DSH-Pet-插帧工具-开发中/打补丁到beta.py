# -*- coding: utf-8 -*-
"""把本工具的本地补丁移植到作者 main 上，并加上作者 v5 规范里的 content/characters。

三处改动：
  1. pet/catalog.py —— 包扫描（content/characters + dlc/ + mods/）、包配置、画布声明
  2. pet/app.py    —— _apply_pack_geometry()，在建库建窗之前落地包的画布/缩放
  3. pet/window.py —— DB-001 修复：无帧时退化 mask + showEvent 兜底

⚠️ main 上 app.py / window.py 都变过（多了自动更新），所以不能整文件覆盖，
   只能按锚点插。catalog.py 没变，可以整文件拿过来再改常量。
"""
from pathlib import Path
import re

BETA = Path.home() / "dsh-pet-beta"
SRC = Path.home() / "dsh-pet-opt"          # 当前在用的、已打过补丁的副本
日志 = []


def 记(行):
    日志.append(行)
    print("  " + 行)


# ─────────────────────────────────────────── ① catalog.py
记("① catalog.py：整文件取自打过补丁的版本，再改回内置常量 + 加 content/characters")
源 = (SRC / "pet/catalog.py").read_text(encoding="utf-8")

# 1a. 内置常量改回作者原值（640×360 / 42ms）—— 画布改由包来声明
源 = 源.replace("CANVAS_W = 320\nCANVAS_H = 180", "CANVAS_W = 640\nCANVAS_H = 360")
源 = 源.replace("FEET_Y = 330 / 360 * CANVAS_H  # = 330", "FEET_Y = 330 / 360 * CANVAS_H")
源 = 源.replace("FRAME_MS = 14", "FRAME_MS = 42")
assert "CANVAS_W = 640" in 源 and "FRAME_MS = 42" in 源

# 1b. 包扫描里补上作者 v5 规范的内容目录 content/characters
旧 = """    # 本地扩展包目录：dlc/ 与 mods/ 和 characters/ 同构（<id>/videos/…），
    # 只是名字更贴合"加装"的语义。追加在最后 → 同名包以 characters/ 优先。
    for root in list(dirs):
        for pack_name in PACK_DIR_NAMES:
            dirs.append(root.parent / pack_name)
    return dirs"""
新 = """    # 本地扩展包目录：dlc/ 与 mods/ 和 characters/ 同构（<id>/videos/…），
    # 只是名字更贴合"加装"的语义。追加在最后 → 同名包以 characters/ 优先。
    for root in list(dirs):
        for pack_name in PACK_DIR_NAMES:
            dirs.append(root.parent / pack_name)
    # 作者 v5 规范里的内容 DLC 目录：<项目根>/content/characters/
    # （见 docs/plugin-phase-01-foundation/PLUGIN-DLC-ARCHITECTURE.md §4）
    # 放在最后：等作者真实现运行时，这个包原地不动就能被识别。
    dirs.append(Path(__file__).resolve().parent.parent / 'content' / 'characters')
    return dirs"""
assert 源.count(旧) == 1, 源.count(旧)
源 = 源.replace(旧, 新)
(BETA / "pet/catalog.py").write_text(源, encoding="utf-8")
记("   catalog.py 写好（含 PACK_DIR_NAMES / character_pack_config / character_canvas / apply_character_canvas）")

# ─────────────────────────────────────────── ② app.py
记("② app.py：按锚点插入 _apply_pack_geometry + 在 _create_library 开头调用")
a = (BETA / "pet/app.py").read_text(encoding="utf-8")

方法 = '''    def _apply_pack_geometry(self, character_id: str) -> None:
        """让角色包声明的画布与缩放生效（本地 DLC 的能力入口）。

        必须在构造 MovieLibrary / PetWindow **之前**调用：窗口尺寸是在构造期
        按 catalog.CANVAS_W/H 与 scale 算出来的。包没有声明时保持内置值，
        行为与改造前逐位一致。
        """
        applied = catalog.apply_character_canvas(character_id)
        if applied is not None:
            logging.info('角色包画布生效：%s -> %dx%d（脚底 y=%.0f，fps=%.0f）',
                         character_id, applied['width'], applied['height'],
                         applied['feet_y'], applied['fps'])
        raw = catalog.character_pack_config(character_id).get('scale')
        try:
            scale = float(raw)
        except (TypeError, ValueError):
            return
        if scale <= 0:
            return
        try:
            current = float(self.config.get('scale', 0) or 0)
        except (TypeError, ValueError):
            current = 0.0
        if abs(current - scale) < 1e-6:
            return
        self.config.set('scale', scale)
        self.config.save()
        logging.info('角色包缩放生效：%s -> %.3f', character_id, scale)

'''
锚方法 = "    def _create_library(self, character_id: str) -> MovieLibrary:\n"
assert a.count(锚方法) == 1, a.count(锚方法)
a = a.replace(锚方法, 方法 + 锚方法)

锚调用 = "    def _create_library(self, character_id: str) -> MovieLibrary:\n"
插入 = 锚调用 + "        # 角色包的能力入口：先把包声明的画布/缩放落地，再建库建窗\n        self._apply_pack_geometry(character_id)\n"
# 确认 _create_library 紧接着的下一行不是已插入的
assert a.count(插入) == 0
a = a.replace(锚方法, 插入, 1)
assert "self._apply_pack_geometry(character_id)" in a
(BETA / "pet/app.py").write_text(a, encoding="utf-8")
记("   app.py 写好（_apply_pack_geometry 已挂到 _create_library 开头）")

# ─────────────────────────────────────────── ③ window.py
记("③ window.py：DB-001 修复（showEvent 兜底 + 无帧退化 mask）")
w = (BETA / "pet/window.py").read_text(encoding="utf-8")

# 3a. 无帧守卫
锚3a = "        if perfstats.ENABLED:\n            _mask_t0 = perfstats.clock()\n        canvas = QImage(self._w, self._h, QImage.Format.Format_ARGB32)"
守卫 = '''        if self._frame_pixmap is None:
            # 还没有可用帧（素材缺失 / 规格与画布不符 / 解码失败）：**绝不能**
            # 停在默认的整块矩形输入区上，否则窗口覆盖范围会把鼠标事件全部
            # 吃掉（实测：素材尺寸与画布不符时整块区域点不动，而画面又是透明的，
            # 看起来像系统卡死）。
            # 注意：**不能交空 mask** —— Qt 把空 QRegion / 空 QBitmap 当作
            # "清除 mask"处理，等于恢复整块矩形（本机实测 A未设/B空QBitmap/
            # C空QRegion 三种写法命中结果完全一样）。退化成 1×1 的角落点，
            # 等价于"看不见就不参与命中"，且不改窗口 flag、无原生窗重建闪烁。
            self.setMask(QRegion(0, 0, 1, 1))
            self._mask_bounds = QRect()
            return
''' + 锚3a
assert w.count(锚3a) == 1, w.count(锚3a)
w = w.replace(锚3a, 守卫)

# 3b. showEvent 末尾补调
锚3b = "        self._effects_on_shown()\n"
assert w.count(锚3b) == 1, w.count(锚3b)
兜底 = 锚3b + '''        # 启动兜底：没有帧的时候窗口也必须先把输入区收掉。
        # _sync_mask() 平时只在「帧交付 / 缩放变更 / 弹动画 tick」里被调用 ——
        # 素材坏掉（缺失、尺寸与画布不符）时一帧都不会交付，于是从来没人调过它，
        # 窗口就一直停在默认的整块矩形输入区上，把覆盖范围内的鼠标事件全吃掉。
        self._sync_mask()
'''
w = w.replace(锚3b, 兜底)
(BETA / "pet/window.py").write_text(w, encoding="utf-8")
记("   window.py 写好")

print()
print("=== 语法自检 ===")
import ast
for f in ("pet/catalog.py", "pet/app.py", "pet/window.py"):
    try:
        ast.parse((BETA / f).read_text(encoding="utf-8"))
        print(f"  ✓ {f}")
    except SyntaxError as e:
        print(f"  ✘ {f}: {e}")
