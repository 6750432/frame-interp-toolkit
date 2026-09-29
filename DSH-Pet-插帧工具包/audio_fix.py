#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DSH Pet 插帧工具 · 音频快修外挂（audio_fix.py）
================================================
给音轨做一次"快修"：**去闷 → 提清晰度 → 响度标准化 → 裁静音**。
不插帧、不碰画面，只动声音。

设计原则（和主流程 插帧.py 保持一致）：
    1. **零第三方 Python 依赖** —— 只用标准库 + 系统里的 ffmpeg（滤镜全是 ffmpeg 自带的）
    2. **外挂原则** —— 不改动 插帧.py / gui.py 的处理流程；只"借用"它们的环境探测、
       配置读取和日志函数（`主流程.log` / `load_config` / `find_ffmpeg` / `run`），
       所以主流程升级了，本模块跟着一起受益，也不会被本模块拖坏。
    3. **AI 降噪不在这里** —— 那需要额外依赖（约 200 MB），按约定做成"可选外挂"，
       默认不启用；没装依赖的机器，本模块照样全功能可用。

文件名故意用 ASCII（audio_fix.py）而不用中文：它要被 gui.py `import`，
中文模块名在某些环境（尤其 Windows 的 zip/解压链路）会有编码坑。

用法：
    python audio_fix.py 音频.mp3          快修，输出到 output/
    python audio_fix.py 视频.webm         自动抽音轨再快修
    python audio_fix.py 文件 --强度 重         轻 / 标准 / 重
    python audio_fix.py 文件 --响度 -14        改目标响度（默认 -16 LUFS）
    python audio_fix.py 文件 --不裁静音        只去闷+提亮+标准化，不剪时长
    python audio_fix.py 文件 --格式 mp3        opus（默认）/ mp3 / flac / wav
    python audio_fix.py 文件 --波形图          顺带出一张前后波形对比图
    python audio_fix.py --检查                只检查环境，不干活

作者：本项目 + 社区贡献者。仅供学习交流。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

# 版本号：和主流程分开编号，出问题时报这个号最快定位。
VERSION = "音频快修 v0.1 (Phase 1)"

