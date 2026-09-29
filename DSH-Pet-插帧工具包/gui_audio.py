#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DSH Pet 插帧工具 · 音频修复面板（GUI 骨架 · Phase 2）

这个文件是**可插拔**的：gui.py 只在用户切到「音频 / 视音」模式时才 import 它，
import/构建失败也只是少一个面板，绝不影响视频插帧主流程。

设计要点：
    · 面板只做三件事：攒配置 → 调 audio_fix.run_audio_pipeline() → 显示结果
    · **面板不知道模型怎么跑**（DSP 在 audio_fix 里，AI 在外挂子进程里）
    · 真正的处理全在后台线程里跑，界面靠 after() 轮询刷新，不卡
    · 模型可用性来自外挂自检（子进程），不可用的档位就置灰并说明缺什么
"""

from __future__ import annotations

import importlib.util
import json
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

HERE = Path(__file__).resolve().parent

# 三档链路的组成（顺序就是执行顺序：便宜的先跑，贵的少跑）
档位说明 = (
    ("粗修", "dsp", "纯 FFmpeg 滤镜：去闷 + 裁静音 + 响度 + 限幅。零依赖，秒级。"),
    ("精修", "轻量AI", "DPDFNet2 / GTCRN 一类轻量语音模型。需要外挂依赖。"),
    ("超精修", "重度AI", "FRCRN 一类高保真模型。依赖更大、更吃算力。"),
)
轻量模型候选 = ("dpdfnet2", "gtcrn")
重度模型候选 = ("frcrn",)


def _载入音频本体():
    """按路径加载 audio_fix.py —— 不在模块顶层 import，免得拖慢/拖坏启动。"""
    if "audio_fix" in sys.modules:
        return sys.modules["audio_fix"]
    路径 = HERE / "audio_fix.py"
    if not 路径.is_file():
        raise RuntimeError(f"找不到 {路径}")
    spec = importlib.util.spec_from_file_location("audio_fix", 路径)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules["audio_fix"] = mod
    return mod


class 音频面板(ttk.Frame):
    """The audio-repair panel. `app` may be None when testing it standalone.
    
    音频修复面板。app 可以是 None（单独测试时用）。
    """

    def __init__(self, master: tk.Misc, app=None, 紧凑: bool = False) -> None:
        super().__init__(master)
        self.app = app
        self.紧凑 = 紧凑
        self._跑着 = False
        self._模型可用: dict[str, tuple[bool, str]] = {}
        # 后台线程**绝不直接碰控件**（Tkinter 不是线程安全的，跨线程 after() 会静默失效）。
        # 统一丢进这个小队列，由 GUI 线程定时取出来应用 —— 和 gui.py 自己的 msgq/_drain 一个路子。
        self._界面队列: queue.Queue[tuple] = queue.Queue()
        self._建界面()
        self.after(120, self._轮询界面)
        self._刷新模型可用性()

    # ------------------------------------------------------------------ 界面
    def _读配置种子(self) -> dict:
        """面板初始值尽量跟 config.json 对齐（只读 JSON，不 import 音频本体）。"""
        try:
            raw = (HERE / "config.json").read_text(encoding="utf-8")
            d = json.loads(raw)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def _建界面(self) -> None:
        pad = {"padx": 8, "pady": 4}
        种子 = self._读配置种子()

        框 = ttk.LabelFrame(self, text=" 音频修复 ")
        框.pack(fill="both", expand=True, pady=4)

        # 源 / 输出
        # ⚠️ var_源 **无论紧凑与否都要建** —— 视音切回音频时还得用它。
        #    省掉它的话，「开始」里那句 hasattr(self, "var_源") 会误判成紧凑模式，
        #    于是跑去走视频流程（不修声音），而且一声不响。
        self.var_源 = tk.StringVar(value=str(getattr(self.app, "var_src", None).get() if getattr(self.app, "var_src", None) else ""))
        self.var_出 = tk.StringVar(value=str(getattr(self.app, "var_dst", None).get() if getattr(self.app, "var_dst", None) else (HERE / "output")))
        self._行_源 = ttk.Frame(框)
        if not self.紧凑:
            self._行_源.pack(fill="x", **pad)
            ttk.Label(self._行_源, text="源音频/文件夹", width=14).pack(side="left")
            ttk.Entry(self._行_源, textvariable=self.var_源).pack(side="left", fill="x", expand=True, padx=6)
            ttk.Button(self._行_源, text="选文件…", width=9, command=self._选文件).pack(side="left")
            ttk.Button(self._行_源, text="选文件夹…", width=10, command=self._选文件夹).pack(side="left", padx=4)
        r2 = self._行_出 = ttk.Frame(框); r2.pack(fill="x", **pad)
        ttk.Label(r2, text="输出文件夹", width=14).pack(side="left")
        ttk.Entry(r2, textvariable=self.var_出).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(r2, text="选择…", width=9, command=self._选出).pack(side="left")

        # 链路三档
        链路框 = ttk.LabelFrame(框, text=" 处理链路（可单跑，也可串联） ")
        链路框.pack(fill="x", **pad)
        链种子 = 种子.get("音频修复_处理链路") if isinstance(种子.get("音频修复_处理链路"), list) else []
        if not 链种子:
            链种子 = ["dsp"] if str(种子.get("音频修复模型") or "dsp") not in ("无", "") else []
        self.var_粗修 = tk.BooleanVar(value="dsp" in 链种子)
        self.var_精修 = tk.BooleanVar(value=any(x in 链种子 for x in 轻量模型候选))
        self.var_超精修 = tk.BooleanVar(value=any(x in 链种子 for x in 重度模型候选))
        self.chk_粗修 = ttk.Checkbutton(链路框, text="粗修（DSP·零依赖）", variable=self.var_粗修,
                                        command=self._刷新链路预览)
        self.chk_粗修.pack(anchor="w", padx=8, pady=(6, 0))
        self.chk_精修 = ttk.Checkbutton(链路框, text="精修（轻量 AI）", variable=self.var_精修,
                                        command=self._刷新链路预览)
        self.chk_精修.pack(anchor="w", padx=8)
        self.chk_超精修 = ttk.Checkbutton(链路框, text="超精修（重度 AI）", variable=self.var_超精修,
                                          command=self._刷新链路预览)
        self.chk_超精修.pack(anchor="w", padx=8)

        模型行 = ttk.Frame(链路框); 模型行.pack(fill="x", padx=8, pady=(2, 4))
        ttk.Label(模型行, text="精修模型").pack(side="left")
        self.var_轻量模型 = tk.StringVar(
            value=next((x for x in 链种子 if x in 轻量模型候选), 轻量模型候选[0]))
        ttk.Combobox(模型行, textvariable=self.var_轻量模型, values=list(轻量模型候选),
                     width=12, state="readonly").pack(side="left", padx=4)
        ttk.Label(模型行, text="超精修模型").pack(side="left", padx=(8, 0))
        self.var_重度模型 = tk.StringVar(
            value=next((x for x in 链种子 if x in 重度模型候选), 重度模型候选[0]))
        ttk.Combobox(模型行, textvariable=self.var_重度模型, values=list(重度模型候选),
                     width=10, state="readonly").pack(side="left", padx=4)

        self.lbl_链路 = ttk.Label(链路框, text="", foreground="#0a6")
        self.lbl_链路.pack(anchor="w", padx=8)
        self.lbl_外挂 = ttk.Label(链路框, text="外挂自检中…", foreground="#666", wraplength=560,
                                  justify="left")
        self.lbl_外挂.pack(anchor="w", padx=8, pady=(0, 6))

        # 参数
        参 = ttk.Frame(框); 参.pack(fill="x", **pad)
        ttk.Label(参, text="强度").pack(side="left")
        self.var_强度 = tk.StringVar(value=str(种子.get("音频修复_强度") or "标准"))
        ttk.Combobox(参, textvariable=self.var_强度, values=["轻", "标准", "重"], width=6,
                     state="readonly").pack(side="left", padx=4)
        ttk.Label(参, text="EQ 风格").pack(side="left", padx=(8, 0))
        self.var_风格 = tk.StringVar(value=str(种子.get("音频修复_EQ风格") or "环境音"))
        ttk.Combobox(参, textvariable=self.var_风格, values=["语音", "环境音"], width=8,
                     state="readonly").pack(side="left", padx=4)
        ttk.Label(参, text="响度 LUFS").pack(side="left", padx=(8, 0))
        self.var_响度 = tk.StringVar(value=str(种子.get("音频修复_响度目标") or -16))
        ttk.Entry(参, textvariable=self.var_响度, width=6).pack(side="left", padx=4)
        ttk.Label(参, text="输出格式").pack(side="left", padx=(8, 0))
        self.var_格式 = tk.StringVar(value=str(种子.get("音频修复_输出格式") or "opus"))
        ttk.Combobox(参, textvariable=self.var_格式, values=["opus", "mp3", "flac", "wav"],
                     width=6, state="readonly").pack(side="left", padx=4)

        参3 = ttk.Frame(框); 参3.pack(fill="x", **pad)
        ttk.Label(参3, text="输出方式").pack(side="left")
        self.var_方式 = tk.StringVar(value=str(种子.get("音频修复_输出方式") or "音频"))
        ttk.Combobox(参3, textvariable=self.var_方式, values=["音频", "视频"], width=8,
                     state="readonly").pack(side="left", padx=4)
        ttk.Label(参3, text="（视频 = 把修好的音轨封回原视频，视频流不重编码）",
                  foreground="#666").pack(side="left")

        # 两行放：放一行会被挤出可视区（实测把「裁静音 / 降级提醒」顶没了）
        参齿 = ttk.Frame(框); 参齿.pack(fill="x", **pad)
        ttk.Label(参齿, text="去齿音").pack(side="left")
        self.var_去齿音 = tk.StringVar(value=str(种子.get("音频修复_去齿音") or "关"))
        ttk.Combobox(参齿, textvariable=self.var_去齿音, values=["关", "轻", "标准", "强"],
                     width=5, state="readonly").pack(side="left", padx=4)
        ttk.Label(参齿, text="压底噪").pack(side="left", padx=(12, 0))
        self.var_压底噪 = tk.StringVar(value=str(种子.get("音频修复_压底噪") or "关"))
        ttk.Combobox(参齿, textvariable=self.var_压底噪, values=["关", "极轻", "轻", "标准", "强"],
                     width=5, state="readonly").pack(side="left", padx=4)
        ttk.Label(参齿, text="（去齿音＝压瞬时尖刺；压底噪＝噪声门，治 AI 重合成后的嘶声）",
                  foreground="#666").pack(side="left", padx=(8, 0))

        参2 = ttk.Frame(框); 参2.pack(fill="x", **pad)
        self.var_裁静音 = tk.BooleanVar(value=bool(种子.get("音频修复_裁静音", True)))
        ttk.Checkbutton(参2, text="裁掉静音（含尾部死寂）", variable=self.var_裁静音).pack(side="left")
        self.var_降级提醒 = tk.BooleanVar(value=bool(种子.get("音频修复_降级时提醒", True)))
        ttk.Checkbutton(参2, text="降级时在日志里提醒", variable=self.var_降级提醒).pack(side="left", padx=10)

        # 按钮 + 进度
        跑行 = ttk.Frame(框); 跑行.pack(fill="x", padx=8, pady=8)
        self.btn_跑 = ttk.Button(
            跑行, text=("▶  开始插帧（音轨自动修）" if self.紧凑 else "▶  开始音频修复"),
            command=self.开始)
        self.btn_跑.pack(side="left", ipadx=14, ipady=4)
        self.btn_停 = ttk.Button(跑行, text="■ 停止", command=self._停止, state="disabled")
        self.btn_停.pack(side="left", padx=(0, 8))
        self.btn_开 = ttk.Button(跑行, text="📂 打开输出文件夹", command=self._打开输出)
        self.btn_开.pack(side="left", padx=8)
        self.lbl_状态 = ttk.Label(跑行, text="待命中", foreground="#666")
        self.lbl_状态.pack(side="left", padx=8)

        self.prog = ttk.Progressbar(框, mode="indeterminate")
        self.prog.pack(fill="x", padx=8, pady=(0, 6))
        self.lbl_结果 = ttk.Label(框, text="", foreground="#666", wraplength=560, justify="left")
        self.lbl_结果.pack(anchor="w", padx=8, pady=(0, 6))

        self._刷新链路预览()

    # ------------------------------------------------------------------ 小动作
    def _刷新链路预览(self) -> None:
        self.lbl_链路.configure(text="执行顺序：" + " → ".join(self.当前链路(只名字=True)))

    def 当前链路(self, 只名字: bool = False) -> list[str]:
        """按「粗修 → 精修 → 超精修」的顺序拼出链路数组（就是配置里那个数组）。"""
        链 = []
        if self.var_粗修.get():
            链.append("dsp")
        if self.var_精修.get():
            链.append(self.var_轻量模型.get())
        if self.var_超精修.get():
            链.append(self.var_重度模型.get())
        if 只名字:
            return ["粗修" if x == "dsp" else x for x in 链] or ["（空：不处理）"]
        return 链

    def _停止(self) -> None:
        """把「还在跑」的标志按下去，循环会在当前文件跑完后停手。"""
        self._跑着 = False
        self.lbl_状态.configure(text="正在收尾…（当前这个文件跑完就停）")
        self._说("⏹ 收到停止指令：当前文件跑完就停。")

    def _选文件(self) -> None:
        p = filedialog.askopenfilename(title="选一个音频或视频文件")
        if p:
            self.var_源.set(p)

    def _选文件夹(self) -> None:
        p = filedialog.askdirectory(title="选一个放素材的文件夹")
        if p:
            self.var_源.set(p)

    def _选出(self) -> None:
        p = filedialog.askdirectory(title="选输出文件夹")
        if p:
            self.var_出.set(p)

    def _打开输出(self) -> None:
        try:
            d = Path(self.var_出.get())
            d.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                import os as _os
                _os.startfile(str(d))                     # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(d)])
            else:
                subprocess.Popen(["xdg-open", str(d)])
        except Exception as exc:
            self._说(f"打不开输出文件夹：{exc}")

    def _日志行(self, 行: str) -> None:
        """audio_fix 的**每一行阶段日志**都从这儿过一遍，抄给界面的运行日志。

        不直接在后台线程里写控件（Tkinter 铁律），统一丢进主窗口的 msgq，
        由主窗口的 after() 轮询写进那块「运行日志」框 —— 那块框三个模式共用。
        """
        q = getattr(self.app, "msgq", None)
        if q is not None:
            try:
                q.put(行); return
            except Exception:
                pass
        print(行, flush=True)

    def _说(self, 文字: str) -> None:
        """往主窗口的日志队列丢一行；没有 app 就打印。"""
        q = getattr(self.app, "msgq", None)
        if q is not None:
            try:
                q.put(文字); return
            except Exception:
                pass
        print(文字, flush=True)

    # ------------------------------------------------------------------ 外挂自检
    def _刷新模型可用性(self) -> None:
        def _干():
            入口 = HERE / "audio_plugin" / "worker.py"
            if not 入口.is_file():
                self._回("外挂不在位（只在用 DSP 也能干活）", {})
                return
            try:
                # 必须问 audio_fix「外挂会跑在哪个解释器上」，不能想当然用
                # sys.executable —— 否则面板显示的是主工具那个环境的依赖，
                # 实际跑的是另一个，会出现「明明装在 venv 里却报缺依赖」。
                af = _载入音频本体()
                检查器 = af.挑解释器()
                前缀 = list(af.主流程.priority_prefix())
                参数 = dict(af.主流程.spawn_kwargs())
            except Exception:
                检查器, 前缀, 参数 = sys.executable, [], {}
            try:
                r = subprocess.run([*前缀, 检查器, str(入口), "--自检"],
                                   stdin=subprocess.DEVNULL,
                                   capture_output=True, text=True, timeout=60, **参数)
                d = json.loads(r.stdout or "{}")
                self._回("", dict(d.get("模型") or {}), d.get("解释器", "?"))
            except Exception as exc:
                self._回(f"外挂自检失败：{exc}", {})
        threading.Thread(target=_干, daemon=True, name="pet-audio-selftest").start()

    def _回(self, 提示: str, 模型: dict, 解释器: str = "") -> None:
        """（后台线程调用）只整理文字，真正的控件更新交给 GUI 线程的轮询。"""
        行 = [f"{名}{'✓' if v[0] else '✗'}" for 名, v in 模型.items()]
        文本 = 提示 or (f"外挂在位（解释器 {解释器}）：" + "、".join(行) if 行 else "外挂在位，但没有模型")
        缺 = [f"{k}：{v[1]}" for k, v in 模型.items() if not v[0] and v[1]]
        if 缺:
            文本 += "\n" + "；".join(缺[:2])
        self._界面队列.put(("外挂", 提示, 模型, 文本))

    # ------------------------------------------------------------------ 开跑
    def _收文件(self, 源文本: str) -> list[Path]:
        p = Path(源文本)
        if p.is_file():
            return [p]
        if p.is_dir():
            音频后缀 = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".aif", ".aiff"}
            视频后缀 = {".webm", ".mkv", ".mp4", ".mov", ".m4v", ".avi", ".wmv", ".flv", ".ts", ".m2ts", ".mpg", ".mpeg", ".ogv", ".3gp"}
            return sorted(x for x in p.iterdir()
                          if x.is_file() and x.suffix.lower() in (音频后缀 | 视频后缀))
        return []

    def _走视频流程(self) -> None:
        """视音模式下这个按钮等于「开始插帧」—— 插完会自动换音轨。"""
        app = self.app
        if app is not None and hasattr(app, "on_start"):
            app.on_start()
        else:
            self._说("视音模式：请点上面的「▶ 开始插帧」，插完会自动修音轨。")

    def 设紧凑(self, 紧凑: bool) -> None:
        """在「音频」（独立）和「视音」（紧凑）之间来回切时换挡。

        做法是**就地换挡，不重建面板** —— 重建会把用户刚填的参数、
        勾好的链路全丢掉，切一下模式就得重填谁受得了。
        换挡只动两样东西：源那一行显示/隐藏、按钮文案。
        """
        紧凑 = bool(紧凑)
        if 紧凑 == getattr(self, "紧凑", None):
            return
        self.紧凑 = 紧凑
        try:
            self.btn_跑.configure(
                text=("▶  开始插帧（音轨自动修）" if 紧凑 else "▶  开始音频修复"))
        except Exception:
            pass
        try:
            if 紧凑:
                self._行_源.pack_forget()
            else:
                # 插回「输出文件夹」那一行前面，保持原来的上下顺序
                self._行_源.pack(fill="x", padx=8, pady=4, before=self._行_出)
        except Exception:
            pass
        # 紧凑模式下按钮是替主界面代喊的，得把状态同步回去
        self._刷新链路预览()

    def 开始(self) -> None:
        # 紧凑模式（视音）：面板自己没有「源」，按主界面的源走视频那套流程
        if self.紧凑:
            self._走视频流程()
            return
        if not hasattr(self, "var_源"):
            # 正常不会走到这里（var_源 永远会建）。真发生了就明说，
            # 绝不默默跑去跑视频流程 —— 那看起来像"点了没反应"。
            self._说("音频面板状态异常（找不到源输入框），请切一下模式再试。")
            return
        if self._跑着:
            self._说("音频任务还在跑，等它结束或者关掉窗口。")
            return
        文件表 = self._收文件(self.var_源.get().strip())
        if not 文件表:
            messagebox.showinfo("没找到文件", "请先选一个音频/视频文件，或者一个装着素材的文件夹。")
            return
        链 = self.当前链路()
        if not 链:
            if not messagebox.askokcancel("链路是空的", "三档都没勾，等于什么都不做。仍然继续吗？"):
                return
        # Tkinter 铁律：所有控件与 tk 变量只能在主线程里碰。
        # 后台线程里读 self.var_xxx.get() 会抛 main thread is not in main loop ——
        # 所以先把设置快照下来，线程只吃这份字典。
        设置 = {
            "链路": 链,
            "强度": self.var_强度.get(),
            "风格": self.var_风格.get(),
            "裁静音": bool(self.var_裁静音.get()),
            "格式": self.var_格式.get(),
            "降级提醒": bool(self.var_降级提醒.get()),
            "去齿音": self.var_去齿音.get(),
            "压底噪": self.var_压底噪.get(),
            "响度文本": self.var_响度.get(),
            "输出目录文本": self.var_出.get().strip(),
            "输出方式": self.var_方式.get(),
        }
        self._跑着 = True
        self.btn_跑.configure(state="disabled")
        self.lbl_状态.configure(text="跑着呢…")
        self.lbl_结果.configure(text="")
        self.btn_停.configure(state="normal")
        self.prog.start(12)
        threading.Thread(target=self._跑一批, args=(文件表, 设置), daemon=True,
                         name="pet-audio-run").start()

    def _跑一批(self, 文件表: list[Path], 设置: dict) -> None:
        """后台线程：只吃主线程快照下来的「设置」字典，绝不碰任何控件。"""
        try:
            af = _载入音频本体()
            cfg = dict(af.load_config())
            cfg.update({
                "音频修复_处理链路": 设置["链路"],
                "音频修复_强度": 设置["强度"],
                "音频修复_EQ风格": 设置["风格"],
                "音频修复_裁静音": 设置["裁静音"],
                "音频修复_输出格式": 设置["格式"],
                "音频修复_降级时提醒": 设置["降级提醒"],
                "音频修复_去齿音": 设置.get("去齿音", "关"),
                "音频修复_压底噪": 设置.get("压底噪", "关"),
                "音频修复_输出方式": 设置.get("输出方式", "音频"),
            })
            try:
                cfg["音频修复_响度目标"] = float(设置["响度文本"])
            except ValueError:
                self._说(f"⚠️ 响度不是数字，用默认 -16。")
            出 = Path(设置["输出目录文本"] or (HERE / "output"))
        except Exception as exc:
            self._说(f"✘ 音频模块起不来：{exc}")
            self._收尾(0, len(文件表), f"模块加载失败：{exc}")
            return

        成功 = 0
        首个降级 = ""
        for i, f in enumerate(文件表, 1):
            if not self._跑着:
                break
            self._在界面(f"[{i}/{len(文件表)}] {f.name}")
            结果 = af.run_audio_pipeline(f, 出, 配置=cfg, 进度=self._进度回调,
                                           日志=self._日志行)
            if 结果.get("ok"):
                成功 += 1
                统 = 结果.get("统计") or {}
                self._说(f"    ✔ {f.name} → {Path(str(结果['输出'])).name}"
                         f"（响度 {统.get('后响度')}｜裁静音 {统.get('裁掉秒数'):.1f} 秒）"
                         if isinstance(统.get("裁掉秒数"), (int, float)) else f"    ✔ {f.name} 完成")
            elif 结果.get("跳过"):
                self._说("    跳过（链路为空）")
            else:
                self._说(f"    ✘ {f.name}：{结果.get('消息')}")
            首个降级 = 首个降级 or str(结果.get("降级") or "")
        摘要 = f"完成：{成功}/{len(文件表)}"
        if 首个降级:
            摘要 += f"　⚠️ 有降级：{首个降级[:120]}"
        self._收尾(成功, len(文件表), 摘要)

    def _进度回调(self, 阶段: str, 百分比) -> None:
        self._在界面(f"    … {阶段}")

    def _在界面(self, 文字: str) -> None:
        self._说(文字)
        self._界面队列.put(("状态", 文字.strip()[:40]))

    def _轮询界面(self) -> None:
        """GUI 线程的定时器：把后台线程排队的界面更新应用掉。"""
        try:
            while True:
                项 = self._界面队列.get_nowait()
                动作 = 项[0]
                if 动作 == "状态":
                    self.lbl_状态.configure(text=项[1])
                elif 动作 == "跑着":
                    self.btn_停.configure(state=("normal" if 项[1] else "disabled"))
                    if 项[1]:
                        self.prog.start(12)
                        self.lbl_状态.configure(text="换音轨中…")
                elif 动作 == "外挂":
                    self._模型可用 = 项[2]
                    self.lbl_外挂.configure(text=项[3])
                elif 动作 == "收尾":
                    self.prog.stop()
                    self.btn_跑.configure(state="normal")
                    self.btn_停.configure(state="disabled")
                    self.lbl_状态.configure(text="待命中")
                    self.lbl_结果.configure(text=项[1],
                                            foreground="#a60" if "降级" in 项[1] else "#666")
                    if 项[2]:
                        self.btn_开.configure(state="normal")
        except queue.Empty:
            pass
        except Exception:
            pass
        try:
            self.after(120, self._轮询界面)
        except Exception:
            pass

    # ------------------------------------------------------------------ 视音：给插帧输出"补一刀"音轨
    def 造视频后处理器(self, 输出目录: str):
        """给「视音」模式用：返回一个可在后台线程里跑的 callable()。

        它把插帧**产出的视频**逐个过一遍音频链路（输出方式=视频 → 封回音轨）。
        必须在 GUI 线程里调用（要读 tk 变量）；返回的函数只吃快照，不碰控件。
        没有链路时返回 None。
        """
        链 = self.当前链路()
        if not 链:
            return None
        设置 = {
            "链路": 链,
            "强度": self.var_强度.get(),
            "风格": self.var_风格.get(),
            "格式": self.var_格式.get(),
            "降级提醒": bool(self.var_降级提醒.get()),
            "去齿音": self.var_去齿音.get(),
            "压底噪": self.var_压底噪.get(),
            "响度文本": self.var_响度.get(),
            "输出目录": 输出目录 or str(HERE / "output"),
        }

        def 处理() -> None:
            # 这个函数在后台线程跑，所以自己把「跑着」标志立起来 ——
            # 它由 _finish() 触发，走的不是「开始音频修复」那条路，没人替它设置。
            self._跑着 = True
            self._界面队列.put(("跑着", True))
            try:
                af = _载入音频本体()
                cfg = dict(af.load_config())
                cfg.update({
                    "音频修复_处理链路": 设置["链路"],
                    "音频修复_强度": 设置["强度"],
                    "音频修复_EQ风格": 设置["风格"],
                    "音频修复_输出格式": 设置["格式"],
                    "音频修复_降级时提醒": 设置["降级提醒"],
                    "音频修复_去齿音": 设置.get("去齿音", "关"),
                    "音频修复_压底噪": 设置.get("压底噪", "关"),
                "音频修复_压底噪": 设置.get("压底噪", "关"),
                "音频修复_去齿音": 设置.get("去齿音", "关"),
                "音频修复_压底噪": 设置.get("压底噪", "关"),
                    "音频修复_输出方式": "视频",          # 视音模式固定封回视频
                    "音频修复_裁静音": False,             # 视频长度由画面决定，别剪音频
                })
                try:
                    cfg["音频修复_响度目标"] = float(设置["响度文本"])
                except ValueError:
                    pass
                目录 = Path(设置["输出目录"])
                视频后缀 = {".webm", ".mkv", ".mp4", ".mov", ".m4v", ".avi", ".wmv", ".flv", ".ts", ".m2ts", ".mpg", ".mpeg", ".ogv", ".3gp"}
                文件 = [x for x in sorted(目录.iterdir())
                        if x.is_file() and x.suffix.lower() in 视频后缀
                        and "-音轨已修复" not in x.stem]
            except Exception as exc:
                self._说(f"✘ 音频后处理起不来：{exc}")
                return
            if not 文件:
                self._说("音频后处理：输出目录里没有视频文件，跳过。")
                self._跑着 = False
                self._界面队列.put(("跑着", False))
                return
            self._说(f"音频后处理：共 {len(文件)} 个视频要换音轨…")
            好 = 0
            for i, f in enumerate(文件, 1):
                if not self._跑着:
                    self._说("音频后处理：收到停止指令，提前结束。")
                    break
                self._在界面(f"换音轨 [{i}/{len(文件)}] {f.name}")
                结果 = af.run_audio_pipeline(f, 目录, 配置=cfg, 进度=self._进度回调,
                                               日志=self._日志行)
                if 结果.get("ok"):
                    好 += 1
                    self._说(f"    ✔ {f.name} → {Path(str(结果['输出'])).name}")
                else:
                    self._说(f"    ✘ {f.name}：{结果.get('消息')}")
            self._说(f"音频后处理完成：{好}/{len(文件)}")
            self._界面队列.put(("收尾", f"音轨后处理完成：{好}/{len(文件)}", 好))
            self._跑着 = False
            self._界面队列.put(("跑着", False))

        return 处理

    def _收尾(self, 成功: int, 总数: int, 摘要: str) -> None:
        self._跑着 = False
        self._界面队列.put(("收尾", 摘要, 成功))


def 挂载(容器: tk.Misc, app=None, 紧凑: bool = False) -> 音频面板:
    """给 gui.py 用的入口：把音频面板塞进指定容器并返回它。"""
    面板 = 音频面板(容器, app, 紧凑)
    面板.pack(fill="both", expand=True)
    return 面板
