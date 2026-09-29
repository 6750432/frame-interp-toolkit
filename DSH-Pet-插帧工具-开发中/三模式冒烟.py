# -*- coding: utf-8 -*-
"""三模式冒烟测试：不点鼠标，直接把界面建起来，逐个模式切一遍看有没有炸。

检查项（每条都打印，谁挂了就是谁）：
  1. 主窗口能建起来
  2. 视频 / 音频 / 视音 三种模式都能切过去
  3. 音频面板确实挂上了，而且关键控件都在
  4. 音频面板的「当前链路」读得出来
  5. 视音模式下音频面板是紧凑版（没有自己的开始按钮）
不点「开始」，不发任何子进程 —— 只验界面装配。
"""
import os
import sys
import traceback

os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("XAUTHORITY", os.path.expanduser("~/.Xauthority"))

工具包 = os.path.expanduser("~/DSH-Pet-插帧工具包")
sys.path.insert(0, 工具包)

import tkinter as tk          # noqa: E402
from tkinter import ttk       # noqa: E402
import gui                    # noqa: E402

# ⚠️ 切换模式会往 config.json 写「工作模式」——测完必须还回去，
#    不然用户的界面下次打开会停在测试最后停的那一页。
import json                   # noqa: E402
_CFG = os.path.join(工具包, "config.json")
try:
    _原模式 = json.load(open(_CFG, encoding="utf-8")).get("工作模式")
except Exception:
    _原模式 = None

失败 = []
def 记(名称, 通过, 备注=""):
    print(("  ✔ " if 通过 else "  ✘ ") + 名称 + (f"   {备注}" if 备注 else ""))
    if not 通过:
        失败.append(名称)

print("=" * 60)
print("三模式冒烟测试")
print("=" * 60)

try:
    窗口 = gui.App()
    窗口.update()
    记("主窗口建起来", True)
except Exception:
    print("  ✘ 主窗口建不起来：")
    traceback.print_exc()
    sys.exit(1)

# 等新手卡片冒出来（它是 after(350) 起手的），顺便验"卡片跟着模式换文案"
try:
    import time as _t
    _t.sleep(0.6)
    窗口.update()
    卡片 = getattr(窗口, "guide", None)
    if 卡片 is not None and 卡片.winfo_exists():
        记("新手卡片出来了", True)
        原文 = 卡片._步.cget("text")
        # 换到一个**跟当前不一样**的模式，文案才该变（启动那页已经是当前模式了）
        目标 = "视音" if 窗口.var_模式.get() != "视音" else "音频"
        窗口.var_模式.set(目标); 窗口._切换模式(); 窗口.update()
        新文 = 卡片._步.cget("text")
        关键词 = {"视音": "音轨修好换进去", "音频": "开始音频修复"}[目标]
        记("卡片文案跟着模式换", 原文 != 新文 and 关键词 in 新文,
           f"{目标}版首行：" + 新文.splitlines()[0])
        记("卡片没被顶出屏幕", 卡片.winfo_x() < 窗口.winfo_screenwidth() and
           卡片.winfo_y() < 窗口.winfo_screenheight(),
           f"位置 ({卡片.winfo_x()}, {卡片.winfo_y()})")
    else:
        记("新手卡片出来了", True, "（这次没弹：之前已选「老鸟」或已记住）")
except Exception:
    print("  ✘ 新手卡片相关检查炸了")
    traceback.print_exc()
    失败.append("新手卡片")


for 模式 in ("视频", "音频", "视音"):
    try:
        窗口.var_模式.set(模式)
        窗口._切换模式()
        窗口.update()
        面板 = 窗口._音频面板
        if 模式 == "视频":
            可见 = not 窗口.frame_音频.winfo_ismapped() or 面板 is None
            记(f"{模式}：切过去不炸", True, f"音频面板={'未加载' if 面板 is None else '已加载'}")
        elif 模式 == "音频":
            记(f"{模式}：切过去不炸", True)
            记(f"{模式}：音频面板已挂载", 面板 is not None)
            if 面板 is not None:
                有 = {n: hasattr(面板, n) for n in
                      ("var_强度", "var_风格", "var_响度", "var_格式", "var_方式",
                       "var_裁静音", "var_去齿音", "btn_跑", "lbl_链路")}
                缺 = [k for k, v in 有.items() if not v]
                记(f"{模式}：关键控件齐全", not 缺, ("缺：" + "、".join(缺)) if 缺 else
                   f"{len(有)} 个都在")
                try:
                    链路 = 面板.当前链路()
                    记(f"{模式}：链路读得出来", True, "→".join(map(str, 链路)) or "(空)")
                except Exception as exc:
                    记(f"{模式}：链路读得出来", False, repr(exc))
        else:  # 视音
            记(f"{模式}：切过去不炸", True)
            记(f"{模式}：音频面板已挂载", 面板 is not None)
            if 面板 is not None:
                记(f"{模式}：紧凑版（按钮交给主界面）",
                   getattr(面板, "紧凑", None) is True,
                   f"紧凑={getattr(面板, '紧凑', None)}")
                记(f"{模式}：源那一行藏起来了",
                   not 面板._行_源.winfo_ismapped(),
                   f"ismapped={面板._行_源.winfo_ismapped()}")
    except Exception:
        print(f"  ✘ {模式}：切换时抛异常")
        traceback.print_exc()
        失败.append(f"{模式} 切换异常")