# --------------------------------------------------------------------- 借用主流程
# 主流程的文件名是中文的，用 importlib 按路径加载，避免依赖 sys.path 里恰好有本目录。
def _载入主流程():
    import importlib.util

    path = HERE / "插帧.py"
    if not path.is_file():
        raise RuntimeError(
            f"找不到主流程文件：{path}\n"
            "    · 本模块是外挂，必须和 插帧.py 放在同一个目录里。"
        )
    spec = importlib.util.spec_from_file_location("dsh_插帧主流程", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"加载主流程失败：{path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


主流程 = _载入主流程()
log = 主流程.log
_log_原样 = 主流程.log          # 原来的实现：打到 stdout（终端 / 日志文件）
_日志钩子 = None                # GUI 用：跑一批的时候临时挂上，好把每一行抄给界面


def log(msg: str) -> None:
    """打印一行日志；挂了钩子（GUI 在跑任务）时**同时**抄一份给界面。

    为什么要抄：这个模块的阶段日志（源 / 修复前 / EQ 后实测 / 增益策略 /
    频段自检 / 修复后 / 裁掉静音）原来只往 stdout 打 —— GUI 用 pythonw 或
    双击启动时根本没有终端，用户在界面上只看得到一个「完成」，
    等于白写了这么多实测数据。
    """
    _log_原样(msg)
    h = _日志钩子
    if h is not None:
        try:
            h(msg)
        except Exception:
            pass        # 抄送失败绝不能影响音频流程本身


def 挂日志钩子(回调) -> None:
    """挂 / 取消日志抄送（传 None 取消）。

    ⚠️ 是模块级全局，所以**同一时刻只能有一个任务在跑**。
    目前够用：GUI 里有 `_跑着` 挡着，一次只跑一批。
    """
    global _日志钩子
    _日志钩子 = 回调
hr = 主流程.hr
capture = 主流程.capture
capture_raw = 主流程.capture_raw
run = 主流程.run
load_config = 主流程.load_config
find_ffmpeg = 主流程.find_ffmpeg

# --------------------------------------------------------------------- 常量
# 能直接当"音频"处理的扩展名
AUDIO_EXTS = (".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma",
              ".aif", ".aiff", ".ape", ".amr", ".mka")

# 输出格式 → (扩展名, ffmpeg 编码参数)
输出格式表 = {
    "opus": (".opus", ["-c:a", "libopus", "-b:a", "128k"]),
    "mp3":  (".mp3",  ["-c:a", "libmp3lame", "-q:a", "2"]),   # VBR ≈190 kbps，什么播放器都认
    "flac": (".flac", ["-c:a", "flac"]),
    "wav":  (".wav",  ["-c:a", "pcm_s16le"]),
}

# opus 只支持这几个采样率，源不是其中之一就先重采样
OPUS_采样率 = (8000, 12000, 16000, 24000, 48000)

# 修复强度的三档：低频砍多少、清晰度提多少、空气感提多少（单位 dB）
强度档位 = {
    "轻":   {"低频": -3.0, "清晰": 2.0, "空气": 2.0},
    "标准": {"低频": -5.0, "清晰": 3.0, "空气": 3.0},
    "重":   {"低频": -7.0, "清晰": 4.5, "空气": 4.0},
}

# 写进 config.json 的新字段（GUI 那边会用同一份；这里只是缺省值）
音频默认配置 = {
    "音频修复_强度": "标准",
    "音频修复_响度目标": -16,
    "音频修复_裁静音": True,
    "音频修复_输出格式": "opus",
    "音频修复_削峰策略": "保真",
    "音频修复_EQ风格": "语音",
    "音频修复_去齿音": "关",        # 关 / 轻 / 标准 / 强：只压齿音那一瞬间，不整体削高频
    "音频修复_压底噪": "关",        # 关 / 轻 / 标准 / 强：噪声门，治 AI 重合成后多出来的嘶声
    "音频修复模型": "dsp",          # 无 = 整条跳过；dsp = 自带零依赖快修；其它 = 走外挂子进程
    "音频修复_外挂超时秒": 3600,
    "音频修复_外挂参数": {},        # 原样透传给外挂模型（如 {"attn_limit_db": 12}）
    "音频修复_处理链路": [],        # 例：["dsp", "dpdfnet2"]。留空 = 按「音频修复模型」推导
    "音频修复_降级时提醒": True,     # false = 连日志都不打印（记录文件里仍留痕）
    "音频修复_输出方式": "音频",     # 音频 = 只出音频文件；视频 = 把修好的音轨封回原视频
    "音频修复_视频容器": "",        # 留空 = 跟随源容器（webm / mkv / mp4 …）
    "音频修复_Python路径": "",      # 留空 = 用主工具自己的解释器；AI 模型建议指到 3.11+ 的解释器     # 保真 = 宁可小声也不削峰；保响度 = 优先打到目标响度
    "音频修复_输出目录": "",       # 留空 = 工具包里的 output/
}


# --------------------------------------------------------------------- 小工具
def 取音频流信息(ffprobe: str, path: Path) -> dict:
    """用 ffprobe 读时长/采样率/声道/编码。读不出来时给安全默认值，不炸。"""
    info = {"时长": 0.0, "采样率": 0, "声道": 0, "编码": "?"}
    try:
        raw = capture([ffprobe, "-v", "error", "-print_format", "json",
                       "-show_format", "-show_streams", str(path)])
        data = json.loads(raw)
        for s in data.get("streams", []):
            if s.get("codec_type") == "audio":
                info["采样率"] = int(s.get("sample_rate") or 0)
                info["声道"] = int(s.get("channels") or 0)
                info["编码"] = s.get("codec_name") or "?"
                break
        dur = (data.get("format") or {}).get("duration")
        if dur:
            info["时长"] = float(dur)
    except Exception as exc:
        log(f"⚠️ 读取音频信息失败（继续，不影响处理）：{exc}")
    return info


def 挑解释器(cfg: dict | None = None) -> str:
    """外挂子进程该用哪个 Python。

    ⚠️ 这条必须**只有一处实现**：外挂自检和真正跑外挂要是用了不同的解释器，
    界面就会显示一套、实际跑另一套 —— 出现过「面板说 dpdfnet2 缺依赖，
    其实装在 venv 里好好的」，就是因为自检写的是 sys.executable。
    """
    cfg = cfg if cfg is not None else load_config()
    return str((cfg or {}).get("音频修复_Python路径") or "").strip() or sys.executable


def 跑并收输出(cmd: list[str]) -> str:
    """跑一条命令，把 **stdout + stderr 一起**收回来。

    为什么不用主流程的 capture()/capture_raw()：那两个函数把 stderr 丢进 DEVNULL，
    而 ffmpeg 的 loudnorm 分析结果、以及绝大部分报错信息，**都是打在 stderr 上的** ——
    用它们会导致"响度测不到"（本模块第一版就踩了这个坑）。
    这里只借用主流程的 priority_prefix()（压低优先级、不抢用户电脑）和
    spawn_kwargs()（Windows 下的进程创建参数），保持跨平台一致。
    """
    try:
        p = subprocess.run([*主流程.priority_prefix(), *cmd], stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           **主流程.spawn_kwargs())
        return p.stdout.decode("utf-8", "replace")
    except (FileNotFoundError, OSError):
        return ""


def 测响度明细(ffmpeg: str, path: Path, 前置: str = "", 响度目标: float = -16.0,
                滤镜参数: list[str] | None = None) -> dict:
    """跑 loudnorm 的"只分析"模式，把整段 JSON 拿回来。

    返回键：i(响度) / tp(真峰值) / lra(动态) / thresh(门限) / offset(建议偏移)。

    ⚠️ 两个坑（本模块都踩过，写下来免得以后又踩）：
      1. loudnorm 的结果打在 **stderr** 上 —— 主流程的 capture() 把 stderr 丢了，
         所以这里必须自己收 stdout+stderr（见 跑并收输出）。
      2. 分析时必须**带上和最终处理相同的 I / TP 目标**：不写的话 loudnorm 按默认
         I=-24 算，返回的 target_offset 就是"朝 -24 修正的量"，拿来给 -16 用会偏。
    """
    af = f"{前置},loudnorm=I={响度目标}:TP=-1.5:LRA=11:print_format=json" if 前置 \
        else f"loudnorm=I={响度目标}:TP=-1.5:LRA=11:print_format=json"
    # 带 filter_complex 时（去齿音要分两路），必须让调用方把整段参数拼好传进来 ——
    # loudnorm 得接在图的最末一级，不能简单往 -af 后面再拼。
    参数 = list(滤镜参数) if 滤镜参数 else ["-af", af]
    try:
        text = 跑并收输出([ffmpeg, "-hide_banner", "-nostdin", "-i", str(path),
                           *参数, "-f", "null", "-"])
        i, j = text.rfind("{"), text.rfind("}")
        if i >= 0 and j > i:
            d = json.loads(text[i:j + 1])
            return {k: float(d.get("input_" + k)) for k in ("i", "tp", "lra", "thresh")} | \
                   {"offset": float(d.get("target_offset") or 0.0)}
    except Exception as exc:
        log(f"⚠️ 响度分析失败（会退回单遍模式）：{exc}")
    return {}


频段定义 = (("80–300 Hz", "highpass=f=80,lowpass=f=300"),
            ("300–1.5k", "highpass=f=300,lowpass=f=1500"),
            ("1.5k–4k", "highpass=f=1500,lowpass=f=4000"),
            ("8k 以上", "highpass=f=8000"))


def 测频段(ffmpeg: str, path: Path) -> dict:
    """一次解码，同时量出 4 个频段的 RMS（dB）。

    为什么要量这个：**光看响度数字看不出"EQ 到底有没有起作用"**。
    本模块第一版就栽在这 —— 低频搁架放在 200 Hz，而这类素材的能量其实堆在 80–300 Hz，
    结果最响的那一段只动了 +0.1 dB（等于没动），听感上"没区别"。
    有了这张表，跑完一眼就能看出"哪一段动了多少"，不会再出现静默无效的处理。
    """
    分支 = "".join(f"[{i}]" for i in range(len(频段定义)))
    链 = [f"[0:a]asplit={len(频段定义)}{分支}"]
    for i, (_, f) in enumerate(频段定义):
        链.append(f"[{i}]{f},astats=metadata=0[o{i}]")
    地图 = []
    for i in range(len(频段定义)):
        地图 += ["-map", f"[o{i}]", "-f", "null", "-"]
    try:
        text = 跑并收输出([ffmpeg, "-hide_banner", "-nostdin", "-i", str(path),
                           "-filter_complex", ";".join(链), *地图])
    except Exception:
        return {}
    # ⚠️ 千万别按"打印顺序"取！实测各分支的 astats 摘要**不是按分支顺序输出的**
    #    （拿到的四个数正好是倒过来的，会把 8k+ 的电平记到 80–300 Hz 头上）。
    # 可靠的做法：按 astats 的实例编号（id 在滤镜创建时就定了，和分支顺序一致）排序，
    #    再依次对应到频段定义。
    组 = {}
    for 行 in text.splitlines():
        m = re.search(r"\[Parsed_astats_(\d+) @ [^\]]+\]\s*RMS level dB:\s*(-?[\d.]+|-inf)", 行)
        if m:
            组.setdefault(int(m.group(1)), m.group(2))
    值 = {}
    for (名, _), 编号 in zip(频段定义, sorted(组)):
        try:
            值[名] = float(组[编号])
        except ValueError:
            值[名] = float("-inf")
    return 值


def 算增益(响度目标: float, 测量: dict, 策略: str,
          真峰值上限: float = -2.0) -> tuple[float | None, str]:
    """算出该加多少 dB，并返回一句人话说明。

    为什么不用 loudnorm 的 linear 模式直接搞定：它是黑盒 —— 实测过，
    它给出的结果会偏 0.5~1 LU（而且真峰值也没真压住）。自己算增益更可控：

        · 需要的增益         = 目标响度 - 实测响度 + offset(小修正)
        · 真峰值允许的增益   = -2.0 dBTP - 实测真峰值
          （为什么留 2 dB 而不是 1.5：opus/mp3 这类有损编码**解出来的真峰值会比编码前高**
            0.5~1 dB，实测就撞到过 -0.29 dBTP。留 2 dB 余量才能真正守住不削顶。）
        · 「保真」策略 → 取两者**较小**：宁可整体小声一点，也不削峰（助眠/环境音首选）
        · 「保响度」策略 → 只按响度算，超出的峰交给限幅器（语音/口播更像"标准响度"）
    """
    if not 测量 or "i" not in 测量:
        return None, "没测到响度，退回单遍模式"

    # ── 三种"量不出正常响度"的情况，各给一条出路（都是验收时真踩出来的）──
    i, tp = 测量["i"], 测量.get("tp", float("-inf"))
    if not math.isfinite(i):
        if math.isfinite(tp):
            # 极短片段（如 0.2 秒的音效）：loudnorm 量不出积分响度，但峰值是准的
            g = 真峰值上限 - tp
            return g, f"太短量不出响度，改按峰值对齐（{tp:.2f} dBTP）→ 加 {g:.2f} dB"
        # 整个文件是纯静音：什么都不加，保持原样，绝不加 +inf
        return 0.0, "整个文件是纯静音（响度 -inf），不做增益、原样输出"

    按响度 = 响度目标 - i + 测量.get("offset", 0.0)
    按峰值 = 真峰值上限 - tp
    # 兜底夹紧：既不把微弱录音放大成一片底噪，也不做出离谱的增益
    按响度 = max(-24.0, min(20.0, 按响度))
    if 策略 == "保响度":
        return 按响度, f"按响度目标加 {按响度:.2f} dB（峰值交给限幅器）"
    if 按响度 <= 按峰值:
        return 按响度, f"按响度目标加 {按响度:.2f} dB"
    损失 = 按响度 - 按峰值
    提醒 = ""
    if 损失 >= 2.0:
        # 实测踩到过：源真峰值 +0.63 dBTP 的助眠素材，环境音 EQ 把峰值又顶高
        # 3.2 dB，于是「保真」只敢加 -5.86 dB，最后比目标小声 6.5 dB。
        # 这是策略本身的意思（宁小不削），但用户看不出原因，所以明说。
        提醒 = (f"⚠️ 保真策略下这一条会比目标小声 {损失:.1f} dB —— "
                f"源素材本来就顶到峰值了，这是「宁可整体小声也不削峰」的代价。"
                f"想让它到 {响度目标} LUFS，把「削峰策略」改成「保响度」"
                f"（代价是限幅器会压一点峰，可能有一点抽吸感）。")
    return 按峰值, (f"受真峰值限制只加 {按峰值:.2f} dB"
                    f"（想打到 {响度目标} LUFS 得加 {按响度:.2f} dB，会超过 0 dBTP）"
                    + (f"\n     {提醒}" if 提醒 else ""))


def 测响度(ffmpeg: str, path: Path) -> dict:
    """给记录文件用的三项读数。"""
    d = 测响度明细(ffmpeg, path)
    return {"响度": d.get("i"), "真峰值": d.get("tp"), "动态": d.get("lra")}


# EQ 风格：同一条素材，两条路子完全不同 —— 这是踩了坑才分出来的
#   语音   = 低频用「搁架」衰减：治"人声被捂住"（问题区在 200~500 Hz 的堆积）
#   环境音 = 低频用「峰值切除」：治"能量全堆在 80~300 Hz"的音乐 / 环境音
#            （实测教训：搁架放在 200 Hz 对这类素材几乎无效 —— 最响的那段只动了 +0.1 dB，
#             听感上"没区别"。换成打在 220 Hz 的峰值切除，同样素材能压下 4~8 dB。）
风格倍率 = {"轻": 0.6, "标准": 1.0, "重": 1.35}


def 组EQ(强度: str, 风格: str = "语音") -> str:
    """前半段：去闷 + 提清晰度 + 空气感。"""
    if 风格 == "环境音":
        k = 风格倍率.get(强度, 1.0)
        return ",".join([
            "highpass=f=40",                          # 只切掉次低频的隆隆声
            f"equalizer=f=220:t=q:w=1:g={-8 * k:.1f}",   # 主刀：打在能量最堆的地方
            f"equalizer=f=500:t=q:w=1:g={-2 * k:.1f}",   # 顺手松开一点低中频
            f"equalizer=f=2800:t=q:w=1.2:g={4 * k:.1f}",  # 人耳清晰度
            f"highshelf=f=8000:g={4 * k:.1f}",           # 空气感
        ])
    g = 强度档位.get(强度) or 强度档位["标准"]
    return ",".join([
        "highpass=f=45",
        f"lowshelf=f=200:g={g['低频']}:width_type=q:width=0.8",
        f"equalizer=f=3200:width_type=q:width=1.5:g={g['清晰']}",
        f"highshelf=f=9000:g={g['空气']}:width_type=q:width=1",
    ])


# 限幅滤镜单独拎出来：去齿音要塞在「增益之后、限幅之前」，
# 所以终段必须能拆成两截（见下面的 组增益段 / 组终段）。
# ── 去齿音（de-esser）：零依赖，用 ffmpeg 自带的 sidechaincompress 搭 ────
# 原理：把信号一分为二 —— 主路不动，侧链只留 5~10 kHz（齿音/尖锐住那儿），
# 主路跟着侧链的电平动态衰减。**只有齿音那一刻才压，平时不压**，
# 这是它跟"固定 EQ 削弱高频"最本质的区别（后者一压就是全曲变暗）。
#
# threshold 是线性幅度，对应 dBFS：0.100≈-20｜0.063≈-24｜0.040≈-28 dBFS。
# 因为去齿音放在「增益之后」，此时整体电平已经归一化到目标响度，
# 所以固定阈值才有意义（放在增益之前会随素材原始电平乱飘 —— 设计时就避开了）。
# ⚠️ 阈值是**实测调出来的**，不是拍脑袋：
#    这条素材 5~10 kHz 的波峰因数是 25~30 dB（峰值 -2 dBFS、RMS -31 dBFS）——
#    也就是说"尖锐"是一阵阵的**尖刺**，不是"一直很亮"。
#    阈值必须卡在 RMS 和峰值之间（-18 ~ -25 dBFS），才能在尖刺出现时才压。
#    一开始把阈值设成 -28 dBFS（贴着 RMS），结果它几乎一直在压，
#    整条被压小 5.4 dB —— 那就不是去齿音，是全程压缩了。
去齿音档位 = {
    "关":   None,
    "轻":   {"threshold": 0.126, "ratio": 2.5},   # -18 dBFS
    "标准": {"threshold": 0.089, "ratio": 4.0},   # -21 dBFS
    "强":   {"threshold": 0.056, "ratio": 6.0},   # -25 dBFS
}
去齿音频段 = "highpass=f=5000,lowpass=f=10000"


# ── 压底噪（噪声门）：治的是「AI 模型重新合成之后凭空多出来的嘶声」────
# 实测：源素材里那段尾巴是**真的数字静音**（-240 dB），
# 过一遍 VoiceFixer 之后变成 -64 dB 的嘶声 —— 音量一开大就听见。
# 试过 DPDFNet2（只到 -74.6）和 afftdn 频谱降噪（-64.5），基本没用；
# **噪声门**才是对的：agate 一下子压到 -94.5 dB，而内容中位数纹丝不动（-23.9）。
# 放在前半段（增益之前）：这里的阈值是绝对 dBFS，先卡掉本底再统一抬音量。
压底噪档位 = {
    "关":   None,
    # 「轻」= 听感选定的一档（release 250→80、knee 6）：
    # 同样的阈值下，声音一停那层噪声不再"滞留"，同时把可用音量阈值从 65% 提到 70%。
    # （用数值指标看不出来 —— 帧间波动反而从 34.2 升到 36.9，因为收得更陡。
    #   这一项只能靠耳朵，所以参数是听出来的，不是算出来的。）
    "极轻": "agate=threshold=0.0006:ratio=2:range=0.25:attack=25:release=600",
    "轻":   "agate=threshold=0.001:ratio=3:range=0.1:attack=5:release=80:knee=6",
    "标准": "agate=threshold=0.002:ratio=4:range=0.05:attack=5:release=250",
    "强":   "agate=threshold=0.0032:ratio=4:range=0.02:attack=10:release=250",
}


def 有压底噪(名: str) -> bool:
    return bool(压底噪档位.get(str(名 or "关").strip()))


def 有去齿音(名: str) -> bool:
    return bool(去齿音档位.get(str(名 or "关").strip()))


def 组滤镜参数(前半: str, 后半: str, 去齿音: str = "关") -> list[str]:
    """拼 ffmpeg 的滤镜参数，返回一整段命令行参数（含 -af 或 -filter_complex）。

    **没有去齿音时保持老样子** —— 一条 -af 链，老路径一行不动，避免回归。
    有去齿音时必须走 -filter_complex：sidechaincompress 要吃两路输入
    （主信号 + 侧链），单输入的滤镜链表达不出来。

    前后两段允许是空串（视音模式下 EQ 可能已经在前面做过了）。
    """
    档 = 去齿音档位.get(str(去齿音 or "关").strip())
    if not 档:
        return ["-af", ",".join(x for x in (前半, 后半) if x)]
    段 = []
    当前 = "[0:a]"
    if 前半:
        段.append(f"{当前}{前半}[__pre]")
        当前 = "[__pre]"
    段.append(f"{当前}asplit=2[__dry][__sc0]")
    段.append(f"[__sc0]{去齿音频段}[__sc]")
    段.append(f"[__dry][__sc]sidechaincompress=threshold={档['threshold']}"
              f":ratio={档['ratio']}:attack=2:release=150:makeup=1[__dn]")
    当前 = "[__dn]"
    if 后半:
        段.append(f"{当前}{后半}[__out]")
        当前 = "[__out]"
    return ["-filter_complex", ";".join(段), "-map", 当前]


限幅滤镜 = "alimiter=limit=0.891:level=false"


def 组增益段(响度目标: float, 测量: dict, 裁静音: bool, 策略: str = "保真") -> str:
    """终段的前半截：裁静音 → 增益。**
    （去齿音要插在这一段和限幅之间，所以单独拆出来。）"""
    段 = []
    if 裁静音:
        段.append("silenceremove=stop_periods=-1:stop_duration=0.5:stop_threshold=-50dB")
    增益, 说明 = 算增益(响度目标, 测量, 策略)
    if 增益 is None:
        段.append(f"loudnorm=I={响度目标}:TP=-1.5:LRA=11:print_format=none")
    else:
        段.append(f"volume={增益:.2f}dB")
    return ",".join(段)


def 组终段(响度目标: float, 测量: dict, 裁静音: bool, 策略: str = "保真") -> str:
    """后半段：裁静音 → 增益（自己算，不用 loudnorm 黑盒）→ 限幅兜底。

    ⚠️ 顺序铁律：**裁静音必须在加增益之前**。
    因为 silenceremove 的判定阈值是绝对值（-50 dB）——先加增益就会改变
    "哪些片段算静音"，于是"测量时算的时长"和"处理时实际裁的时长"对不上，
    最终响度会偏（本模块实测偏过 +1 LU）。和测量链保持同序就不会歪。
    """
    段 = []
    if 裁静音:
        段.append("silenceremove=stop_periods=-1:stop_duration=0.5:stop_threshold=-50dB")
    增益, 说明 = 算增益(响度目标, 测量, 策略)
    if 增益 is None:
        # 量不出来就退回单遍动态模式 —— 能用，但响度会偏、可能有一点抽吸感
        段.append(f"loudnorm=I={响度目标}:TP=-1.5:LRA=11:print_format=none")
    else:
        段.append(f"volume={增益:.2f}dB")
    # ⚠️ level=false 必写！alimiter 默认 level=true = 「自动电平」，
    # 它会把输出再顶回去（实测凭空多出 +1 LU），响度就白算了。
    # 关掉之后它只做一件事：峰值超过 -1.0 dBFS 时压下来。
    段.append(限幅滤镜)
    return ",".join(段)


def 组滤镜链(强度: str, 响度目标: float, 裁静音: bool, 测量: dict | None = None,
             策略: str = "保真", 风格: str = "语音") -> str:
    """完整链 = EQ + 终段。给 --检查 和 GUI 预览用（不实际处理）。"""
    return ",".join([组EQ(强度, 风格), 组终段(响度目标, 测量 or {}, 裁静音, 策略)])


def 出波形对比图(ffmpeg: str, 原件: Path, 新件: Path, 出图: Path) -> bool:
    """把修复前后的波形上下叠在一张图上（纯 ffmpeg 实现，不额外依赖）。"""
    cmd = [
        ffmpeg, "-hide_banner", "-nostdin", "-v", "error",
        "-i", str(原件), "-i", str(新件),
        "-filter_complex",
        "[0:a]showwavespic=s=1400x300:colors=0x5aa9e6[上];"
        "[1:a]showwavespic=s=1400x300:colors=0x7bd88f[下];"
        "[上][下]vstack=inputs=2[out]",
        "-map", "[out]", "-frames:v", "1", "-y", str(出图),
    ]
    return run(cmd, "生成前后波形对比图") == 0 and 出图.is_file()


def 追加记录(记录文件: Path, 条目: dict) -> None:
    """把这一次的结果追加进《音频修复记录.txt》。用追加而不是覆盖，跑多次能攒成清单。"""
    lines = []
    if not 记录文件.is_file():
        lines += [
            "音频修复记录",
            "=" * 62,
            "修复链：去闷(lowshelf) → 清晰度(3.2kHz) → 空气感(9kHz)",
            "        → 裁静音(silenceremove) → 响度增益(volume，自己算的) → 限幅(alimiter，只压峰)",
            "本工具零第三方依赖：只用 ffmpeg 自带滤镜，不需要 pip 安装任何东西。",
            "",
        ]
    def 值(x, 单位="", 空="（没测到）"):
        return f"{x:.2f}{单位}" if isinstance(x, (int, float)) else 空

    频段行 = []
    if 条目.get("前频段"):
        频段行.append("")
        频段行.append("各频段 RMS（dB）—— 看 EQ 到底动了多少：")
        for 名, 前 in 条目["前频段"].items():
            后 = (条目.get("后频段") or {}).get(名)
            if 后 is None or 前 == float("-inf") or 后 == float("-inf"):
                continue
            差 = 后 - 前 - 条目.get("增益dB", 0.0)      # 扣掉整体增益，才是 EQ 的净作用
            注 = "   ← 最响的一段几乎没动：这个素材用当前风格≈没效果" \
                if (名 == "80–300 Hz" and abs(差) < 1.0) else ""
            频段行.append(f"  {名:<10} {前:>8.1f} → {后:>8.1f}   变动 {差:+.1f} dB{注}")

    lines += [
        "-" * 62,
        f"时间      : {条目['时间']}",
        f"来源文件  : {条目['来源']}",
        f"输出文件  : {条目['输出']}",
        f"模型      : {条目.get('模型', 'dsp')}"
        + (f"　⚠️ 已降级：{条目['降级原因']}" if 条目.get("降级原因") else ""),
        f"参数      : 强度={条目['强度']}  响度目标={条目['响度目标']} LUFS  "
        f"裁静音={'是' if 条目['裁静音'] else '否'}  格式={条目['格式']}  "
        f"削峰策略={条目.get('策略', '保真')}",
        "",
        "            修复前        修复后",
        f"响度 LUFS   {值(条目['前响度']):>10}   {值(条目['后响度']):>10}",
        f"真峰值 dBTP {值(条目['前真峰值']):>10}   {值(条目['后真峰值']):>10}",
        f"动态 LU     {值(条目['前动态']):>10}   {值(条目['后动态']):>10}",
        f"时长 秒     {值(条目['前时长']):>10}   {值(条目['后时长']):>10}",
        f"裁掉静音    {值(条目['裁掉秒数'])} 秒",
        *频段行,
        f"EQ 风格    {条目.get('风格', '语音')}   整体增益 {条目.get('增益dB', 0.0):+.2f} dB",
        f"变化最大   {条目.get('最大变动段', '（未测）')}（{条目.get('最大变动值', 0):+.1f} dB）",
        f"耗时        {条目['耗时']} 秒",
        "",
    ]
    记录文件.parent.mkdir(parents=True, exist_ok=True)
    with open(记录文件, "a", encoding="utf-8") as f:
        f.write("\n".join(lines))


# --------------------------------------------------------------------- 外挂通道
# 架构：主工具 → run_audio_pipeline() →（模型≠dsp 时）子进程 audio_plugin/worker.py
#       主工具**完全不 import 外挂**，只认命令行 + JSON 协议：
#           作业 {"模型","输入","输出","参数"} → 结果 {"ok","输出","耗时","消息"}
# 好处：外挂缺依赖/崩溃/卡死，主工具一律只是"这次降级"，视频插帧主流程毫发无伤。
def 外挂目录() -> Path:
    return HERE / "audio_plugin"


def 跑外挂模型(模型名: str, 输入: Path, 输出: Path, cfg: dict, 参数: dict,
               进度=None) -> tuple[bool, str, dict]:
    """把外挂当黑盒跑一遍。返回 (成功?, 消息, 统计)。**绝不抛异常。**"""
    import json as _json
    import tempfile

    入口 = 外挂目录() / "worker.py"
    if not 入口.is_file():
        return False, f"外挂目录不存在或缺少 worker.py（{外挂目录()}）", {}

    解释器 = 挑解释器(cfg)          # ← 只有这一处挑解释器，自检也走它
    超时 = float(cfg.get("音频修复_外挂超时秒") or 3600)
    with tempfile.TemporaryDirectory(prefix="pet_audio_job_") as 临时:
        作业路径 = Path(临时) / "job.json"
        结果路径 = Path(临时) / "result.json"
        作业路径.write_text(_json.dumps({
            "schema": "pet-audio-job/1", "模型": 模型名,
            "输入": str(输入), "输出": str(输出), "参数": 参数,
            "超时秒": 超时,
        }, ensure_ascii=False), encoding="utf-8")
        命令行 = [解释器, str(入口), "--作业", str(作业路径), "--结果", str(结果路径)]
        if 进度:
            进度(f"外挂模型 {模型名} 处理中…", None)
        try:
            p = subprocess.run([*主流程.priority_prefix(), *命令行],
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, timeout=超时,
                               **主流程.spawn_kwargs())
        except subprocess.TimeoutExpired:
            return False, f"外挂超时（>{超时:.0f} 秒），已放弃", {}
        except (OSError, ValueError) as exc:
            return False, f"外挂起不来：{exc}", {}
        尾巴 = (p.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        尾部 = " ｜ ".join(尾巴[-2:])[:300]
        数据 = {}
        if 结果路径.is_file():
            try:
                数据 = _json.loads(结果路径.read_text(encoding="utf-8"))
            except Exception:
                数据 = {}
        if p.returncode == 0 and 数据.get("ok"):
            return True, str(数据.get("消息") or ""), dict(数据.get("统计") or {})
        if 数据.get("消息"):
            原因 = str(数据["消息"])
        elif p.returncode < 0 or p.returncode > 1:
            # 子进程被信号打死（段错误 / os._exit 之类）——这正是"要隔离"的原因
            原因 = f"外挂进程异常退出（退出码 {p.returncode}）" + (f"：{尾部}" if 尾部 else "")
        else:
            原因 = 尾部 or f"外挂返回码 {p.returncode}"
        return False, 原因, {}


# --------------------------------------------------------------------- 封回视频
# 背景：音频修复出来的音轨，有两种去处 ——
#   ① 单独存成音频文件（听/存/当素材）
#   ② 封回原来的视频，替换掉里面的旧音轨（「视音」模式要的就是这个）
# 注意：视频流一律 `-c:v copy`（不重编码，秒级、无损）；音频按容器挑编码 ——
#       webm/mkv 能用 opus，**mp4/mov 必须用 aac**（opus 塞进 mp4 播不出来，这个坑踩过）。
视频容器音频 = {"webm": ["libopus", ["-b:a", "128k"]],
                "mkv":  ["libopus", ["-b:a", "128k"]],
                "mp4":  ["aac", ["-b:a", "192k"]],
                "mov":  ["aac", ["-b:a", "192k"]],
                "m4v":  ["aac", ["-b:a", "192k"]]}


def 有视频流(ffprobe: str, path: Path) -> bool:
    try:
        raw = capture([ffprobe, "-v", "error", "-select_streams", "v:0",
                       "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)])
        return "video" in raw
    except Exception:
        return False


def 再封装视频(ffmpeg: str, 原视频: Path, 新音频: Path, 输出: Path, 容器: str) -> tuple[bool, str]:
    """把新音频换进原视频（视频流原样复制）。返回 (成功?, 原因)。"""
    编码器, 参数 = 视频容器音频.get(容器.lower(), ("aac", ["-b:a", "192k"]))
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-v", "error",
           "-i", str(原视频), "-i", str(新音频),
           "-map", "0:v:0", "-map", "1:a:0",
           "-c:v", "copy", "-c:a", 编码器, *参数,
           "-map_metadata", "0", "-y", str(输出)]
    try:
        p = subprocess.run([*主流程.priority_prefix(), *cmd], stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           **主流程.spawn_kwargs())
    except OSError as exc:
        return False, f"起不来：{exc}"
    if p.returncode != 0 or not 输出.is_file():
        尾 = (p.stdout or b"").decode("utf-8", "replace").strip().splitlines()
        return False, (尾[-1][:200] if 尾 else "封装失败")
    return True, ""


# --------------------------------------------------------------------- 链式执行框架
# 配置示例： "音频修复_处理链路": ["dsp", "dpdfnet2"]
#   → 先跑粗修（去闷 + 裁静音，把尾部 20 分钟死寂切掉），再把这**剩下的**丢给 AI 精修
#     —— 顺序就是省算力的关键：便宜的先跑，贵的少跑。
# 每一档的约定：吃一个音频文件、吐一个音频文件（wav 中间件），失败就跳过这一档。
阶段说明 = {
    "dsp": "粗修（纯 FFmpeg 滤镜，零依赖，秒级）",
}


def 解析链路(cfg: dict) -> list[str]:
    """把配置解析成一条有序的执行链。数组优先；没写数组就按老的单模型键推导。"""
    raw = cfg.get("音频修复_处理链路")
    if isinstance(raw, (list, tuple)):
        链 = [str(x).strip() for x in raw if str(x).strip()]
        if 链:
            return 链
    模型 = str(cfg.get("音频修复模型") or "").strip()
    if 模型 in ("", "无", "none", "None"):
        return []
    return [模型]


def 阶段_粗修(ffmpeg: str, 输入: Path, 输出: Path, 强度: str, 风格: str, 裁静音: bool) -> tuple[bool, str]:
    """粗修这一档：去闷 EQ + 裁静音（**不做响度**，响度统一放到最后收尾做）。"""
    eq = 组EQ(强度, 风格)
    链 = ",".join([eq, "silenceremove=stop_periods=-1:stop_duration=0.5:stop_threshold=-50dB"] ) \
        if 裁静音 else eq
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-i", str(输入),
           "-vn", "-af", 链, "-c:a", "pcm_s16le", "-y", str(输出)]
    try:
        p = subprocess.run([*主流程.priority_prefix(), *cmd], stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           **主流程.spawn_kwargs())
    except OSError as exc:
        return False, f"起不来：{exc}"
    if p.returncode != 0 or not 输出.is_file():
        return False, p.stdout.decode("utf-8", "replace").strip().splitlines()[-1:][0][:200] \
            if p.stdout else "粗修失败"
    return True, ""


def 跑链路(ffmpeg: str, 源: Path, cfg: dict, 工作目录: Path, 进度=None) -> tuple[Path | None, list[str], str, str]:
    """按顺序跑完整条链（不含最后的收尾）。

    返回 (最终工作文件, 实际跑过的阶段, 降级说明, 用过的模型名) —— **绝不抛异常**。
    """
    import tempfile

    链 = 解析链路(cfg)
    强度 = str(cfg.get("音频修复_强度") or "标准")
    风格 = str(cfg.get("音频修复_EQ风格") or "语音")
    裁静音 = bool(cfg.get("音频修复_裁静音", True))
    降级: list[str] = []
    跑过: list[str] = []
    用过的模型: list[str] = []

    # 起点：先把音轨抽成 wav 中间件（链路里每一档都吃 wav、吐 wav）
    当前 = 工作目录 / "工作-0-原始.wav"
    if run([ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-i", str(源), "-vn",
            "-c:a", "pcm_s16le", "-y", str(当前)], "抽出音轨（链式处理用）") != 0:
        return None, [], "抽出音轨失败", ""

    for i, 档 in enumerate(链, 1):
        下一件 = 工作目录 / f"工作-{i}-{档}.wav"
        if 档 == "dsp":
            if 进度:
                进度(f"粗修（DSP）第 {i} 档…", None)
            ok, 原因 = 阶段_粗修(ffmpeg, 当前, 下一件, 强度, 风格, 裁静音)
            if ok:
                当前 = 下一件
                跑过.append("dsp")
            else:
                降级.append(f"粗修失败（{原因}）")
        else:
            if 进度:
                进度(f"AI 模型 {档} 第 {i} 档…", None)
            ok, 消息, _ = 跑外挂模型(档, 当前, 下一件, cfg,
                                    dict(cfg.get("音频修复_外挂参数") or {}), 进度)
            if ok and 下一件.is_file():
                当前 = 下一件
                跑过.append(档)
                用过的模型.append(档)
            else:
                降级.append(f"{档} 不可用（{消息}）")
    return 当前, 跑过, "；".join(降级), 用过的模型


# --------------------------------------------------------------------- 主流程
def run_audio_pipeline(源: Path | str, 输出目录: Path | None = None, *,
                       配置: dict | None = None, 进度=None, 日志=None) -> dict:
    """**主工具唯一应该调用的音频接口。** 里面用什么模型，主工具不知道也不关心。

    `日志` 是给 GUI 用的可选回调：传了之后，本次调用里每一行阶段日志
    都会额外抄一份过去（界面上的「运行日志」就是这么来的）。
    """
    if 日志 is None:
        return _跑音频(源, 输出目录, 配置=配置, 进度=进度)
    挂日志钩子(日志)
    try:
        return _跑音频(源, 输出目录, 配置=配置, 进度=进度)
    finally:
        挂日志钩子(None)          # 一定要摘掉，别把钩子留给下一次别的任务


def _跑音频(源: Path | str, 输出目录: Path | None = None, *,
            配置: dict | None = None, 进度=None) -> dict:
    """真正干活的那个（别直接调它，用上面的 run_audio_pipeline）。

    返回结果字典（永远返回，不抛异常）：
        {"ok": bool, "跳过": bool, "模型": str, "实际用了": str,
         "输出": Path|None, "降级": str, "统计": dict, "消息": str}
    """
    import tempfile

    cfg = 配置 if 配置 is not None else load_config()
    源 = Path(源)
    结果 = {"ok": False, "跳过": False, "模型": "", "实际用了": "", "输出": None,
            "降级": "", "统计": {}, "消息": ""}

    链 = 解析链路(cfg)
    结果["模型"] = "、".join(链) or "无"
    结果["链路"] = 链
    if not 链:
        结果["跳过"] = True
        结果["消息"] = "配置里「音频修复模型」是「无」（且处理链为空）—— 整条音频流程跳过"
        log("音频：配置为「无」，跳过（原样输出）")
        return 结果

    try:
        ffmpeg, ffprobe = find_ffmpeg(cfg)
    except Exception as exc:
        结果["消息"] = f"找不到 ffmpeg：{exc}"
        log(f"⚠️ 音频：{结果['消息']}")
        return 结果

    强度 = str(cfg.get("音频修复_强度") or "标准")
    响度目标 = float(cfg.get("音频修复_响度目标") or -16)
    裁静音 = bool(cfg.get("音频修复_裁静音", True))
    去齿音 = str(cfg.get("音频修复_去齿音") or 音频默认配置["音频修复_去齿音"]).strip() or "关"
    压底噪 = str(cfg.get("音频修复_压底噪") or 音频默认配置["音频修复_压底噪"]).strip() or "关"
    输出方式 = str(cfg.get("音频修复_输出方式") or 音频默认配置["音频修复_输出方式"]).strip() or "音频"
    视频容器 = str(cfg.get("音频修复_视频容器") or "").strip()
    if 输出方式 == "视频" and 裁静音:
        # 视频的长度由画面决定：把音频剪短了，尾巴就没声音了（音画不同步）。
        # 所以封回视频时**自动关掉裁静音**，并在日志里说清楚。
        log("音频：输出方式是「视频」—— 自动关掉「裁静音」（剪短音频会导致音画不同步）。")
        裁静音 = False
    输出格式 = 格式(cfg)
    eq风格 = str(cfg.get("音频修复_EQ风格") or "语音")
    策略 = str(cfg.get("音频修复_削峰策略") or "保真")
    if 输出目录 is None:
        设置 = str(cfg.get("音频修复_输出目录") or "").strip()
        输出目录 = Path(设置) if 设置 else (HERE / "output")

    # ── 执行链：["dsp"] 走单遍快路径；组合链走"逐档跑中间件"的通用路径 ──
    工作输入 = 源
    降级 = ""
    实际用了 = "dsp"
    EQ链 = None                     # None = 收尾时照常做 EQ；"" = 前面档位已经做过
    临时目录对象 = None
    log("音频链路：" + " → ".join(阶段说明.get(档, 档) for 档 in 链))
    if 链 != ["dsp"]:
        try:
            临时目录对象 = tempfile.TemporaryDirectory(prefix="pet_audio_chain_")
            最终件, 跑过, 降级, 用过的 = 跑链路(ffmpeg, 源, cfg,
                                                  Path(临时目录对象.name), 进度)
            if 最终件 is None:
                降级 = 降级 or "链路执行失败"
            else:
                工作输入 = 最终件
                EQ链 = "" if "dsp" in 跑过 else None
                实际用了 = "、".join(跑过) or "dsp"
                if 用过的:
                    log(f"音频：外挂模型 {'、'.join(用过的)} 处理完成，接下来收尾（响度+编码）")
        except Exception as exc:                       # 外挂/链路这一层怎么坏都不许往上冒
            降级 = f"{type(exc).__name__}: {exc}"
        if 降级:
            if bool(cfg.get("音频修复_降级时提醒", True)):
                log(f"⚠️ 音频外挂不可用（{降级}），**自动降级为 DSP 快修**，本次照常出结果。")

    try:
        条目 = 快修一个(ffmpeg, ffprobe, 源, Path(输出目录),
                        强度=强度, 响度目标=响度目标, 裁静音=裁静音, 格式=输出格式,
                        策略=策略, 风格=eq风格, 工作输入=工作输入, EQ链=EQ链,
                        去齿音=去齿音, 压底噪=压底噪,
                        模型=实际用了, 降级=降级, 输出方式=输出方式, 视频容器=视频容器,
                        要波形图=bool(cfg.get("音频修复_出波形图")))
    except Exception as exc:
        结果["消息"] = f"音频处理出错：{type(exc).__name__}: {exc}"
        log(f"❌ {结果['消息']}")
        临时目录对象 = None
        return 结果
    finally:
        if 临时目录对象 is not None:
            临时目录对象.cleanup()

    if 条目 is None:
        结果["消息"] = "处理失败（详见上面的日志）"
        return 结果
    结果.update({"ok": True, "实际用了": 实际用了,
                 # 视频模式：对外只报"能直接用的那个"（音轨已修复的视频）；音频文件也留着
                 "输出": 条目.get("视频输出") or 条目.get("输出路径"),
                 "音频": 条目.get("输出路径"),
                 "降级": 降级, "统计": 条目, "消息": "完成"})
    return 结果


def 快修一个(ffmpeg: str, ffprobe: str, 源: Path, 输出目录: Path, *,
             强度: str, 响度目标: float, 裁静音: bool, 格式: str,
             策略: str = "保真", 风格: str = "语音", 工作输入: Path | None = None,
             模型: str = "dsp", 降级: str = "", EQ链: str | None = None,
             去齿音: str = "关", 压底噪: str = "关",
             输出方式: str = "音频", 视频容器: str = "",
             要波形图: bool = False, 记录: bool = True) -> dict | None:
    """处理一个文件。返回本次的统计字典；失败返回 None。"""
    扩展, 编码参数 = 输出格式表.get(格式) or 输出格式表["opus"]
    输出目录.mkdir(parents=True, exist_ok=True)
    目标 = 输出目录 / f"{源.stem}-音频快修{扩展}"

    log(f"【源】{源.name}")
    输入 = Path(工作输入) if 工作输入 else 源      # 让 DSP 吃的音频（可能是链中间件）
    # 注意：记录里的「修复前」一律量**原始文件** —— 链路模式下工作输入是中间件，
    # 拿它当"前"会让记录里的对比毫无意义。
    前信息 = 取音频流信息(ffprobe, 源)
    log(f"     时长 {前信息['时长']:.1f} 秒 ｜ "
        f"{前信息['采样率']} Hz ｜ {前信息['声道']} 声道 ｜ {前信息['编码']}")
    前响度 = 测响度(ffmpeg, 源)
    前频段 = 测频段(ffmpeg, 源)
    if 前响度["响度"] is not None:
        log(f"     修复前：响度 {前响度['响度']:.2f} LUFS ｜ "
            f"真峰值 {前响度['真峰值']:.2f} dBTP ｜ 动态 {前响度['动态']:.2f} LU")

    # ── 两遍法 ────────────────────────────────────────────────
    # 第一遍：先量出"过了 EQ 之后"的真实响度（不落文件，纯分析）。
    # 第二遍：把 measured_* 喂给 loudnorm 并用 linear=true —— 用**线性增益**打准目标，
    #         不会像单遍动态模式那样让环境音忽大忽小（抽吸感）。
    eq链 = 组EQ(强度, 风格) if EQ链 is None else EQ链     # 空串 = 前面阶段已经做过 EQ
    裁静音滤镜 = ("silenceremove=stop_periods=-1:stop_duration=0.5:stop_threshold=-50dB"
                  if 裁静音 else "")
    # 关键：测量链要和最终处理链「同款」——包括裁静音那一步。
    # 因为裁掉静音本身会改变整段的积分响度（实测差 ~1 LU），不先裁再量，增益就会算歪。
    压底噪滤镜 = 压底噪档位.get(压底噪) or ""
    测量链 = ",".join(x for x in (eq链, 压底噪滤镜, 裁静音滤镜) if x)
    # ── 去齿音为什么要在测量链里 ────────────────────────────────
    # 去齿音的阈值是绝对 dBFS，只有先把电平归一到目标响度，固定阈值才有意义。
    # 但它压的正好是峰值，压完整体电平会掉 —— 如果直接放在增益之后，
    # 最终响度就会低于目标（实测「轻」低 1.2 dB、「强」低 4.0 dB）。
    # 解法：先垫一个"把素材拉到标称响度"的 G1，**让测量链也过一遍去齿音**，
    # 量出经过去齿音之后的真实响度，再算补差增益 G2。
    # 于是最终响度照样打准，去齿音也始终工作在标称电平上。
    G1 = 0.0
    if 有去齿音(去齿音) and 前响度.get("响度") is not None:
        G1 = max(-24.0, min(20.0, 响度目标 - 前响度["响度"]))
        测量链 = ",".join(x for x in (测量链, f"volume={G1:.2f}dB") if x)
    log("     第一遍：按「和最终处理同款」的链条量一遍响度（只测量，不落文件）…")
    if 有去齿音(去齿音):
        测量 = 测响度明细(ffmpeg, 输入, 响度目标=响度目标, 滤镜参数=组滤镜参数(
            测量链, f"loudnorm=I={响度目标}:TP=-1.5:LRA=11:print_format=json", 去齿音))
    else:
        测量 = 测响度明细(ffmpeg, 输入, 测量链, 响度目标)
    if 测量:
        log(f"     EQ 后实测：响度 {测量['i']:.2f} LUFS ｜ 真峰值 {测量['tp']:.2f} dBTP ｜ "
            f"动态 {测量['lra']:.2f} LU")
    增益, 说明 = 算增益(响度目标, 测量, 策略)     # 这里必须接住增益值：下面频段自检要拿它扣掉
    log(f"     增益策略「{策略}」：{说明}")

    # 顺序：去闷 EQ → 裁静音 → 增益 → （可选）去齿音 → 限幅
    # 去齿音刻意放在**增益之后**：这时整体电平已经对齐目标响度，
    # 固定阈值才有意义；放增益之前会随素材原始电平乱飘。
    if 有去齿音(去齿音):
        # 开着去齿音：前半 = EQ + 裁静音 + G1；后半 = 补差增益 G2 + 限幅
        前半 = ",".join(x for x in (eq链, 压底噪滤镜, 裁静音滤镜,
                                    (f"volume={G1:.2f}dB" if G1 else "")) if x)
        后半 = ",".join(x for x in (组增益段(响度目标, 测量, False, 策略), 限幅滤镜) if x)
        总增益 = G1 + 增益
    else:
        # 关着（老路径，一字不改）：前半 = EQ + 裁静音 + 增益；后半 = 限幅
        前半 = ",".join(x for x in (eq链, 压底噪滤镜, 组增益段(响度目标, 测量, 裁静音, 策略)) if x)
        后半 = 限幅滤镜
        总增益 = 增益
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-i", str(输入), "-vn",
           "-map_metadata", "0"]
    cmd += 组滤镜参数(前半, 后半, 去齿音)
    # opus 只吃 8/12/16/24/48 kHz；源是别的采样率就先重采样，免得直接报错
    if 格式 == "opus" and 前信息["采样率"] and 前信息["采样率"] not in OPUS_采样率:
        cmd += ["-ar", "48000"]
    cmd += 编码参数 + ["-y", str(目标)]

    起点 = time.time()
    if run(cmd, f"音频快修（{强度}档 / {格式}）") != 0:
        log("❌ ffmpeg 处理失败，跳过这个文件。")
        return None
    耗时 = time.time() - 起点

    后信息 = 取音频流信息(ffprobe, 目标)
    后响度 = 测响度(ffmpeg, 目标)
    后频段 = 测频段(ffmpeg, 目标)
    变动 = {k: 后频段[k] - v for k, v in 前频段.items() if k in 后频段
            and v > float("-inf") and 后频段[k] > float("-inf")}
    变动净 = {k: v - (总增益 or 0.0) for k, v in 变动.items()}    # 扣掉整体增益 = EQ 净作用
    最大变动段 = max(变动净, key=lambda k: abs(变动净[k])) if 变动 else "（未测）"
    if 变动:
        log(f"     频段自检（已扣掉整体增益）：最响一段净变动 "
            f"{变动净.get('80–300 Hz', 0):+.1f} dB，变化最大的是 {最大变动段}"
            f"（{变动净.get(最大变动段, 0):+.1f} dB）")
        if abs(变动净.get("80–300 Hz", 0)) < 1.0:
            log("     ⚠️ 最响的低频段几乎没动 —— 换个 EQ 风格（环境音/音乐）或更强的强度档试试。")
    裁掉 = max(0.0, 前信息["时长"] - 后信息["时长"])
    if 后响度["响度"] is not None:
        差 = 后响度["响度"] - 响度目标
        # 差为负 = 比目标小声。之前只打数字，用户看不出「离目标还差多少」，
        # 尤其「保真」策略在源峰值本来就顶到 0 的素材上会主动做小好几 dB。
        差话 = (f" （比目标{'低' if 差 < 0 else '高'} {abs(差):.1f} dB）"
                if abs(差) >= 0.5 else "  （与目标一致）")
        log(f"     修复后：响度 {后响度['响度']:.2f} LUFS ｜ "
            f"真峰值 {后响度['真峰值']:.2f} dBTP ｜ 动态 {后响度['动态']:.2f} LU{差话}")
    if 有压底噪(压底噪):
        log(f"     压底噪「{压底噪}」：已启用 —— 噪声门，安静段落的本底会被压下去")
    if 有去齿音(去齿音):
        log(f"     去齿音「{去齿音}」：已启用 —— 只压 5~10 kHz 的瞬时齿音，不整体削高频")
    log(f"     裁掉静音 {裁掉:.1f} 秒 ｜ 耗时 {耗时:.1f} 秒 ｜ 输出 {目标.name}")

    条目 = {
        "时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        "来源": str(源), "输出": str(目标),
        "强度": 强度, "响度目标": 响度目标, "裁静音": 裁静音, "格式": 格式,
        "策略": 策略,
        "前响度": 前响度["响度"], "后响度": 后响度["响度"],
        "前真峰值": 前响度["真峰值"], "后真峰值": 后响度["真峰值"],
        "前动态": 前响度["动态"], "后动态": 后响度["动态"],
        "前时长": 前信息["时长"], "后时长": 后信息["时长"],
        "裁掉秒数": 裁掉, "耗时": round(耗时, 1),
        "前频段": 前频段, "后频段": 后频段,
        "模型": 模型, "降级原因": 降级,
        "最大变动段": 最大变动段, "增益dB": 总增益 or 0.0,
        "最大变动值": (变动.get(最大变动段, 0.0) - (总增益 or 0.0)) if 变动 else 0.0,
        "风格": 风格,
    }
    if 记录:
        追加记录(输出目录 / "音频修复记录.txt", 条目)
        log(f"     记录已写入：{输出目录 / '音频修复记录.txt'}")
    if 要波形图:
        图 = 输出目录 / f"{目标.stem}-波形对比.png"
        if 出波形对比图(ffmpeg, 源, 目标, 图):
            log(f"     波形对比图：{图.name}")
    条目["输出路径"] = 目标

    # ── 要不要把修好的音轨封回原视频？（「视音」模式要的就是这一步）──
    if 输出方式 == "视频":
        容器 = (视频容器 or 源.suffix.lstrip(".")).lower()
        if not 有视频流(ffprobe, 源):
            log(f"     源不是视频（没有视频流），这一步跳过，只出音频。")
        elif 容器 not in 视频容器音频:
            log(f"     容器「{容器}」没有预设编码方案，改用 mp4/aac。")
            容器 = "mp4"
        if 有视频流(ffprobe, 源):
            视频目标 = 输出目录 / f"{源.stem}-音轨已修复.{容器}"
            ok, 原因 = 再封装视频(ffmpeg, 源, 目标, 视频目标, 容器)
            if ok:
                log(f"     已封回视频（视频流原样复制）：{视频目标.name}")
                条目["视频输出"] = str(视频目标)
            else:
                log(f"     ⚠️ 封回视频失败（{原因}），音频文件照常可用。")
    return 条目


def 收集输入(参数里的文件: list[str], cfg: dict) -> list[Path]:
    """定输入：命令行给了就用命令行的，没给就扫 input/ 目录。"""
    if 参数里的文件:
        return [Path(x) for x in 参数里的文件]
    入 = HERE / "input"
    if not 入.is_dir():
        return []
    可用的 = AUDIO_EXTS + tuple(主流程.VIDEO_EXTS)
    return sorted(p for p in 入.iterdir() if p.is_file() and p.suffix.lower() in 可用的)


def 检查环境(cfg: dict) -> int:
    hr("音频快修 · 环境检查")
    log(f"版本      : {VERSION}")
    try:
        ffmpeg, ffprobe = find_ffmpeg(cfg)
    except Exception as exc:
        log(f"✗ 找不到 ffmpeg：{exc}")
        return 1
    log(f"ffmpeg    : {ffmpeg}")
    log(f"ffprobe   : {ffprobe}")
    log(f"输出格式  : {格式(cfg)}（可在 config.json 里改「音频修复_输出格式」）")
    log(f"强度      : {cfg.get('音频修复_强度') or 音频默认配置['音频修复_强度']}")
    log(f"响度目标  : {cfg.get('音频修复_响度目标') or 音频默认配置['音频修复_响度目标']} LUFS")
    log(f"裁静音    : {cfg.get('音频修复_裁静音', True)}")
    log("滤镜链    : " + 组滤镜链(str(cfg.get("音频修复_强度") or "标准"),
                                   float(cfg.get("音频修复_响度目标") or -16),
                                   bool(cfg.get("音频修复_裁静音", True))))
    模型 = str(cfg.get("音频修复模型") or 音频默认配置["音频修复模型"])
    log(f"音频模型  : {模型}"
        + ("（自带 DSP 快修，零依赖）" if 模型 == "dsp" else
           "（整条跳过）" if 模型 == "无" else "（走外挂子进程）"))
    入口 = 外挂目录() / "worker.py"
    if not 入口.is_file():
        log("外挂      : 不在位（只用 DSP 也能干活）")
    else:
        try:
            # 用**外挂真正会用的那个**解释器自检，不然报的依赖是别处的
            检查器 = 挑解释器(cfg)
            r = subprocess.run([检查器, str(入口), "--自检"],
                               capture_output=True, text=True, timeout=60,
                               **主流程.spawn_kwargs())
            data = json.loads(r.stdout or "{}")
            可用 = {k: v for k, v in (data.get("模型") or {}).items()}
            log(f"外挂      : 在位，解释器 {data.get('解释器')}，模型 "
                + "、".join(f"{k}{'✓' if v[0] else '✗(' + (v[1] or '')[:40] + ')'}" for k, v in 可用.items()))
        except Exception as exc:
            log(f"外挂      : 在位但自检失败：{exc}")
    log("✓ 本模块零第三方依赖，环境只要 ffmpeg 就够（AI 模型另算，缺了自动降级）。")
    return 0


def 格式(cfg: dict) -> str:
    return str(cfg.get("音频修复_输出格式") or 音频默认配置["音频修复_输出格式"]).lower()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="音频快修（去闷 / 提清晰度 / 响度标准化 / 裁静音）—— 零第三方依赖",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("文件", nargs="*", help="要处理的音频或视频文件；不填就扫 input/ 目录")
    p.add_argument("--强度", choices=list(强度档位), help="轻 / 标准 / 重（默认取 config）")
    p.add_argument("--响度", type=float, dest="响度目标", help="目标响度 LUFS，默认 -16")
    p.add_argument("--格式", choices=list(输出格式表), help="opus（默认）/ mp3 / flac / wav")
    p.add_argument("--不裁静音", action="store_true", help="只去闷+提亮+标准化，不剪时长")
    p.add_argument("--模型", help="音频模型：无 / dsp（自带零依赖）／外挂里的模型名（如 dpdfnet2）")
    p.add_argument("--风格", choices=["语音", "环境音"],
                   help="EQ 风格：语音（默认，治人声发闷）/ 环境音（治音乐、环境音能量堆积）")
    p.add_argument("--策略", choices=["保真", "保响度"],
                   help="保真（默认）=受真峰值限制时宁可小声也不削峰；保响度=优先打到目标响度")
    p.add_argument("--波形图", action="store_true", help="顺带输出前后波形对比图")
    p.add_argument("--检查", action="store_true", help="只检查环境，不干活")
    args = p.parse_args(argv)

    cfg = load_config()
    if args.检查:
        return 检查环境(cfg)

    ffmpeg, ffprobe = find_ffmpeg(cfg)
    源列表 = 收集输入(args.文件, cfg)
    if not 源列表:
        log("没有可处理的文件。")
        log("    · 用法：python audio_fix.py 某个音频.mp3")
        log("    · 或者把文件放进 input/ 目录再跑一次")
        return 1

    强度 = args.强度 or str(cfg.get("音频修复_强度") or 音频默认配置["音频修复_强度"])
    if 强度 not in 强度档位:
        log(f"⚠️ config 里的强度「{强度}」不认识，改用「标准」。")
        强度 = "标准"
    响度目标 = args.响度目标 if args.响度目标 is not None else float(
        cfg.get("音频修复_响度目标") or 音频默认配置["音频修复_响度目标"])
    裁静音 = (not args.不裁静音) and bool(cfg.get("音频修复_裁静音", True))
    输出格式 = args.格式 or 格式(cfg)
    if 输出格式 not in 输出格式表:
        log(f"⚠️ config 里的输出格式「{输出格式}」不认识，改用 opus。")
        输出格式 = "opus"

    eq风格 = args.风格 or str(cfg.get("音频修复_EQ风格") or 音频默认配置["音频修复_EQ风格"])
    if eq风格 not in ("语音", "环境音"):
        log(f"⚠️ config 里的 EQ 风格「{eq风格}」不认识，改用「语音」。")
        eq风格 = "语音"
    策略 = args.策略 or str(cfg.get("音频修复_削峰策略") or 音频默认配置["音频修复_削峰策略"])
    if 策略 not in ("保真", "保响度"):
        log(f"⚠️ config 里的削峰策略「{策略}」不认识，改用「保真」。")
        策略 = "保真"

    输出目录设置 = str(cfg.get("音频修复_输出目录") or "").strip()
    输出目录 = Path(输出目录设置) if 输出目录设置 else (HERE / "output")

    hr(f"{VERSION} · 共 {len(源列表)} 个文件")
    log(f"强度 {强度} ｜ EQ 风格 {eq风格} ｜ 响度目标 {响度目标} LUFS ｜ "
        f"裁静音 {'是' if 裁静音 else '否'} ｜ 输出格式 {输出格式}")
    log(f"输出目录：{输出目录}")

    # 把命令行选项并回配置，然后统一走唯一的对外入口 run_audio_pipeline()
    cfg = dict(cfg)
    cfg.update({"音频修复_强度": 强度, "音频修复_响度目标": 响度目标,
                "音频修复_裁静音": 裁静音, "音频修复_EQ风格": eq风格,
                "音频修复_削峰策略": 策略, "音频修复_出波形图": args.波形图})
    if args.模型:
        cfg["音频修复模型"] = args.模型
    if args.格式:
        cfg["音频修复_输出格式"] = args.格式

    成功 = 0
    for i, 源 in enumerate(源列表, 1):
        hr(f"[{i}/{len(源列表)}]")
        if not 源.is_file():
            log(f"⚠️ 找不到文件，跳过：{源}")
            continue
        结果 = run_audio_pipeline(源, 输出目录, 配置=cfg)
        if 结果["ok"]:
            成功 += 1
        elif 结果["跳过"]:
            log(f"　（{结果['消息']}）")
        else:
            log(f"❌ 这个文件出错了，跳过：{结果['消息']}")

    hr(f"完成：成功 {成功} / 共 {len(源列表)}")
    return 0 if 成功 else (0 if any(p.is_file() for p in 源列表) and 结果.get("跳过") else 1)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已中断。")
        sys.exit(130)
    except Exception as exc:  # 兜底：不要让窗口一闪而过
        print(f"\n出错了：{exc}")
        try:
            input("\n按回车键关闭…")
        except Exception:
            pass
        sys.exit(1)
