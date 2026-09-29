#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DSH Pet 素材定制插帧工具 —— 图形界面（v0.8）
=============================================
给不想碰命令行的群友用：选两个文件夹、填个数字、点一下按钮就行。

设计哲学（v0.8）：
* **推荐是帮你填，不是替你选** —— 预设按钮只往输入框里填数字，不锁死、
  不禁用输入框，你随时能改成别的。
* **体检只报信息，不改业务流程** —— 右边那块只是展示，判断逻辑一律
  调用底层（插帧.py）的现成函数，这里一行独立判断都不写。
* **小白无门槛，极客无上限** —— 默认点两下就能跑；想调参数的全在
  config.json 和命令行版里，一个都没少。

架构：底层（插帧.py）的插帧/拆帧/编码流水线**一行不动**。
所有新能力都在本文件（GUI 外层）。

依赖：只用 Python 自带的 tkinter，零第三方库。
"""

from __future__ import annotations

import importlib.util
import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

HERE = Path(__file__).resolve().parent
CORE = HERE / "插帧.py"
CONFIG = HERE / "config.json"

VERSION = "v0.9"

# 目标帧率允许的范围（超出就给提示）
FPS_MIN, FPS_MAX = 2, 240
FPS_SUGGEST = "72-144"

# 预设按钮：(名字, 相对源帧率的倍数, 鼠标悬停的说明)
# 「源 24fps」那一列是举的例子，实际倍数是按你素材的真实帧率算的。
PRESETS = [
    ("省电",       2, "最省 CPU。源 24fps → 48fps。老笔记本 / 小机箱友好"),
    ("均衡",       3, "默认安全线。源 24fps → 72fps。画质最稳"),
    ("丝滑",       5, "源 24fps → 120fps。超过默认安全线，会先拦一下"),
    ("高帧高画质", 6, "源 24fps → 144fps。整数倍不抖，144Hz 屏刚好"),
    ("全都拉满",   8, "源 24fps → 192fps。很吃 CPU，会弹窗确认"),
]
# 这几个预设会超出默认安全倍数，软件渲染（llvmpipe）时置灰
HIGH_PRESETS = {"丝滑", "高帧高画质", "全都拉满"}

# 预估表的档位（固定 9 档，不是笛卡尔积 —— 每行只变帧率这一个变量）
EST_TARGETS = [48, 60, 72, 90, 120, 144, 165, 180, 240]

# 预估公式的基准：i7-6700 + RTX 2060，640×360 带透明的实测值
REF_PX = 640 * 360
BASE_SEC = 6.0          # 起子进程 / 拆帧 / 收尾的固定开销
SEC_PER_FRAME = 0.026   # 每输出一帧的成本（含两次 RIFE + 编码）
MB_PER_FRAME = 0.0029   # 每输出一帧的体积


# ================================================================== 平台适配
def setup_platform() -> None:
    """Windows 上把进程标成「DPI 感知」，否则系统缩放 125% 时界面是糊的。"""
    if os.name != "nt":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)   # Win8.1+
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()        # 老系统兜底
    except Exception:
        pass          # 拿不到也无所谓，顶多界面糊一点，不能因此起不来


def disk_is_rotational(path: str) -> bool | None:
    """Windows：判断这个盘是不是机械硬盘。返回 None = 查不出来。

    为什么不用 psutil：本工具的铁律是**零第三方依赖**。
    这里直接问 Windows 要「寻道代价」属性：
    固态盘 IncursSeekPenalty = 0，机械盘 = 1。
    """
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        GENERIC_READ = 0
        FILE_SHARE_READ = 1
        FILE_SHARE_WRITE = 2
        OPEN_EXISTING = 3
        IOCTL_STORAGE_QUERY_PROPERTY = 0x002D1400
        StorageDeviceSeekPenaltyProperty = 7
        PropertyStandardQuery = 0

        class STORAGE_PROPERTY_QUERY(ctypes.Structure):
            _fields_ = [("PropertyId", ctypes.c_int),
                        ("QueryType", ctypes.c_int),
                        ("AdditionalParameters", ctypes.c_byte * 1)]

        class DEVICE_SEEK_PENALTY_DESCRIPTOR(ctypes.Structure):
            _fields_ = [("Version", ctypes.c_ulong),
                        ("Size", ctypes.c_ulong),
                        ("IncursSeekPenalty", ctypes.c_ubyte)]

        drive = os.path.splitdrive(os.path.abspath(path))[0] or "C:"
        h = ctypes.windll.kernel32.CreateFileW(
            f"\\\\.\\{drive}", GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
            None, OPEN_EXISTING, 0, None)
        if h == -1 or h == 0xFFFFFFFFFFFFFFFF:
            return None
        try:
            q = STORAGE_PROPERTY_QUERY()
            q.PropertyId = StorageDeviceSeekPenaltyProperty
            q.QueryType = PropertyStandardQuery
            d = DEVICE_SEEK_PENALTY_DESCRIPTOR()
            ret = wintypes.DWORD()
            ok = ctypes.windll.kernel32.DeviceIoControl(
                h, IOCTL_STORAGE_QUERY_PROPERTY, ctypes.byref(q),
                ctypes.sizeof(q), ctypes.byref(d), ctypes.sizeof(d),
                ctypes.byref(ret), None)
            if not ok:
                return None
            return bool(d.IncursSeekPenalty)
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
    except Exception:
        return None


def copy_to_clipboard(widget: tk.Misc, text: str, feedback: tk.Label | None = None) -> None:
    """复制到剪贴板。

    ⚠️ Linux/X11 的坑：剪贴板是「应用还活着才有效」的。X11 下必须调一次
    update() 让 Tk 真正把内容登记上去；如果复制完立刻销毁窗口，内容就没了。
    所以这里除了复制，还会在界面上留一份**可选中**的文本供用户手动 Ctrl+C。
    """
    try:
        widget.clipboard_clear()
        widget.clipboard_append(text)
        widget.update()          # X11 上少了这句，剪贴板可能是空的
        if feedback is not None:
            feedback.configure(text="已复制 ✓")
            widget.after(1600, lambda: feedback.configure(text=""))
    except Exception as exc:
        if feedback is not None:
            feedback.configure(text=f"复制失败：{exc}")


# ================================================================== 读配置
def load_cfg() -> dict:
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cfg(updates: dict) -> None:
    """只改指定的键，其它键原样保留（旧版 config.json 直接兼容）。"""
    try:
        d = load_cfg()
        d.update(updates)
        CONFIG.write_text(json.dumps(d, ensure_ascii=False, indent=4) + "\n",
                          encoding="utf-8")
    except Exception:
        pass


# ================================================================== 底层复用
def load_core():
    """把 插帧.py 当模块加载进来，直接复用它的函数。

    为什么不用 subprocess 去问：**红线要求「检测类 UI 只做展示，
    业务判断依然调用原有底层函数，不复制独立逻辑」**。
    导入进来调它的 find_ffmpeg / check_gpus / probe，就是最彻底的复用 ——
    两边共用同一份代码，永远不会各说各话。

    插帧.py 的 main() 有 `if __name__ == "__main__"` 守卫，
    导入时不会真的开始跑活。
    """
    try:
        spec = importlib.util.spec_from_file_location("dshpet_core", CORE)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


CORE_MOD = load_core()


def core_const(name: str, fallback):
    """从底层取一个常量；取不到就用兜底值，不让界面崩。"""
    v = getattr(CORE_MOD, name, None)
    return v if v is not None else fallback


# ================================================================== 新手引导
def 模式步骤(模式: str) -> str:
    """新手卡片的正文 —— 三种模式说的步骤不一样。"""
    if 模式 == "音频":
        return ("这一页只管声音，不碰画面：\n"
                "  ① 点「选文件…」或「选文件夹…」挑要修的音频\n"
                "  ② 上面确认「输出文件夹」\n"
                "  ③ 点「▶ 开始音频修复」，跑完点「打开输出文件夹」\n"
                "  默认参数就能用；听着跟没修一样就换个「EQ 风格」再跑。\n")
    if 模式 == "视音":
        return ("一次干两件事（画面插帧 + 声音修复）：\n"
                "  ① 上面选好「源素材文件夹」和「输出文件夹」\n"
                "  ② 填目标帧率；下方面板里设音频参数（三档至少要勾一个）\n"
                "  ③ 点「▶ 开始插帧」—— 插完会自动接着把音轨修好换进去\n")
    return ("三步就完事：\n"
            "  ① 选「源素材文件夹」（素材放这儿）\n"
            "  ② 选「输出文件夹」（结果去这儿拿）\n"
            "  ③ 填个目标帧率（或者点左边那几个快捷键），点开始\n")


class GuidePopup(tk.Toplevel):
    """The little first-run hint card.
    
    首次启动时冒出来的小提示。

    刻意做成**非模态**（不调 grab_set）：它只是个指路牌，
    不该把主界面锁住。用户可以拖着它到处放，也可以直接关掉。
    """

    def __init__(self, master: "App"):
        super().__init__(master)
        self.master_app = master
        self.title("第一次用？")
        self.transient(master)
        self.resizable(False, False)
        self.configure(padx=16, pady=12)

        ttk.Label(self, text="第一次用这个工具？",
                  font=("", 12, "bold")).pack(anchor="w")
        # 文案跟着当前模式走 —— 在「音频」页却教人"填目标帧率"很容易把人绕晕
        self._步 = ttk.Label(self, text=模式步骤("视频"), justify="left")
        self._步.pack(anchor="w", pady=(8, 4))
        self._模式 = "视频"

        ttk.Label(self, text="不清楚哪个按钮是干嘛的，就点右上角的 [?]。",
                  foreground="#666").pack(anchor="w", pady=(0, 10))

        row = ttk.Frame(self)
        row.pack(fill="x")
        ttk.Button(row, text="新手，保留提示", command=self._keep).pack(side="left")
        ttk.Button(row, text="老手，不再提示", command=self._dismiss).pack(side="left", padx=8)
        ttk.Label(row, text="（可以拖到任意位置）", foreground="#999").pack(side="left")

        self.update_idletasks()
        self._place_me()

    def 设模式(self, 模式: str) -> None:
        """模式一换，卡片上的步骤也跟着换（卡片还开着的时候）。

        ⚠️ 这个方法**只能改文案，绝不能再往卡片上 pack 控件**。
        之前它的函数体里混进了 __init__ 的尾巴（提示行 + 两个按钮），
        于是每切一次模式就重贴一整套按钮，卡片越长越离谱 —— 实测踩过。
        """
        模式 = 模式 if 模式 in ("视频", "音频", "视音") else "视频"
        if 模式 == getattr(self, "_模式", None):
            return
        try:
            self._步.configure(text=模式步骤(模式))
            self._模式 = 模式
            self.update_idletasks()
            self._place_me()          # 文案行数变了，位置重算，别顶出屏幕
        except Exception:
            pass

    def _place_me(self) -> None:
        """把卡片摆在主窗口旁边，但**保证整张都在屏幕里**。

        原来的算法只算了「主窗口右边还剩多少」，没管屏幕边界 ——
        主窗口一宽（1080 哪怕只占屏幕一半），x 就跑到 1900 多，
        整张卡片飞出去，只剩一条边露在外面，用户以为它坏了。
        现在三级退让：

          ① 主窗口右边放得下 → 摆右边（原来的行为，不挡主界面）
          ② 右边放不下     → 摆到主窗口内部的右上角（像贴纸一样）
          ③ 主窗口自己快占满屏 → 贴着屏幕右上角放

        最后再兜一次底：摆完量一下真实位置，出界就硬拉回来
        （防缩放、多屏这些算不准的情况）。
        """
        m = self.master
        try:
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            mx, my = m.winfo_rootx(), m.winfo_rooty()
            mw, mh = m.winfo_width(), m.winfo_height()
            pw, ph = self.winfo_reqwidth(), self.winfo_reqheight()
            gap, margin = 12, 24

            x = mx + mw + gap                       # ① 右边
            if x + pw > sw - margin:
                x = mx + mw - pw - gap              # ② 主窗口内部右上角
            if x < margin or x + pw > sw - margin:
                x = sw - pw - margin                # ③ 贴屏幕右上角

            y = my + 60
            if y + ph > sh - margin:
                y = max(margin, sh - ph - margin)

            self.geometry(f"+{int(max(0, x))}+{int(max(0, y))}")

            # 兜底：按实际落点再修一次
            self.update_idletasks()
            nx = min(max(self.winfo_x(), 0), max(0, sw - pw))
            ny = min(max(self.winfo_y(), 0), max(0, sh - ph))
            if (nx, ny) != (self.winfo_x(), self.winfo_y()):
                self.geometry(f"+{nx}+{ny}")
        except Exception:
            pass

    def _keep(self) -> None:
        # 「新手」= 让它留着当路标，但把按钮换成一句提示免得反复点
        for w in self.winfo_children():
            w.destroy()
        self.configure(padx=16, pady=12)
        ttk.Label(self, text="那就照上面三步来：",
                  font=("", 11, "bold")).pack(anchor="w")
        ttk.Label(self, text=(
            "  ① 选源素材文件夹\n  ② 选输出文件夹\n  ③ 填帧率 → 点「开始插帧」\n\n"
            "  卡住了就点主界面右上角的 [?]。\n"
            "  这张小卡片可以拖到屏幕角落，随时关。"),
            justify="left").pack(anchor="w", pady=(8, 8))
        ttk.Button(self, text="知道了", command=self.destroy).pack(anchor="e")

    def _dismiss(self) -> None:
        save_cfg({"新手引导已完成": True})
        self.destroy()


# ================================================================== 可滚动容器
class ScrollBox(ttk.Frame):
    """A scrollable container built only from stock tkinter widgets.
    
    一个能滚的容器，只用 tkinter 自带的东西。

    帮助面板内容挺长（五个折叠区 + 一堆链接），全展开肯定超出屏幕，
    没有滚动条就只能把窗口拉到比屏幕还高 —— 那还不如直接给个滚的。
    """

    def __init__(self, master: tk.Misc):
        super().__init__(master)
        self.canvas = tk.Canvas(self, highlightthickness=0, background="#fbfbfb",
                                borderwidth=0)
        sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>",
                        lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        for w in (self.canvas, self.inner):
            w.bind("<MouseWheel>", self._wheel)     # Windows / macOS
            w.bind("<Button-4>", self._wheel)       # X11 上滚
            w.bind("<Button-5>", self._wheel)       # X11 下滚

    def bind_wheel_tree(self, widget: tk.Misc | None = None) -> None:
        """把滚轮事件递归绑到所有子控件上。

        ⚠️ 这一步不能省：Tk 的事件**不会往父控件冒泡**。
        内容填进去之后，鼠标多半是停在某个 Label 上的 ——
        只绑 canvas 的话，滚轮事件被 Label 吃掉，页面根本不动。
        """
        w = widget if widget is not None else self.inner
        try:
            w.bind("<MouseWheel>", self._wheel)
            w.bind("<Button-4>", self._wheel)
            w.bind("<Button-5>", self._wheel)
        except Exception:
            pass
        for child in w.winfo_children():
            self.bind_wheel_tree(child)

    def _wheel(self, e) -> None:
        if getattr(e, "num", 0) == 4:
            d = -1
        elif getattr(e, "num", 0) == 5:
            d = 1
        else:
            d = -1 if getattr(e, "delta", 0) > 0 else 1
        self.canvas.yview_scroll(d, "units")


# ================================================================== 帮助面板
class HelpWindow(tk.Toplevel):
    """Help panel: draggable, non-modal, with hand-rolled collapsible sections.
    
    帮助面板：可拖拽、非模态、折叠区手写（只用 pack_forget/pack）。

    链接全部加了 gh-proxy 前缀（国内直连 GitHub 打不开），
    每个链接旁边都有「复制」按钮，也留了可选中文本兜底 Ctrl+C。
    """

    LINKS = [
        ("Python（必装）", "https://gh-proxy.com/https://www.python.org/downloads/"),
        ("ffmpeg（Windows 版）", "https://gh-proxy.com/https://www.gyan.dev/ffmpeg/builds/"),
        ("rife-ncnn-vulkan（插帧本体）",
         "https://gh-proxy.com/https://github.com/nihui/rife-ncnn-vulkan/releases"),
        ("本工具的 GitHub（如果有）", "https://gh-proxy.com/https://github.com/"),
    ]

    def __init__(self, master: "App"):
        super().__init__(master)
        self.title(f"帮助 · DSH Pet 素材定制插帧工具 {VERSION}")
        self.geometry("800x680")
        self.minsize(600, 420)

        head = ttk.Frame(self)
        head.pack(fill="x", padx=12, pady=(10, 4))
        ttk.Label(head, text="❓ 帮助（这窗口可以随便拖、随便关）",
                  font=("", 13, "bold")).pack(side="left")
        self.lbl_copy = ttk.Label(head, text="", foreground="#2a7")
        self.lbl_copy.pack(side="right")

        # 内容挺长，套一个能滚的容器，别把窗口撑到比屏幕还高
        self.scroll = ScrollBox(self)
        self.scroll.pack(fill="both", expand=True, padx=10, pady=6)

        ttk.Label(self.scroll.inner, justify="left", wraplength=730, font=("", 10),
                  text=("三步上手：\n"
                        "  ① 源素材文件夹：把素材丢进去的那个文件夹\n"
                        "  ② 输出文件夹：结果会出现在这儿\n"
                        "  ③ 填个目标帧率（或点左边那几个快捷键），点「开始插帧」\n\n"
                        "下面几块可以点标题展开/收起。链接都加了国内中转前缀，直接能用。")
                  ).pack(anchor="w", padx=8, pady=(8, 10))

        self._build_sections()
        self.finish_build()

        foot = ttk.Frame(self)
        foot.pack(fill="x", padx=12, pady=(4, 12))
        self.var_auto = tk.BooleanVar(value=bool(load_cfg().get("启动时自动打开帮助")))
        ttk.Checkbutton(foot, text="以后启动就自动打开这份帮助",
                        variable=self.var_auto,
                        command=self._toggle_auto).pack(side="left")
        ttk.Button(foot, text="关闭", command=self.destroy).pack(side="right")

    # ---- 折叠区：只用 pack_forget() / pack() 手写，不引第三方库 ----
    def _fold(self, parent: tk.Misc, title: str, lines: list[str]) -> None:
        box = ttk.LabelFrame(parent, text=" ")
        box.pack(fill="x", padx=4, pady=3)
        head = ttk.Frame(box)
        head.pack(fill="x")
        # 初始 open=False，下面 toggle() 一次把它打开 ——
        # 这样按钮文字和实际状态一定一致，不会出现"写着▼其实是收着"的错位
        state = {"open": False}

        content = ttk.Frame(box)

        def toggle() -> None:
            state["open"] = not state["open"]
            if state["open"]:
                content.pack(fill="x", pady=(2, 6))
                btn.configure(text=f"▼ {title}")
            else:
                content.pack_forget()
                btn.configure(text=f"▶ {title}")

        btn = ttk.Button(head, text=f"▼ {title}", command=toggle)
        btn.pack(fill="x")
        toggle()      # 先关一次，再展开，保证初始状态和按钮文字一致

        for ln in lines:
            ttk.Label(content, text=ln, justify="left", wraplength=640,
                      font=("", 9)).pack(anchor="w", padx=8, pady=1)

    def _build_sections(self) -> None:
        parent = self.scroll.inner
        # （函数末尾会调 scroll.bind_wheel_tree()，见下面）
        self._fold(parent, "一、这工具是干嘛的", [
            "把 webm / mkv / mp4 等视频补帧，保留透明通道，输出统一是 webm。",
            "只做插帧，不做超分（分辨率跟源素材一致）。",
            "输出能直接塞回桌宠的素材目录。",
        ])
        self._fold(parent, "二、要准备什么（三个东西）", [
            "① Python 3.8 以上 —— 装的时候务必勾选「Add Python to PATH」",
            "② ffmpeg —— 把 ffmpeg.exe / ffprobe.exe 放到本工具目录下",
            "③ rife-ncnn-vulkan —— 整个文件夹放到本工具目录下",
            "",
            "国内直连 GitHub 常常打不开，下面的链接都加了中转前缀，直接用。",
        ])
        self._fold(parent, "三、文件怎么摆（目录树）", [
            "DSH-Pet-插帧工具包/",
            "  ├─ 插帧.py / gui.py       主程序和界面",
            "  ├─ 启动界面.bat            双击这个开图形界面",
            "  ├─ 一键插帧.bat            双击这个跑命令行版",
            "  ├─ config.json             所有参数都在这儿",
            "  ├─ ffmpeg.exe              你自己下的",
            "  ├─ ffprobe.exe             你自己下的",
            "  ├─ rife-ncnn-vulkan.exe    你自己下的",
            "  ├─ rife-v4.6/              rife 自带，整个放进来",
            "  ├─ input/                  素材丢这儿",
            "  └─ output/                 结果在这儿",
            "",
            "⚠️ 如果你下的是「懒人包 / 开箱即用版」，那里面已经配好了，",
            "   不用自己放。但那个版本可能比最新版落后，以版本号为准。",
        ])
        self._fold(parent, "四、下载链接（都走中转）", [
            "点下面的「复制」按钮，粘到浏览器地址栏就行。",
            "链接也在下面的输入框里，可以手动选中 Ctrl+C。",
        ])

        # 链接区（单独一块，带复制按钮 + 可选中文本）
        box = ttk.LabelFrame(parent, text=" 下载链接 ")
        box.pack(fill="x", padx=4, pady=3)
        for name, url in self.LINKS:
            row = ttk.Frame(box)
            row.pack(fill="x", padx=6, pady=2)
            ttk.Label(row, text=name, width=22).pack(side="left")
            e = ttk.Entry(row)
            e.insert(0, url)
            e.configure(state="readonly")
            e.pack(side="left", fill="x", expand=True, padx=4)
            ttk.Button(row, text="复制", width=6,
                       command=lambda u=url: copy_to_clipboard(self, u, self.lbl_copy)
                       ).pack(side="left")

        self._fold(parent, "五、常见问题", [
            "■ 双击没反应 / 一闪而过",
            "   先看有没有装 Python，装的时候要勾「Add Python to PATH」。",
            "■ 提示找不到 ffmpeg / rife",
            "   看上面第三节的目录树，把文件放到对的位置。",
            "■ 太慢了 / 风扇响",
            "   config.json 里把「性能模式」改成「省电」。",
            "■ 报 $'\\r': command not found",
            "   脚本行尾被 Windows 编辑器改坏了。跑一次 python 插帧.py 会自动修。",
            "■ 输出为什么是 .webm 不是 .mp4",
            "   带透明的视频只有 webm 装得下。mp4 的 H.264 没有透明通道。",
        ])

    def _toggle_auto(self) -> None:
        save_cfg({"启动时自动打开帮助": bool(self.var_auto.get())})

    def finish_build(self) -> None:
        """内容全部建好之后，把滚轮递归绑上去。"""
        try:
            self.scroll.bind_wheel_tree()
        except Exception:
            pass


# ================================================================== 主界面
class App(tk.Tk):
    """Main window: three work modes (interpolate / audio / both), a preset row and a live log pane.
    
    主窗口：三种工作模式（插帧 / 音频 / 视音）、一排预设，以及实时日志区。
    """
    def __init__(self) -> None:
        super().__init__()
        setup_platform()

        self.title(f"DSH Pet 素材定制插帧工具 {VERSION}")
        self._摆好窗口()
        self.minsize(900, 560)

        self.proc: subprocess.Popen | None = None
        # 工作模式：视频 / 音频 / 视音（Phase 2 骨架）。音频面板懒加载，见 _切换模式()
        self.var_模式 = tk.StringVar(value=str(load_cfg().get("工作模式") or "视频"))
        self._音频面板 = None
        self.msgq: queue.Queue[str] = queue.Queue()
        self.hcq: queue.Queue[dict] = queue.Queue()
        self.retry_high = False
        self.retry_one = False          # 「先试一个文件」用，只在内存里生效
        self._dst_touched = False
        self.src_fps_cache: float = 0.0
        self.health: dict = {}
        self.help_win: HelpWindow | None = None
        self.guide: GuidePopup | None = None

        self.var_src = tk.StringVar(value=str(HERE / "input"))
        self.var_dst = tk.StringVar(value=str(HERE / "output"))
        self.var_fps = tk.StringVar(value=str(self._cfg_fps()))

        self._build()
        self.after(80, self._drain)
        self.after(120, self._drain_health)
        self._log_head()

        # 轻量预检（只查文件路径，不跑显卡探测）放后台线程，别卡住启动
        threading.Thread(target=self._light_check, daemon=True).start()

        # 窗口要主动跳到最前面 —— 不然它会安静地开在别的窗口后面，
        # 用户看着屏幕没反应，以为"双击了没打开"。（踩过）
        self.after(60, self._raise_me)

        # 首次启动 → 冒一个非模态的引导小卡片
        if not load_cfg().get("新手引导已完成"):
            self.after(350, self._show_guide)
        # 用户勾过「启动自动打开帮助」
        if load_cfg().get("启动时自动打开帮助"):
            self.after(500, self.open_help)

    # ------------------------------------------------------------ 配置读写
    def _cfg_fps(self) -> int:
        try:
            v = int(float(load_cfg().get("目标帧率", 72)))
            if FPS_MIN <= v <= FPS_MAX:
                return v
        except Exception:
            pass
        return 72

    def _log_head(self) -> None:
        self._log(f"DSH Pet 素材定制插帧工具 {VERSION}")
        self._log("把素材放进「源素材文件夹」，选好输出、填个帧率，点「开始插帧」。")
        self._log("不清楚的看右上角 [?]。参数细节在 config.json，命令行版参数更全。")
        self._log("")

    # ------------------------------------------------------------ 界面搭建
    def _build(self) -> None:
        head = ttk.Frame(self)
        head.pack(fill="x", padx=12, pady=(10, 6))
        ttk.Label(head, text=f"DSH Pet 素材定制插帧工具  {VERSION}",
                  font=("", 15, "bold")).pack(side="left")
        self.btn_help = ttk.Button(head, text="?", width=3, command=self.open_help)
        self.btn_help.pack(side="right")
        ttk.Label(head, text="推荐是帮你填，不是替你选；填错了随时改。",
                  foreground="#666").pack(side="right", padx=10)

        # ── 模式：视频 / 音频 / 视音 ──────────────────────────────────
        # 说明：音频那一侧是**可插拔**的（gui_audio.py）。它加载失败也只是少一个面板，
        # 视频插帧主流程一个字都不受影响 —— 这是刻意做的隔离。
        modebar = ttk.Frame(self)
        modebar.pack(fill="x", padx=12, pady=(0, 2))
        ttk.Label(modebar, text="模式", foreground="#666").pack(side="left")
        for _名, _提示 in (("视频", "只做插帧，音频原样搬过去"),
                           ("音频", "只修音频，不碰画面"),
                           ("视音", "插帧 + 音频修复")):
            ttk.Radiobutton(modebar, text=_名, value=_名, variable=self.var_模式,
                            command=self._切换模式).pack(side="left", padx=(8, 0))
        self.lbl_mode_tip = ttk.Label(modebar, text="", foreground="#666")
        self.lbl_mode_tip.pack(side="left", padx=12)

        # 左右分栏；minsize 兜住，拖到最窄也不会把布局挤崩
        self.paned = ttk.PanedWindow(self, orient="horizontal")
        self.paned.pack(fill="both", expand=True, padx=12, pady=(0, 4))

        left = ttk.Frame(self.paned)
        right = ttk.Frame(self.paned)
        self.paned.add(left, weight=3)
        self.paned.add(right, weight=2)
        # 防布局崩坏：ttk.PanedWindow **不支持** per-pane 的 minsize
        # （只有 add/forget/insert/pane/panes/sashpos 这几个命令），
        # 所以用「拖过头就弹回来」的办法 —— 松手时如果分隔条越界，直接掰回去。
        self._sash_min = 420
        self.paned.bind("<ButtonRelease-1>", self._clamp_sash)
        self.after(140, self._init_sash)
        # 左栏里放两个容器：视频面板 / 音频面板，按模式 pack/forget 切换
        self.frame_日志 = ttk.Frame(left)
        # 先占住底部：视频 / 音频 / 视音 三种模式共用同一块运行日志，
        # 哪个模式都不许把它藏起来（它不跟着模式切）。
        self.frame_日志.pack(side="bottom", fill="x")
        self.frame_视频 = ttk.Frame(left)
        self.frame_音频 = ttk.Frame(left)
        self.frame_视频.pack(fill="both", expand=True)
        self._build_left(self.frame_视频)
        self._build_right(right)
        self.after(200, self._切换模式)

    # ------------------------------------------------------------ 窗口
    def _摆好窗口(self) -> None:
        """尺寸 + 位置一起算好，保证整扇窗（尤其最下面的「运行日志」）在屏幕里。

        实测踩过：只写 `geometry("1080x640")` 不给位置，窗口管理器会按它
        自己的记忆摆 —— 有一次被摆到 y=474，640 高的窗子下沿到了 1114，
        屏幕才 1080，**最底下那块运行日志直接被切掉**，
        用户看到的现象就是"日志怎么没了"。
        """
        屏宽 = max(640, self.winfo_screenwidth())
        屏高 = max(480, self.winfo_screenheight())
        宽 = min(1080, 屏宽 - 40)
        高 = min(860, 屏高 - 80)
        if 宽 < 900:            # 小屏幕上优先保宽（左栏内容多）
            宽 = min(900, 屏宽 - 20)
        x = max(10, (屏宽 - 宽) // 2)
        y = max(30, (屏高 - 高) // 2)
        self.geometry(f"{宽}x{高}+{x}+{y}")

    def _切换模式(self) -> None:
        """视频 / 音频 / 视音 三态切换。

        音频面板是**懒加载**的：只有真的切过去才 import gui_audio。
        加载失败也只在提示行里说一句，绝不弹窗、绝不影响插帧主流程。
        """
        模式 = self.var_模式.get()
        try:
            save_cfg({"工作模式": 模式})
        except Exception:
            pass
        if 模式 == "视频":
            self.frame_音频.pack_forget()
            self.frame_视频.pack(fill="both", expand=True)
            self.lbl_mode_tip.configure(text="只做视频插帧，音频原样搬过去")
            return
        if self._音频面板 is None:
            try:
                import gui_audio
                self._音频面板 = gui_audio.挂载(self.frame_音频, self, 紧凑=(模式 == "视音"))
            except Exception as exc:
                self.lbl_mode_tip.configure(text=f"音频面板加载失败（{exc}）—— 插帧照常可用")
                return
        if 模式 == "视音":
            self.frame_视频.pack(fill="both", expand=True)
            self.frame_音频.pack(fill="x", pady=(4, 0))
            self.lbl_mode_tip.configure(text="插帧 + 音频修复（音频设置见下方面板）")
        else:
            self.frame_视频.pack_forget()
            self.frame_音频.pack(fill="both", expand=True)
            self.lbl_mode_tip.configure(text="只修音频，不碰画面")

        # 从「音频」切到「视音」（或反过来）时**不重建**面板，就地换挡 ——
        # 重建会把刚填的参数丢掉。不换挡的话，视音模式下那块面板还留着
        # 自己的「开始音频修复」按钮，点下去只会修声音、不插帧。
        换挡 = getattr(self._音频面板, "设紧凑", None)
        if callable(换挡):
            try:
                换挡(模式 == "视音")
            except Exception:
                pass
        # 新手卡片还开着的话，文案也跟着换（已经关掉/销毁的就不用管）
        if self.guide is not None:
            try:
                if self.guide.winfo_exists():
                    self.guide.设模式(模式)
            except Exception:
                pass

    def _init_sash(self) -> None:
        try:
            self.paned.sashpos(0, max(self._sash_min,
                                      int(self.paned.winfo_width() * 0.58)))
        except Exception:
            pass

    def _clamp_sash(self, _evt=None) -> None:
        try:
            if self.paned.sashpos(0) < self._sash_min:
                self.paned.sashpos(0, self._sash_min)
        except Exception:
            pass

    # ------------------------------------------------------------ 左面板
    def _build_left(self, root: ttk.Frame) -> None:
        pad = {"padx": 8, "pady": 4}

        box = ttk.LabelFrame(root, text=" 文件位置 ")
        box.pack(fill="x", pady=4)

        r1 = ttk.Frame(box); r1.pack(fill="x", **pad)
        ttk.Label(r1, text="源素材文件夹", width=12).pack(side="left")
        ttk.Entry(r1, textvariable=self.var_src).pack(side="left", fill="x",
                                                       expand=True, padx=6)
        ttk.Button(r1, text="选择…", width=8, command=self._pick_src).pack(side="left")

        r2 = ttk.Frame(box); r2.pack(fill="x", **pad)
        ttk.Label(r2, text="输出文件夹", width=12).pack(side="left")
        e_dst = ttk.Entry(r2, textvariable=self.var_dst)
        e_dst.pack(side="left", fill="x", expand=True, padx=6)
        e_dst.bind("<KeyRelease>", self._dst_edited)
        ttk.Button(r2, text="选择…", width=8, command=self._pick_dst).pack(side="left")

        box2 = ttk.LabelFrame(root, text=" 参数 ")
        box2.pack(fill="x", pady=4)
        r3 = ttk.Frame(box2); r3.pack(fill="x", **pad)
        ttk.Label(r3, text="目标帧率", width=12).pack(side="left")
        ttk.Entry(r3, textvariable=self.var_fps, width=8).pack(side="left")
        ttk.Label(r3, text=f"  想让它多少帧就填多少（建议 {FPS_SUGGEST}）",
                  foreground="#666").pack(side="left")

        ttk.Label(box2, text="快速预设（只帮你填数字，不锁死输入框，随时能改）：",
                  foreground="#666").pack(anchor="w", padx=8, pady=(2, 0))

        pr = ttk.Frame(box2); pr.pack(fill="x", padx=8, pady=(2, 8))
        self.preset_btns: dict[str, ttk.Button] = {}
        for name, mult, tip in PRESETS:
            b = ttk.Button(pr, text=name, width=11,
                           command=lambda n=name: self._apply_preset(n))
            b.pack(side="left", padx=3)
            b.bind("<Enter>", lambda _e, t=tip: self._state(t))
            b.bind("<Leave>", lambda _e: self._state("待命中"))
            self.preset_btns[name] = b
        self.lbl_preset = ttk.Label(box2, text="（素材帧率还没探测，点一下预设就知道）",
                                    foreground="#999")
        self.lbl_preset.pack(anchor="w", padx=8, pady=(0, 8))

        r4 = ttk.Frame(root); r4.pack(fill="x", pady=8)
        self.btn_start = ttk.Button(r4, text="▶  开始插帧", command=self.on_start)
        self.btn_start.pack(side="left", ipadx=18, ipady=6)
        self.btn_open = ttk.Button(r4, text="📂 打开输出文件夹", state="disabled",
                                   command=self._open_out)
        self.btn_open.pack(side="left", padx=8)
        self.lbl_state = ttk.Label(r4, text="待命中", foreground="#666")
        self.lbl_state.pack(side="left", padx=12)

        # ⚠️ 「运行日志」不建在视频页里，而是建在这个**三种模式共用**的底栏里。
        # 原来它属于 frame_视频，一切到「音频」模式整块就被 pack_forget 掉了，
        # 结果日志内容照写、用户一个字的看不到（既定约束：日志每个板块都要）。
        日志父 = getattr(self, "frame_日志", root)
        logbox = ttk.LabelFrame(日志父, text=" 运行日志 ")
        logbox.pack(fill="both", expand=True, pady=(0, 4))
        self.txt = tk.Text(logbox, height=12, wrap="none", state="disabled",
                           background="#111", foreground="#ddd",
                           insertbackground="#ddd", font=("monospace", 9))
        sb = ttk.Scrollbar(logbox, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.txt.pack(side="left", fill="both", expand=True)
        self.txt.tag_configure("warn", foreground="#e8c34a")    # 黄色：小提醒
        self.txt.tag_configure("bad", foreground="#ff6b6b")     # 红色：严重

    # ------------------------------------------------------------ 右面板
    def _build_right(self, root: ttk.Frame) -> None:
        ttk.Label(root, text="环境自检（只报信息，不改业务流程）",
                  foreground="#666").pack(anchor="w", padx=6, pady=(6, 2))

        dev = ttk.LabelFrame(root, text=" 显示设备 ")
        dev.pack(fill="x", padx=4, pady=4)
        self.txt_dev = tk.Text(dev, height=6, wrap="none", state="disabled",
                               background="#f7f7f7", relief="flat", font=("monospace", 9))
        self.txt_dev.pack(fill="x", padx=6, pady=6)

        spec = ttk.LabelFrame(root, text=" 素材规格 ")
        spec.pack(fill="x", padx=4, pady=4)
        self.txt_spec = tk.Text(spec, height=6, wrap="none", state="disabled",
                                background="#f7f7f7", relief="flat", font=("monospace", 9))
        self.txt_spec.pack(fill="x", padx=6, pady=6)

        est = ttk.LabelFrame(root, text=" 预估（点开始插帧后出） ")
        est.pack(fill="both", expand=True, padx=4, pady=(4, 8))
        cols = ("fps", "mult", "frames", "sec", "size")
        self.tree = ttk.Treeview(est, columns=cols, show="headings", height=9)
        for c, t, w in (("fps", "目标", 62), ("mult", "倍数", 56),
                        ("frames", "输出帧数", 76), ("sec", "预估耗时", 76),
                        ("size", "预估体积", 76)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=6, pady=(6, 2))
        self.tree.tag_configure("safe", foreground="#2a7")
        self.tree.tag_configure("risky", foreground="#c80")
        ttk.Label(est, text="基于本机实测外推，不包含桌宠渲染负载",
                  foreground="#999").pack(anchor="w", padx=6, pady=(0, 6))

    # ------------------------------------------------------------ 小动作
    def _log(self, text: str, tag: str = "") -> None:
        self.txt.configure(state="normal")
        self.txt.insert("end", text + "\n", tag)
        self.txt.see("end")
        self.txt.configure(state="disabled")

    def _state(self, text: str) -> None:
        self.lbl_state.configure(text=text)

    def _set_text(self, widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _pick(self, var: tk.StringVar, title: str, after=None) -> None:
        d = filedialog.askdirectory(title=title, initialdir=var.get() or str(HERE))
        if d:
            var.set(d)
            if after is not None:
                after(d)

    def _pick_src(self) -> None:
        def follow(src: str) -> None:
            self.src_fps_cache = 0.0
            if not self._dst_touched:
                p = Path(src)
                base = p if p.is_dir() else p.parent
                self.var_dst.set(str(base.parent / (base.name + "_插帧输出")))
            if not load_cfg().get("新手引导已完成"):
                return
        self._pick(self.var_src, "选择源素材文件夹", follow)

    def _pick_dst(self) -> None:
        self._dst_touched = True
        self._pick(self.var_dst, "选择输出文件夹")

    def _dst_edited(self, _evt=None) -> None:
        self._dst_touched = True

    def _open_out(self) -> None:
        p = Path(self.var_dst.get())
        if not p.is_dir():
            messagebox.showinfo("提示", "输出文件夹还不存在，跑一次就有了。")
            return
        try:
            if os.name == "nt":
                os.startfile(p)          # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p)])
        except Exception as exc:
            messagebox.showwarning("打不开", f"系统不允许打开这个文件夹：{exc}\n\n路径：{p}")

    def _raise_me(self) -> None:
        """把自己弹到最前面。用完立刻撤掉 topmost，不然会一直压着别人。"""
        try:
            self.deiconify()
            self.lift()
            self.attributes("-topmost", True)
            self.after(700, lambda: self.attributes("-topmost", False))
            self.focus_force()
        except Exception:
            pass

    def _show_guide(self) -> None:
        try:
            self.guide = GuidePopup(self)
            # 卡片是"跟着模式走"的：启动时停在哪一页，就讲哪一页的步骤
            self.guide.设模式(self.var_模式.get())
        except Exception:
            pass

    def open_help(self) -> None:
        if self.help_win is not None and self.help_win.winfo_exists():
            self.help_win.lift()
            return
        self.help_win = HelpWindow(self)

    # ------------------------------------------------------------ 预设按钮
    def _ensure_src_fps(self) -> float:
        """拿到源素材的帧率（取第一个文件）。走底层 probe，不自己写解析。"""
        if self.src_fps_cache > 0:
            return self.src_fps_cache
        if CORE_MOD is None:
            return 0.0
        try:
            cfg = CORE_MOD.load_config()
            _ff, ffprobe = CORE_MOD.find_ffmpeg(cfg)
            root = Path(self.var_src.get().strip())
            files = sorted(p for p in root.rglob("*")
                           if p.is_file()
                           and p.suffix.lower() in CORE_MOD.VIDEO_EXTS)
            if not files:
                return 0.0
            info = CORE_MOD.probe(ffprobe, files[0])
            self.src_fps_cache = float(info.get("fps") or 0.0)
        except Exception:
            return 0.0
        return self.src_fps_cache

    def _apply_preset(self, name: str) -> None:
        mult = next(m for n, m, _ in PRESETS if n == name)
        src = self._ensure_src_fps()
        if src <= 0:
            messagebox.showinfo(
                "还没探到素材帧率",
                "预设是「按你素材的真实帧率算整数倍」的，所以得先知道源帧率。\n\n"
                "请先确认「源素材文件夹」里有素材，再点一次。\n"
                "（也可以直接在输入框里手填数字）")
            return
        target = int(round(src * mult))
        if target > FPS_MAX:
            target = FPS_MAX
        self.lbl_preset.configure(
            text=f"源 {src:g}fps × {mult} = {target}fps"
                 f"（{'整数倍 ✔' if abs(src * mult - round(src * mult)) < 0.01 else '非整数倍'}）")
        self.var_fps.set(str(target))     # 只回填，不锁定输入框

        if name in HIGH_PRESETS and self.health.get("soft_gpu"):
            messagebox.showwarning(
                "软件渲染，慢很多",
                "这台机器现在只有软件渲染（llvmpipe）能用。\n"
                "插帧本身会跑得极慢，再往上堆帧率只会更慢。\n\n"
                "先装好显卡驱动再用这些高帧预设吧。")
            return

        if name == "全都拉满":
            self._confirm_max(target)

    def _confirm_max(self, target: int) -> None:
        dlg = tk.Toplevel(self)
        dlg.title("确认：全都拉满")
        dlg.transient(self)
        dlg.resizable(False, False)
        dlg.configure(padx=16, pady=12)
        ttk.Label(dlg, text=f"要插到 {target}fps —— 这会明显吃 CPU、风扇会响。",
                  font=("", 11, "bold")).pack(anchor="w")
        ttk.Label(dlg, text=(
            "默认安全线是 3 倍，这个已经超过很多了。\n"
            "画质上没测出鬼影，但样本不多，风险自负。\n\n"
            "不确定的话，建议先点「先试一个文件」。"),
            justify="left").pack(anchor="w", pady=(8, 10))
        row = ttk.Frame(dlg); row.pack(fill="x")

        def go(one_file: bool) -> None:
            dlg.destroy()
            if one_file:
                # 只在内存里生效，绝不写进 config.json
                self.retry_one = True
                self._log("（已选「先试一个文件」：这次只跑 1 个素材，不改配置）", "warn")
            self.on_start()

        ttk.Button(row, text="先试一个文件", command=lambda: go(True)).pack(side="left")
        ttk.Button(row, text="就这样跑全部", command=lambda: go(False)).pack(side="left", padx=8)
        ttk.Button(row, text="算了", command=dlg.destroy).pack(side="right")

    # ------------------------------------------------------------ 后台：轻量预检
    def _light_check(self) -> None:
        """启动时的轻量预检：只查文件路径，不跑显卡探测（那个慢）。"""
        out = {"stage": "light", "lines": []}
        if CORE_MOD is None:
            out["lines"].append("✘ 读不到 插帧.py（gui.py 要和它放同一个目录）")
            self.hcq.put(out)
            return
        try:
            cfg = CORE_MOD.load_config()
            try:
                ffmpeg, ffprobe = CORE_MOD.find_ffmpeg(cfg)
                out["lines"].append(f"✔ ffmpeg   {ffmpeg}")
            except Exception as exc:
                out["lines"].append(f"✘ ffmpeg   {exc}")
            try:
                rife, _md = CORE_MOD.find_rife(cfg, str(cfg.get("插帧模型") or "rife-v4.6"))
                out["lines"].append(f"✔ rife     {rife}")
            except Exception as exc:
                out["lines"].append(f"✘ rife     {exc}")
            if "✘ rife" in "\n".join(out["lines"]):
                out["lines"].append("")
                out["lines"].append("  → rife 没找到。把 rife-ncnn-vulkan 整个文件夹放进")
                out["lines"].append("     本工具目录，或在 config.json 里填「rife可执行文件路径」。")
                out["lines"].append("     下载（国内中转）：https://gh-proxy.com/https://github.com/nihui/rife-ncnn-vulkan/releases")
                out["lines"].append("     点右上角 [?] 有帮助面板，里面有「复制」按钮。")
            cpus, note = CORE_MOD.detect_cpus()
            out["lines"].append(f"· 电脑核数 {cpus} {note}".rstrip())
            _d, tnote = CORE_MOD.pick_temp_dir(cfg)
            out["lines"].append("· 中间帧 " + tnote.splitlines()[0])
        except Exception as exc:
            out["lines"].append(f"✘ 预检出错：{exc}")
        out["lines"].append("")
        out["lines"].append("（完整的显卡体检在点「开始插帧」后跑）")
        self.hcq.put(out)

    # ------------------------------------------------------------ 后台：合并体检
    def _heavy_check(self, src: Path) -> None:
        """点「开始插帧」后触发的合并体检：显卡探测 + 素材采样 + 预估表。"""
        out = {"stage": "heavy", "lines": [], "spec": "", "est": [], "soft_gpu": False}
        if CORE_MOD is None:
            out["lines"] = ["✘ 底层模块加载失败"]
            self.hcq.put(out)
            return
        try:
            cfg = CORE_MOD.load_config()
            model = str(cfg.get("插帧模型") or "rife-v4.6")
            rife, _md = CORE_MOD.find_rife(cfg, model)
            devs, tail = CORE_MOD.check_gpus(rife, model)
            if not devs:
                out["lines"] = [f"⚠️ 没问出可用显示设备（{tail or '没有输出'}）",
                                "   多半是显卡驱动没装好，会掉到 CPU 软件渲染，极慢。"]
                out["soft_gpu"] = True
            else:
                gpu = cfg.get("使用第几块显卡", "auto")
                picked = None
                if str(gpu).strip().lower() in ("auto", "", "自动", "默认"):
                    idx, why = CORE_MOD.pick_best_gpu(devs)
                    idx = 0 if idx is None else idx
                else:
                    idx = int(gpu)
                for i, nm in devs:
                    tag = "软渲染·极慢" if CORE_MOD.is_soft(nm) else (
                        "核显" if CORE_MOD.is_integrated(nm) else "独显")
                    mark = "  ← 用这块" if i == idx else ""
                    out["lines"].append(f"[{i}] {nm}　〔{tag}〕{mark}")
                picked = dict(devs).get(idx)
                if picked and CORE_MOD.is_soft(picked):
                    out["soft_gpu"] = True
            # 素材采样
            _ff, ffprobe = CORE_MOD.find_ffmpeg(cfg)
            files = sorted(p for p in src.rglob("*")
                           if p.is_file() and p.suffix.lower() in CORE_MOD.VIDEO_EXTS)
            if files:
                info = CORE_MOD.probe(ffprobe, files[0])
                src_fps = float(info.get("fps") or 0) or 24.0
                self.src_fps_cache = src_fps
                out["spec"] = (
                    f"目录共 {len(files)} 个素材（只采样第一个）\n"
                    f"第一个：{files[0].name}\n"
                    f"{info.get('w')}×{info.get('h')}  {src_fps:.2f}fps  "
                    f"{info.get('frames')} 帧  {info.get('dur', 0):.2f} 秒\n"
                    f"容器 {info.get('container') or '?'}  编码 {info.get('codec') or '?'}\n"
                    f"音轨 {info.get('audio') or '无'}   "
                    f"{'带透明通道' if info.get('alpha') else '不透明'}")
                out["est"] = self._estimate(info, cfg)
                out["info"] = info
            else:
                out["spec"] = "这个文件夹里没有能处理的素材"
        except Exception as exc:
            out["lines"] = [f"✘ 体检出错：{exc}"]
        self.hcq.put(out)

    def _estimate(self, info: dict, cfg: dict) -> list[tuple]:
        """按固定 9 档算预估。只变帧率一个变量，不是笛卡尔积。"""
        src = float(info.get("fps") or 0) or 24.0
        frames = int(info.get("frames") or 0)
        px = int(info.get("w") or 0) * int(info.get("h") or 0) or REF_PX
        scale = max(0.15, px / REF_PX)
        alpha_k = 1.0 if info.get("alpha") else 0.72
        safe_max = float(cfg.get("安全倍数上限") or 3.0)
        rows = []
        for t in EST_TARGETS:
            mult = t / src
            if frames and t <= src + 0.01:
                rows.append((t, mult, 0, 0.0, 0.0, "skip"))
                continue
            out_frames = max(2, round(frames * t / src)) if frames else 0
            sec = (BASE_SEC + out_frames * SEC_PER_FRAME * scale) * alpha_k
            mb = out_frames * MB_PER_FRAME * scale * alpha_k
            rows.append((t, mult, out_frames, sec, mb,
                         "safe" if mult <= safe_max else "risky"))
        return rows

    def _drain_health(self) -> None:
        try:
            while True:
                out = self.hcq.get_nowait()
                stage = out.get("stage")
                if stage == "light":
                    self._set_text(self.txt_dev, "\n".join(out["lines"]))
                else:
                    if out["lines"]:
                        self._set_text(self.txt_dev, "\n".join(out["lines"]))
                    if out.get("spec"):
                        self._set_text(self.txt_spec, out["spec"])
                    self.tree.delete(*self.tree.get_children())
                    for t, mult, fr, sec, mb, tag in out.get("est", []):
                        if tag == "skip":
                            self.tree.insert("", "end", values=(f"{t}", f"{mult:.2f}×",
                                                                "跳过", "—", "—"),
                                             tags=("risky",))
                            continue
                        self.tree.insert("", "end",
                                         values=(f"{t}", f"{mult:.2f}×", f"{fr}",
                                                 f"{sec:.0f} 秒", f"{mb:.2f} MB"),
                                         tags=(tag,))
                    self._apply_preset_availability(out.get("soft_gpu", False))
        except queue.Empty:
            pass
        self.after(120, self._drain_health)

    def _apply_preset_availability(self, soft: bool) -> None:
        """软件渲染时把高帧预设置灰。只影响按钮，不影响业务流程。"""
        self.health["soft_gpu"] = soft
        for name in HIGH_PRESETS:
            b = self.preset_btns.get(name)
            if b is None:
                continue
            try:
                b.configure(state=("disabled" if soft else "normal"))
            except Exception:
                pass
        if soft:
            self._log("⚠️ 检测到软件渲染（llvmpipe）：几个高帧预设已置灰。", "warn")

    # ------------------------------------------------------------ 点「开始」
    def on_start(self) -> None:
        if self.proc is not None:
            return

        src = Path(self.var_src.get().strip())
        dst = self.var_dst.get().strip()
        raw = self.var_fps.get().strip()

        # ① 帧率校验（红线：非法输入校验完整保留）
        if not raw.isdigit():
            messagebox.showerror("输入不合法",
                                 f"输入不合法，请填数字（建议 {FPS_SUGGEST}）！")
            return
        fps = int(raw)
        if fps < FPS_MIN or fps > FPS_MAX:
            messagebox.showerror(
                "输入不合法",
                f"输入不合法，请填数字（建议 {FPS_SUGGEST}）！\n\n"
                f"（允许范围 {FPS_MIN} ~ {FPS_MAX}，你填的是 {fps}）")
            return

        # ② 路径校验（业务判断走底层常量，不自己再抄一份后缀表）
        if not src.is_dir():
            messagebox.showerror("找不到文件夹", f"源素材文件夹不存在：\n{src}")
            return
        exts = core_const("VIDEO_EXTS", (".webm",))
        if not any(p.is_file() and p.suffix.lower() in exts for p in src.rglob("*")):
            messagebox.showerror(
                "没有素材",
                f"这个文件夹里没找到能处理的素材：\n{src}\n\n"
                f"认得这些后缀：{' '.join(exts)}\n"
                "先把要插帧的素材放进去。")
            return

        save_cfg({"目标帧率": fps})
        self.retry_high = False
        self._launch(src, dst, fps)

    # ------------------------------------------------------------ 起子进程
    def _launch(self, src: Path, dst: str, fps: int) -> None:
        self._log("=" * 62)
        self._log(f"  DSH Pet 素材定制插帧工具 {VERSION}")
        self._log(f"  目标帧率 {fps}    源：{src}")
        self._log("=" * 62)

        # 合并体检跑在后台线程，界面不会卡
        threading.Thread(target=self._heavy_check, args=(src,), daemon=True).start()

        cmd = [child_python(), "-u", str(CORE), str(src), "--帧率", str(fps)]
        if dst:
            cmd += ["--输出", dst]
        if self.retry_high:
            cmd += ["--允许高风险"]
        if self.retry_one:
            cmd += ["--试跑", "1"]
            self.retry_one = False          # 只影响这一次，不进 config

        try:
            self.proc = subprocess.Popen(
                cmd, cwd=str(HERE), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                errors="replace", bufsize=1, env=child_env(),
                **win_flags())
        except Exception as exc:
            self.proc = None
            messagebox.showerror("启动失败", str(exc))
            return

        self.btn_start.configure(state="disabled")
        self._state("正在插帧…（可以去干别的，别关窗口）")
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            self.msgq.put(line.rstrip("\n"))
        self.proc.wait()
        self.msgq.put(f"__EXIT__{self.proc.returncode}")

    def _drain(self) -> None:
        try:
            while True:
                line = self.msgq.get_nowait()
                if line.startswith("__EXIT__"):
                    self._finish(int(line[len("__EXIT__"):]))
                elif line.startswith("__AUDIO_DONE__"):
                    self._state("✅ 全部完成（插帧 + 音轨）")
                else:
                    tag = ""
                    if "⚠️" in line:
                        tag = "warn"
                    self._log(line, tag)
        except queue.Empty:
            pass
        self.after(80, self._drain)

    def _音频后处理(self, 处理) -> None:
        """（后台线程）跑音频后处理；跑完通过 msgq 回报，不直接碰界面。"""
        try:
            处理()
            self.msgq.put("__AUDIO_DONE__")
        except Exception as exc:                       # 音频这层怎么坏都不许影响插帧
            self.msgq.put(f"⚠️ 音频后处理出错（插帧结果不受影响）：{exc}")
            self.msgq.put("__AUDIO_DONE__")

    # ------------------------------------------------------------ 收尾
    def _finish(self, code: int) -> None:
        self.proc = None
        self.btn_start.configure(state="normal")

        if code == 0:
            self.btn_open.configure(state="normal")
            # 「视音」模式：插帧跑完之后，顺手把输出视频的音轨也修一遍。
            # 音频那套全在 gui_audio 里，这里只负责"什么时候叫它"——没有链路就不叫。
            后续 = None
            if self.var_模式.get() == "视音" and self._音频面板 is not None:
                try:
                    后续 = self._音频面板.造视频后处理器(self.var_dst.get().strip())
                except Exception as exc:
                    self._log(f"⚠️ 音频后处理没能启动：{exc}", "warn")
            if 后续 is None:
                self._state("✅ 完成")
                messagebox.showinfo("跑完了", "插帧完成！\n结果就在你选的输出文件夹里。")
            else:
                self._state("✅ 插帧完成，正在换音轨…")
                self._log("\n插帧完成。接着按「视音」模式修音轨（输出方式=视频）…\n")
                threading.Thread(target=self._音频后处理, args=(后续,), daemon=True,
                                 name="pet-audio-after-video").start()
        elif code == 3:
            # 红线：安全倍数拦截逻辑完整保留，只是把它弹回给用户决定
            self._state("被安全拦截")
            ok = messagebox.askyesno(
                "帧率超出默认安全范围",
                "这个帧率超过了默认的安全倍数（默认 3 倍）。\n\n"
                "实测在 640×360 的 Q 版素材上没看出明显鬼影，\n"
                "但样本不多、细线条素材没覆盖，而且 CPU 会明显变热。\n\n"
                "要强行跑一次吗？")
            if ok:
                self.retry_high = True
                self._log("\n（按你的要求，跳过安全拦截，重跑一次）\n", "warn")
                self._launch(Path(self.var_src.get().strip()),
                             self.var_dst.get().strip(),
                             int(self.var_fps.get().strip()))
            else:
                self._state("已取消")
        else:
            self._state(f"❌ 出错了（退出码 {code}）")
            messagebox.showerror(
                "出错了",
                f"退出码 {code}，具体原因看日志框。\n\n"
                "小提示：已经处理好的文件下次会自动跳过，直接再点一次就行。")


# ================================================================== 入口
def child_python() -> str:
    exe = sys.executable or "python"
    if os.name == "nt":
        p = Path(exe)
        if p.name.lower() == "pythonw.exe":
            cand = p.with_name("python.exe")
            if cand.exists():
                return str(cand)
    return exe


def child_env() -> dict:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def win_flags() -> dict:
    """Windows：子进程不弹黑框（不加的话批处理时会闪几十个窗口）。"""
    if os.name != "nt":
        return {}
    return {"creationflags": int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))}


def main() -> int:
    if not CORE.is_file():
        print(f"找不到 {CORE}，请把 gui.py 和 插帧.py 放在同一个目录里。")
        return 1
    App().mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