# 来回切一圈：视音 → 音频，确认面板能换挡回来（这条是回归出来的真 bug）
try:
    窗口.var_模式.set("视音")
    窗口._切换模式()
    窗口.update()
    窗口.var_模式.set("音频")
    窗口._切换模式()
    窗口.update()
    面板 = 窗口._音频面板
    记("视音→音频：换挡回来（不再是紧凑版）",
       getattr(面板, "紧凑", None) is False, f"紧凑={getattr(面板, '紧凑', None)}")
    记("视音→音频：源输入框还在（开始才会修声音）",
       hasattr(面板, "var_源") and 面板._行_源.winfo_ismapped(),
       f"有var_源={hasattr(面板, 'var_源')} 显示={面板._行_源.winfo_ismapped()}")
    # 关键：这条路由错了就会"点了不修声音"
    记("视音→音频：开始按钮指向音频流程（紧凑标记为假）",
       getattr(面板, "紧凑", True) is False)
except Exception:
    print("  ✘ 视音→音频 换挡时抛异常")
    traceback.print_exc()
    失败.append("视音→音频 换挡")

# 回归：**三种模式下「运行日志」都必须看得见**（既定约束：日志每个板块都要）
try:
    for 模式 in ("视频", "音频", "视音"):
        窗口.var_模式.set(模式)
        窗口._切换模式()
        窗口.update()
        可见 = 窗口.frame_日志.winfo_ismapped() and 窗口.txt.winfo_ismapped()
        高 = 窗口.txt.winfo_height()
        记(f"{模式}：运行日志可见", bool(可见), f"高度 {高}px")
except Exception:
    print("  ✘ 运行日志可见性检查炸了")
    traceback.print_exc()
    失败.append("运行日志可见性")

# 回归：来回切模式**不能**让新手卡片越贴越长（踩过：设模式里混进了建控件的代码）
if 卡片 is not None and 卡片.winfo_exists():
    def _子树(w):
        for c in w.winfo_children():
            yield c
            yield from _子树(c)
    按钮数 = sum(1 for c in _子树(卡片) if isinstance(c, ttk.Button))
    提示数 = sum(1 for c in _子树(卡片)
                 if isinstance(c, ttk.Label) and "点右上角" in str(c.cget("text")))
    记("卡片按钮没被重复贴（应正好 2 个）", 按钮数 == 2, f"实际 {按钮数} 个")
    记("卡片提示行没被重复贴（应正好 1 行）", 提示数 == 1, f"实际 {提示数} 行")

# 切回视频模式收尾，确认还能回来
try:
    窗口.var_模式.set("视频")
    窗口._切换模式()
    窗口.update()
    记("切回视频模式", 窗口.frame_音频.winfo_ismapped() == 0 or 窗口._音频面板 is None)
except Exception:
    print("  ✘ 切回视频时抛异常")
    traceback.print_exc()
    失败.append("切回视频")

try:
    窗口.destroy()
except Exception:
    pass

# 把用户原来的「工作模式」还回去
if _原模式 is not None:
    try:
        数据 = json.load(open(_CFG, encoding="utf-8"))
        数据["工作模式"] = _原模式
        json.dump(数据, open(_CFG, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=4)
        print(f"  ↩ 已把「工作模式」还原成 {_原模式}")
    except Exception as exc:
        print(f"  ⚠️ 还原「工作模式」失败：{exc}")

print("-" * 60)
print(("全部通过 ✔" if not 失败 else f"有 {len(失败)} 项没过：" + "、".join(失败)))
sys.exit(0 if not 失败 else 2)
