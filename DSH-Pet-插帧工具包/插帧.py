#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DSH Pet 素材定制插帧工具
=========================
把桌宠的 webm 动画按你设定的目标帧率做插帧，保留 Alpha 透明通道，输出 webm。

原理（三步）：
    1. 拆帧   把 webm 拆成 彩色帧 + 透明通道帧 两组 png
    2. 插帧   用 RIFE 把两组各自补到目标帧数
    3. 合成   把彩色和透明通道合成，编码成带 Alpha 的 VP9 webm

设计原则：**零第三方 Python 依赖**，只调用系统里的 ffmpeg 和 rife-ncnn-vulkan。
（这样最不容易在别人机器上装不上。）

用法：
    python 插帧.py              处理 input/ 里的全部素材
    python 插帧.py --检查        只检查环境，不干活
    python 插帧.py --试跑 1      只处理 1 个文件，先确认没问题
    python 插帧.py --模型 rife-anime
    python 插帧.py 某个文件.webm  也可以直接指定一个文件

作者：群友分享，AI 辅助编写。仅供学习交流。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

# 版本号。GUI 和日志头部都会打它 —— 出问题时报这个号最快的定位方式。
VERSION = "v0.9"

DEFAULT_CONFIG = {
    "_说明": "改这个文件就行，改完保存，再运行「一键插帧」。所有路径留空 = 自动在系统里找。",
    "目标帧率": 72,
    "插帧模型": "rife-v4.6",
    "使用第几块显卡": 0,
    "视频质量CRF": 32,
    "视频码率kbps": 0,
    "编码速度cpu-used": 4,
    "编码实时模式": True,
    "编码线程数": 0,
    "rife读写线程": "1:2:2",
    "安全倍数上限": 3.0,
    "允许超过安全倍数": False,
    "只处理前N个文件": 0,
    "ffmpeg路径": "",
    "rife可执行文件路径": "",
    "rife模型所在目录": "",
    "处理完删除临时帧": True,
}

# 可以用 -n 自定义输出帧数的模型（只有 rife-v4 系列支持）
CUSTOM_FRAME_MODELS = ("rife-v4",)

# 认哪些输入后缀。
# 放这么宽是有意的：真正"能不能处理"由 ffprobe 说了算，这儿只负责
# 别去把 .txt / .jpg 当素材试。作者以后换格式（mp4 / mkv / 动图），
# 只要在这个名单里就不用改代码。
VIDEO_EXTS = (".webm", ".mkv", ".mp4", ".mov", ".m4v", ".avi", ".wmv",
              ".flv", ".ts", ".m2ts", ".mpg", ".mpeg", ".ogv", ".3gp",
              ".webp", ".gif", ".apng")

# 输出永远是 webm —— 带透明的视频，实际能用的容器只有它。
# 所以不管喂进来的是 mp4 还是 mkv，出来的统一是 .webm。
OUT_EXT = ".webm"

# 各编码对应的「显式解码器」参数。
# 为什么非指定不可：不给解码器的话，某些容器里的 VP9 / AV1 的 alpha 通道
# 压根不会被解出来，ffprobe 会老老实实报 yuv420p —— 让你以为素材没透明。
# 表里没有的编码一律交回给 ffmpeg 自己认（实测 h264、mpeg4 这些都认得很准）。
DECODER_ARGS = {
    "vp9": ["-c:v", "libvpx-vp9"],
    "vp8": ["-c:v", "libvpx"],
    "av1": ["-c:v", "libdav1d"],
}

# webm 容器只认这几家的音轨，其它一律得转码 —— 否则 ffmpeg 会直接
# 拒绝写文件（"Only VP8/VP9/AV1 video and Vorbis/Opus audio are supported"）。
WEBM_AUDIO_OK = ("opus", "vorbis")

# 带 alpha 的像素格式前缀（用来判断素材到底有没有透明通道）
ALPHA_PIX_FMT_PREFIX = ("yuva", "rgba", "bgra", "argb", "abgr",
                        "ya8", "ya16", "gbrap", "pal8")


def decoder_args(codec: str) -> list[str]:
    return DECODER_ARGS.get((codec or "").lower(), [])


def has_alpha_fmt(pix_fmt: str) -> bool:
    p = (pix_fmt or "").lower()
    return any(p.startswith(pre) for pre in ALPHA_PIX_FMT_PREFIX)


def alpha_plane_is_empty(ffmpeg: str, adir: Path) -> bool:
    """扫一遍拆出来的 alpha 帧，看整段到底有没有**真正的**透明像素。

    为什么要扫这个：
      有些格式（最典型的是 GIF）会声明一个透明索引，但根本不用它。
      解出来的像素格式是带 alpha 的（bgra），于是本工具一路按"有透明"处理 ——
      白跑一整轮 alpha 插帧（实测多花 30% 时间），输出还莫名其妙带个
      全空的 yuva420p。
      实测案例：群里抓的一张 GIF 表情，143×143，声明 bgra，
      但 100% 像素的 alpha 都是 255 —— 整段压根没有透明。

    怎么扫：把已经躺在磁盘上的 alpha png 缩成 32×32 再拼成原始灰度流，
    一次读完看最小值。
      · 覆盖全部帧，不抽样 —— 不会漏掉"只有某几帧有透明"的情况
      · 读的是拆帧的产物，不用重新解码源视频，代价零点几秒
      · 缩图的风险是"极小的透明点被平均掉"，所以阈值放到 250
        （只要有一处平均下来低于 250 就认为有真透明）

    拿不准的时候一律返回 False（= 当它有 alpha）—— 宁可白跑一轮，
    也绝不能把真的透明给丢了。
    """
    data = capture_raw([ffmpeg, "-nostdin", "-v", "error",
                        "-i", str(adir / "%05d.png"),
                        "-vf", "scale=32:32,format=gray",
                        "-f", "rawvideo", "-"])
    if not data:
        return False
    return min(data) >= 250


# --------------------------------------------------------------------- 调度
# 下面这两个是全局的，由 main() 在开跑前按「性能模式」设定一次。
# 为什么用全局而不是往每个函数里传参：run()/capture() 一轮会被调用几百次，
# 而优先级在整轮里不会变，传参只会把一堆函数签名搞脏。
_NICE_LEVEL = 0            # 0 = 不降级
_IONICE_IDLE = False       # True = 磁盘 IO 也降到「空闲级」
_WIN_FLAGS = 0             # Windows 上等价于 nice 的东西（进程优先级类）


def detect_cpus() -> tuple[int, str]:
    """数一下这台机器实际能用几个逻辑核。

    为什么用 sched_getaffinity 而不是只看 os.cpu_count()：
    cpu_count() 报的是整机核数，而进程如果被 taskset / cgroup 限制过、
    或者跑在容器里，实际能用的没那么多 —— 按整机核数算会算多，
    结果就是把机器压垮。
    """
    total = os.cpu_count() or 1
    if hasattr(os, "sched_getaffinity"):
        try:
            usable = len(os.sched_getaffinity(0))
            if usable and usable != total:
                return max(1, usable), f"（整机 {total} 核，本进程只能用 {usable} 个）"
            if usable:
                return max(1, usable), ""
        except OSError:
            pass
    return max(1, total), ""


def plan_performance(mode: str, cpus: int) -> dict:
    """按「性能模式」和核数算一套参数。

    设计依据（都是实测出来的）：
      · 本工具的编码（cpu-used=4 + realtime）只吃约 2.2 个核。
        所以核多的机器**根本不用限制线程** —— 限制了只是白白变慢。
      · 真正需要限制的是小机器（4 核及以下），那里 2.2 个核已经是半台机器。
      · 降优先级（nice）不是"少占"，而是"忙时让路、闲时全速"。
        实测：机器空着时 nice 0 和 nice 19 是 5.9 / 6.2 秒，等于零成本；
        机器被压满时，nice 19 把对用户的干扰从 +11.5% 降到 +5.2%，
        代价只是自己慢 7%。
    """
    m = (mode or "auto").strip().lower()
    if m in ("全速", "fast", "full"):
        return {"threads": 0, "rife_j": "1:2:2", "nice": 0, "ionice": False,
                "why": "全速模式：不限制线程，也不降优先级"}
    if m in ("省电", "eco", "low"):
        return {"threads": max(1, cpus // 2), "rife_j": "1:1:1", "nice": 19,
                "ionice": True,
                "why": f"省电模式：{cpus} 核 → 编码 {max(1, cpus // 2)} 线程，"
                       f"rife 降到 1:1:1，优先级降到底"}
    if m in ("手动", "manual", "off"):
        return {"threads": None, "rife_j": None, "nice": 0, "ionice": False,
                "why": "手动模式：线程参数完全按 config 里填的来，不动优先级"}

    if cpus >= 5:
        return {"threads": 0, "rife_j": "1:2:2", "nice": 10, "ionice": True,
                "why": f"{cpus} 核够用（编码实测只吃约 2.2 核）→ 编码不限线程；"
                       f"但优先级压低，你干别的时它自动让路"}
    return {"threads": max(1, cpus - 2), "rife_j": "1:2:2", "nice": 10,
            "ionice": True,
            "why": f"只有 {cpus} 核 → 编码限制成 {max(1, cpus - 2)} 线程，"
                   f"留出核给你自己用；同时压低优先级"}


def priority_prefix() -> list[str]:
    """给外部命令前面挂上「降优先级」的命令（Linux / macOS）。"""
    if os.name == "nt" or _NICE_LEVEL <= 0:
        return []
    pre: list[str] = []
    if shutil.which("nice"):
        pre += ["nice", "-n", str(_NICE_LEVEL)]
    if _IONICE_IDLE and shutil.which("ionice"):
        # -c 3 = idle 级：只有磁盘完全闲着的时候才轮到本工具读写。
        # 一趟插帧要写几百上千张小 png，落在机械盘上能把整机拖到卡顿 —— 这条最管用。
        pre += ["ionice", "-c", "3"]
    return pre


def looks_memory_backed(p: Path) -> str:
    """看看这个目录是不是内存盘，是的话返回一句人话说明。"""
    try:
        mounts = Path("/proc/mounts").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    best = ""
    for line in mounts.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        mp, fstype = parts[1], parts[2]
        if fstype in ("tmpfs", "ramfs") and (
                str(p) == mp or str(p).startswith(mp.rstrip("/") + "/")):
            if len(mp) > len(best):
                best = mp
    return "内存盘（快、不碰硬盘）" if best else ""


def win_ram_disk() -> str:
    """Windows：找一个「虚拟内存盘」，有就优先拿它放中间帧。

    国内不少人装了内存盘（魔盘 / ImDisk 之类）。中间帧是几百 MB 的小文件，
    放内存盘能省掉一整轮磁盘读写 —— 对系统盘是机械硬盘的机器尤其明显。
    """
    if os.name != "nt":
        return ""
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        DRIVE_RAMDISK = 6
        mask = k32.GetLogicalDrives()
        for i in range(26):
            if not (mask >> i) & 1:
                continue
            root = f"{chr(65 + i)}:\\"
            if k32.GetDriveTypeW(ctypes.c_wchar_p(root)) == DRIVE_RAMDISK:
                return root
    except Exception:
        pass
    return ""


def pick_temp_dir(cfg: dict) -> tuple[Path | None, str]:
    """挑一个放中间帧的地方。返回 (目录，None 表示用系统默认) 和说明。

    为什么值得专门挑：一趟插帧要拆出几百上千张小 png（几百 MB）。
    这些文件落在机械硬盘上，会把整台机器拖得一顿一顿的 ——
    这比吃 CPU 更容易让人骂人。Linux 的 /tmp 通常已经是内存盘（白拿优势），
    但 Windows 的 %TEMP% 在系统盘上，那边才真的需要挑。
    """
    raw = str(cfg.get("临时帧目录") or "").strip()
    if raw:
        p = Path(raw).expanduser()
        try:
            p.mkdir(parents=True, exist_ok=True)
            free = shutil.disk_usage(p).free
            return p, f"按配置指定 → {p}（剩余 {free / 1024 ** 3:.0f} GB）"
        except OSError as exc:
            return None, f"配置里的「临时帧目录」用不了（{exc}），改用系统默认"

    if os.name == "nt":
        rd = win_ram_disk()
        if rd:
            try:
                free = shutil.disk_usage(rd).free
                if free >= 2 * 1024 ** 3:
                    return (Path(rd) / "dshpet_tmp",
                            f"发现内存盘 {rd}（剩余 {free / 1024 ** 3:.0f} GB）→ 中间帧放这儿")
            except OSError:
                pass
        tmp = Path(tempfile.gettempdir())
        try:
            free = shutil.disk_usage(tmp).free / 1024 ** 3
        except OSError:
            return None, "系统临时目录"
        note = f"系统临时目录 → {tmp}（剩余 {free:.0f} GB）"
        note += ("\n      💡 如果这个盘是机械硬盘，建议在 config.json 里把「临时帧目录」"
                 "\n         指到 SSD 或内存盘上 —— 中间帧一趟好几百 MB，能明显减少卡顿。")
        return None, note

    # Linux / macOS：优先内存盘
    for cand in ("/dev/shm", "/tmp"):
        p = Path(cand)
        if not p.is_dir():
            continue
        kind = looks_memory_backed(p)
        if not kind:
            continue
        try:
            free = shutil.disk_usage(p).free
        except OSError:
            continue
        if free >= 1 * 1024 ** 3:
            return p, f"{cand}（{kind}，剩余 {free / 1024 ** 3:.1f} GB）"
    tmp = Path(tempfile.gettempdir())
    return None, f"系统临时目录 → {tmp}"


# --------------------------------------------------------------------- 小工具
def log(msg: str) -> None:
    print(msg, flush=True)


def hr(title: str = "") -> None:
    if title:
        log("\n" + "=" * 62)
        log(f"  {title}")
        log("=" * 62)
    else:
        log("-" * 62)


# 会被「行尾修复」处理的文本文件后缀（.bat 必须保留 CRLF，所以排除在外）
FIX_EXTS = {".sh", ".command", ".py", ".json", ".txt", ".md"}


def fix_line_endings() -> list[str]:
    """把同目录下脚本的行尾从 CRLF 修回 LF。

    为什么要有这个：zip 在 Windows 上被解压/编辑后，.sh 很容易带上 CRLF，
    跑起来就是一堆 "$'\\r': command not found" —— 而 bash 自己没法自救
    （它读到 CR 就已经崩了）。Python 不在乎行尾，所以由它来修最稳。
    """
    fixed = []
    for p in sorted(HERE.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in FIX_EXTS:
            continue
        try:
            raw = p.read_bytes()
        except OSError:
            continue
        if b"\r" not in raw:
            continue
        p.write_bytes(raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n"))
        fixed.append(str(p.relative_to(HERE)))
    return fixed


def spawn_kwargs() -> dict:
    """建子进程时要带的参数（Windows 专用）。

    Windows 上没有 nice，等价物是「进程优先级类」——
    BELOW_NORMAL_PRIORITY_CLASS 就是 Windows 版的 nice。
    这两个常量都由标准库 subprocess 提供，不用引任何第三方依赖。

    另外必须带 CREATE_NO_WINDOW：不带的话，GUI 版每起一个 ffmpeg /
    rife 都会在屏幕上闪一个黑色命令行窗口，批处理时会弹出几十个。
    """
    kw: dict = {}
    if os.name == "nt":
        flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
        if _WIN_FLAGS:
            flags |= _WIN_FLAGS
        kw["creationflags"] = flags
    return kw


def run(cmd: list[str], desc: str = "") -> int:
    """跑一个外部命令。

    两个关键点：
      · stdin 一律给空，绝不让子进程去抢输入流（踩过坑，见 README）
      · 前面挂上降优先级的命令，这样机器忙的时候它会自己让路
    """
    try:
        p = subprocess.run([*priority_prefix(), *cmd], stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           **spawn_kwargs())
    except FileNotFoundError:
        raise RuntimeError(f"找不到程序：{cmd[0]}")
    if p.returncode != 0 and desc:
        tail = p.stdout.decode("utf-8", "replace").strip().splitlines()[-6:]
        log(f"    ✗ {desc} 失败：")
        for line in tail:
            log(f"      {line}")
    return p.returncode


def capture_raw(cmd: list[str]) -> bytes:
    """跑一条命令，把 stdout 当**原始字节**收回来（不是文本）。"""
    try:
        p = subprocess.run([*priority_prefix(), *cmd], stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           **spawn_kwargs())
        return p.stdout
    except (FileNotFoundError, OSError):
        return b""


def capture(cmd: list[str]) -> str:
    try:
        p = subprocess.run([*priority_prefix(), *cmd], stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           **spawn_kwargs())
        return p.stdout.decode("utf-8", "replace").strip()
    except FileNotFoundError:
        return ""


# --------------------------------------------------------------------- 读配置
def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    path = HERE / "config.json"
    if path.is_file():
        raw = path.read_bytes()
        data = None
        # 依次尝试 utf-8 / 带BOM的utf-8 / GBK —— Windows 记事本可能存成 GBK
        for enc in ("utf-8", "utf-8-sig", "gbk"):
            try:
                data = json.loads(raw.decode(enc))
                break
            except Exception:
                continue
        if isinstance(data, dict):
            for k, v in data.items():
                if not k.startswith("_") or k == "_说明":
                    cfg[k] = v
        else:
            log("⚠️ config.json 读不出来（可能格式写错了），本次用默认配置继续。")
    return cfg


# --------------------------------------------------------------------- 找程序
def find_ffmpeg(cfg: dict) -> tuple[str, str]:
    """返回 (ffmpeg, ffprobe)。"""
    f = str(cfg.get("ffmpeg路径") or "").strip()
    if f:
        p = Path(f)
        if p.is_dir():
            exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
            f = str(p / exe)
        probe = str(Path(f).with_name(Path(f).name.replace("ffmpeg", "ffprobe")))
        if Path(f).exists():
            return f, probe
        log(f"⚠️ 配置里的 ffmpeg 路径不存在：{f}，改为自动查找。")

    ff = shutil.which("ffmpeg")
    fp = shutil.which("ffprobe")
    if ff and fp:
        return ff, fp

    # 常见位置兜底
    for cand in ("/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/opt/homebrew/bin/ffmpeg"):
        if Path(cand).exists():
            return cand, cand.replace("ffmpeg", "ffprobe")
    raise RuntimeError(
        "找不到 ffmpeg / ffprobe。\n"
        "    · Windows：去 https://www.gyan.dev/ffmpeg/builds/ 下 ffmpeg-release-essentials.zip，\n"
        "      解压后把 bin 目录里的 ffmpeg.exe / ffprobe.exe 放到本工具包目录下即可。\n"
        "    · macOS：brew install ffmpeg\n"
        "    · Linux：sudo apt install ffmpeg"
    )


def find_rife(cfg: dict, model: str) -> tuple[str, Path]:
    """返回 (rife可执行文件, 模型目录)。

    模型目录这块要啰嗦一点，因为三个平台放模型的位置不一样：
      · Windows / Linux：模型就在可执行文件旁边（解压出来啥样就啥样）
      · macOS：发布包是 rife-ncnn-vulkan.app，可执行文件在
        Contents/MacOS/ 下，而模型可能在 Contents/MacOS/ 或 Contents/Resources/
    所以这里按几个候选位置依次找，谁有那个模型就用谁。
    """
    exe = str(cfg.get("rife可执行文件路径") or "").strip()
    model_dir = str(cfg.get("rife模型所在目录") or "").strip()

    if exe and Path(exe).exists():
        exe_p = Path(exe)
    else:
        if exe:
            log(f"⚠️ 配置里的 rife 路径不存在：{exe}，改为自动查找。")
        name = "rife-ncnn-vulkan.exe" if os.name == "nt" else "rife-ncnn-vulkan"
        found = shutil.which(name)
        if not found:
            # 在本工具包目录及子目录里找（macOS 的 .app 也能被 ** 穿进去）
            for p in sorted(HERE.glob("**/" + name)):
                if p.is_file():
                    found = str(p)
                    break
        if not found:
            mac_hint = (
                "    · macOS 注意：发布包是个 rife-ncnn-vulkan.app 包，\n"
                "      整个丢进本工具包目录就行，不用进去找。\n" if sys.platform == "darwin" else ""
            )
            raise RuntimeError(
                "找不到 rife-ncnn-vulkan。\n"
                "    去这里下载预编译包（选自己系统的那个）：\n"
                "    https://github.com/nihui/rife-ncnn-vulkan/releases\n"
                "    国内打不开就用中转：https://gh-proxy.com/https://github.com/nihui/rife-ncnn-vulkan/releases\n"
                "    解压后把整个文件夹放到本工具包目录下，或者在本配置里填绝对路径。\n"
                + mac_hint
            )
        exe_p = Path(found)

    # 用户明确指定了模型目录 → 直接用
    if model_dir:
        md = Path(model_dir)
        if not md.is_dir():
            raise RuntimeError(f"rife 模型目录不存在：{md}")
        return str(exe_p), md

    # 自动找：可执行文件附近那几个常见位置，谁有目标模型用谁
    parent = exe_p.parent
    cands = [
        parent,                                    # 同级（Win/Linux 常见）
        parent.parent,                             # .app/Contents/MacOS 的上一层
        parent.parent / "Resources",               # .app/Contents/Resources（macOS 常见）
        parent.parent.parent / "Resources",
        HERE,                                      # 工具包根目录
    ]
    seen: set[Path] = set()
    for c in cands:
        try:
            if c in seen or not c.is_dir():
                continue
        except OSError:
            continue
        seen.add(c)
        if model_ok(c, model):
            return str(exe_p), c

    # 再兜底：在可执行文件附近和工具包目录里翻两三层
    for base in (parent, HERE):
        try:
            for p in base.glob("**/" + model):
                if p.is_dir():
                    return str(exe_p), p.parent
        except OSError:
            continue

    log(f"⚠️ 没找到放模型的目录（想要 {model}），先按可执行文件同目录试：{parent}")
    return str(exe_p), parent


def model_ok(md: Path, model: str) -> bool:
    for cand in (md / model, md / "rife" / model):
        if cand.is_dir():
            return True
    return False


# --------------------------------------------------------------------- 显卡预检
# 两张 64x64 的纯色 PNG（纯标准库手搓，一个 136 字节）。
# 为什么内嵌而不是临时生成：预检发生在「环境检查」阶段，那时还不能假设 ffmpeg
# 一定可用；内嵌进来就一个外部依赖都不欠。
_PROBE_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAT0lEQVR42u3PQQkAAAgEsItz/VMYywi+hcEKLNO+FgEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQGBywLvDoEAVSaz4wAAAABJRU5ErkJggg==",
    "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAT0lEQVR42u3PQQkAAAgEsItz/VMYywi+hcEKLO28FgEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQGBywLt4oEAvGaPlQAAAABJRU5ErkJggg==",
)

# rife 启动时会把枚举到的设备打成这种行：[0 NVIDIA GeForce RTX 2060]  queueC=2[8] ...
_GPU_LINE = re.compile(r"^\[(\d+)\s+([^\]]+?)\]\s")

# 名字里带这些的 = 软件渲染（没显卡驱动时才出现），慢到没法用
_SOFT_RENDER = ("llvmpipe", "swiftshader", "softpipe", "lavapipe", "soft render")
# 名字里带这些的 = 核显。能跑，但比独显慢一截
_INTEGRATED = ("intel", "uhd graphics", "hd graphics", "iris", "radeon graphics",
               "radeon vega", "microsoft basic")


def check_gpus(rife: str, model: str) -> tuple[list[tuple[int, str]], str]:
    """跑一次最小任务，让 rife 自己把能用的显示设备报出来。

    为什么要让它自己报：命令行上 -g 只是个序号，序号背后是哪块卡只有 rife 知道。
    光看参数永远发现不了「你以为在用独显，其实一直在跑核显」这种事。

    返回 ([(序号, 名字), ...], 日志最后一行)。拿不到列表时返回 ([], 线索)。
    """
    tmp = Path(tempfile.mkdtemp(prefix="dshpet_gpu_"))
    try:
        for i, blob in enumerate(_PROBE_PNG):
            (tmp / f"{i}.png").write_bytes(base64.b64decode(blob))
        try:
            p = subprocess.run(
                [rife, "-0", str(tmp / "0.png"), "-1", str(tmp / "1.png"),
                 "-o", str(tmp / "out.png"), "-m", model],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, timeout=120)
            text = p.stdout.decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            return [], "预检超时（120 秒没动静）"
        except (FileNotFoundError, OSError):
            return [], "跑不起来（文件不存在？）"
        devs, seen = [], set()
        for line in text.splitlines():
            m = _GPU_LINE.match(line.strip())
            if m:
                idx, name = int(m.group(1)), m.group(2).strip()
                if idx not in seen:
                    seen.add(idx)
                    devs.append((idx, name))
        devs.sort()
        lines = [ln for ln in (l.strip() for l in text.splitlines()) if ln]
        return devs, (lines[-1] if lines else "")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def is_soft(name: str) -> bool:
    n = name.lower()
    return any(k in n for k in _SOFT_RENDER)


def is_integrated(name: str) -> bool:
    n = name.lower()
    return any(k in n for k in _INTEGRATED)


# 名字里带这些的，基本可以确定是独显
_DISCRETE_HINT = ("nvidia", "geforce", "quadro", "rtx ", "gtx ", "tesla",
                  "radeon rx", "radeon pro", "arc a", "arc b", "apple m")


def pick_best_gpu(devs: list[tuple[int, str]]) -> tuple[int | None, str]:
    """从 rife 报出来的设备里挑一块最该用的，返回 (序号, 挑它的理由)。

    挑选优先级：独显 → 核显 → 软件渲染。
    为什么默认自动挑而不是让用户填序号：大部分人根本不知道自己是哪块卡，
    笔记本上更是核显排在 [0]、独显排在 [1] —— 默认值 0 会让人一直在跑核显，
    还以为是这工具就这样慢。
    """
    if not devs:
        return None, "没有可用设备"

    # 一、先找名字明确像独显的
    for i, name in devs:
        if is_soft(name) or is_integrated(name):
            continue
        if any(k in name.lower() for k in _DISCRETE_HINT):
            return i, "独显"

    # 二、没有明确标记的，就找第一块"不像核显也不像软件渲染"的
    for i, name in devs:
        if not is_soft(name) and not is_integrated(name):
            return i, "不是核显的那块"

    # 三、没独显，退而用核显
    for i, name in devs:
        if not is_soft(name):
            return i, "没找到独显，退用核显"

    # 四、只剩软件渲染了
    return devs[0][0], "只有软件渲染可用（会很慢）"


# --------------------------------------------------------------------- 探素材
def probe(ffprobe: str, path: Path) -> dict:
    """读出容器、编码、宽高、帧率、帧数、时长、是否带 Alpha、音轨编码。

    探测分两步走，为的是「既准又快」：
      第一步  不带解码器问一次 —— 拿到编码名、尺寸、帧率。
              不带解码器是最快的，而且对 h264 / mpeg4 这些认得很准。
      第二步  只有当编码属于「可能带 alpha」的那几种（vp9 / vp8 / av1）时，
              才带上对应的显式解码器再问一次。
    为什么第二步必不可少：不给解码器的话，某些容器里 VP9 / AV1 的 alpha
    通道根本不会被解出来，ffprobe 会报成 yuv420p —— 让你以为素材没透明，
    于是输出不带 alpha 的 webm，桌宠上就是一块白底。
    """
    info = {"w": 0, "h": 0, "fps": 0.0, "frames": 0, "dur": 0.0,
            "alpha": False, "codec": "", "container": "", "audio": ""}

    def ask(extra: list[str]) -> str:
        return capture([ffprobe, "-v", "error", *extra, "-select_streams", "v:0",
                        "-show_entries",
                        "stream=width,height,r_frame_rate,pix_fmt,nb_frames,codec_name",
                        "-of", "default=nw=1", str(path)])

    def parse(text: str) -> None:
        for line in text.splitlines():
            k, _, val = line.partition("=")
            k, val = k.strip(), val.strip()
            if k == "width" and val.isdigit():
                info["w"] = int(val)
            elif k == "height" and val.isdigit():
                info["h"] = int(val)
            elif k == "r_frame_rate" and "/" in val:
                n, d = val.split("/")
                if float(d or 1) > 0:
                    info["fps"] = float(n) / float(d)
            elif k == "pix_fmt":
                info["alpha"] = has_alpha_fmt(val)
            elif k == "nb_frames" and val.isdigit():
                info["frames"] = int(val)
            elif k == "codec_name":
                info["codec"] = val

    text = ask([])
    parse(text)
    codec = info["codec"].lower()
    # 只有这几类才值得再问一次（其它编码的 alpha 探测没有这个坑，省一次子进程）
    if codec in DECODER_ARGS:
        text2 = ask(DECODER_ARGS[codec])
        if "width=" in text2:
            parse(text2)

    info["audio"] = audio_codec(ffprobe, path)
    cline = capture([ffprobe, "-v", "error", "-show_entries", "format=format_name",
                     "-of", "csv=p=0", str(path)]).splitlines()
    info["container"] = cline[0].strip() if cline else ""

    d = capture([ffprobe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", str(path)])
    try:
        info["dur"] = float(d.splitlines()[0]) if d else 0.0
    except (ValueError, IndexError):
        pass
    if info["frames"] <= 0 and info["fps"] > 0 and info["dur"] > 0:
        info["frames"] = int(round(info["fps"] * info["dur"]))
    return info


def audio_codec(ffprobe: str, path: Path) -> str:
    """读音轨编码，没音轨就返回空串。"""
    text = capture([ffprobe, "-v", "error", "-select_streams", "a:0",
                    "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(path)])
    for line in text.splitlines():
        line = line.strip().lower()
        if line and line != "n/a":
            return line
    return ""


def already_done(ffprobe: str, dst: Path, target_fps: float, src_dur: float) -> bool:
    """输出文件已存在、帧率对得上、时长也对得上 → 视为已完成（可续跑）。"""
    if not dst.is_file() or dst.stat().st_size < 1024:
        return False
    i = probe(ffprobe, dst)
    if abs(i["fps"] - target_fps) > 0.6:
        return False
    if src_dur > 0 and abs(i["dur"] - src_dur) / src_dur > 0.05:
        return False
    return True


# --------------------------------------------------------------------- 单个文件
def convert_one(ffmpeg: str, ffprobe: str, rife: str, model_dir: Path,
                model: str, gpu: int, src: Path, dst: Path,
                target_fps: float, crf: int, kbps: int, keep_tmp: bool,
                threads: int = 0, keep_audio: bool = True, info: dict | None = None,
                cpu_used: int = 4, realtime_mode: bool = True,
                rife_j: str = "1:2:2", tmp_root: Path | None = None) -> tuple[bool, str]:
    t0 = time.time()
    # info 允许由调用方传进来复用 —— 主循环为了拿时长已经探过一次了，
    # 这里再探一次等于白起两个 ffprobe 子进程（批量跑时是分钟级的浪费）。
    if info is None:
        info = probe(ffprobe, src)
    if info["frames"] < 2:
        return False, f"读不出帧数（w={info['w']} h={info['h']} fps={info['fps']}）"
    src_fps = info["fps"] or 24.0
    out_frames = max(2, int(round(info["frames"] * target_fps / src_fps)))
    mult = target_fps / src_fps
    alpha = info["alpha"]
    dec = decoder_args(info["codec"])

    log(f"    {info['w']}x{info['h']}  {src_fps:.2f}fps → {target_fps:g}fps  "
        f"（{mult:.2f} 倍：{info['frames']} 帧 → {out_frames} 帧）")
    log(f"    源格式：{info['container'] or '?'} / {info['codec'] or '?'}"
        f"{' / 音轨 ' + info['audio'] if info['audio'] else ' / 无音轨'}"
        f"  →  {'带透明通道' if alpha else '不透明'}")
    if not alpha and info["codec"] in ("h264", "hevc", "mpeg4", "vp8", "msmpeg4"):
        log("    ℹ️ 源素材没有透明通道（这种编码本来就不带），输出也会是不透明的 webm")

    tmp = Path(tempfile.mkdtemp(prefix="dshpet_", dir=tmp_root))
    rgb_in, a_in, rgb_out, a_out = tmp / "rgb", tmp / "a", tmp / "rgb_i", tmp / "a_i"
    for d in (rgb_in, a_in, rgb_out, a_out):
        d.mkdir(parents=True, exist_ok=True)

    try:
        # ---- 1) 拆帧 ----
        # 注意 -nostdin：在循环里调 ffmpeg 而不关 stdin，会把后面待处理的路径当命令吃掉。
        #
        # 为什么要用 split 一次解码出两组，而不是调两次 ffmpeg：
        # 调两次 = 源视频解码两遍。带透明的素材本来就要拆两份，实测能省掉
        # 三分之一到一半的拆帧时间（241 帧素材约 0.9 秒 → 0.6 秒）。
        if alpha:
            rc = run([ffmpeg, "-nostdin", "-v", "error", "-y", *dec, "-i", str(src),
                      "-filter_complex",
                      "[0:v]split=2[c][al];"
                      "[c]format=rgb24[c2];"
                      "[al]alphaextract,format=gray[a2]",
                      "-map", "[c2]", str(rgb_in / "%05d.png"),
                      "-map", "[a2]", str(a_in / "%05d.png")], "拆帧（彩色+透明）")
            if rc != 0:
                # 极少数素材 split 滤镜链会出问题，退回老办法：分两次拆
                rc = run([ffmpeg, "-nostdin", "-v", "error", "-y", *dec, "-i", str(src),
                          "-vf", "format=rgb24", str(rgb_in / "%05d.png")], "拆彩色帧")
                if rc != 0:
                    return False, "拆彩色帧失败"
                rc = run([ffmpeg, "-nostdin", "-v", "error", "-y", *dec, "-i", str(src),
                          "-vf", "alphaextract,format=gray", str(a_in / "%05d.png")],
                         "拆透明通道")
                if rc != 0:
                    return False, "拆透明通道失败"
        else:
            rc = run([ffmpeg, "-nostdin", "-v", "error", "-y", *dec, "-i", str(src),
                      "-vf", "format=rgb24", str(rgb_in / "%05d.png")], "拆彩色帧")
            if rc != 0 and dec:
                # 显式指定的解码器这台 ffmpeg 可能没有（比如 libdav1d）→
                # 退一步让 ffmpeg 自己认，别因为一个可选参数把整件事废掉
                log("    ⚠️ 指定解码器失败，改用 ffmpeg 自动识别重试")
                rc = run([ffmpeg, "-nostdin", "-v", "error", "-y", "-i", str(src),
                          "-vf", "format=rgb24", str(rgb_in / "%05d.png")], "拆彩色帧")
            if rc != 0:
                return False, "拆彩色帧失败"

        n_rgb = len(list(rgb_in.glob("*.png")))
        n_a = len(list(a_in.glob("*.png"))) if alpha else 0
        if n_rgb < 2 or (alpha and n_a < 2):
            return False, f"拆帧数不对（彩色 {n_rgb}、透明 {n_a}）"

        # 别光听素材"声明"自己有透明通道，得看它实际有没有。
        # 有些格式（最典型是 GIF）会带个透明索引却从不使用，
        # 不查的话会白跑一整轮 alpha 插帧（实测多花 30% 时间）。
        if alpha and alpha_plane_is_empty(ffmpeg, a_in):
            log("    ℹ️ 这个素材虽然带 alpha 通道，但整段扫下来没有一处透明像素"
                " → 省掉一轮插帧")
            alpha = False

        # ---- 2) 插帧 ----
        custom_n = model.startswith(CUSTOM_FRAME_MODELS)
        if not custom_n and abs(mult - 2.0) > 0.01:
            # rife-anime 这类模型不支持自定义帧数，只能 2 倍
            return False, (f"模型 {model} 不支持自定义倍数（只能 2 倍），"
                           f"而你设的是 {mult:.2f} 倍 —— 请改用 rife-v4.6")
        jobs = [(rgb_in, rgb_out, "彩色")] + ([(a_in, a_out, "透明")] if alpha else [])
        for srcdir, dstdir, tag in jobs:
            cmd = [rife, "-i", str(srcdir), "-o", str(dstdir),
                   "-m", model, "-g", str(gpu)]
            # -j 控制 rife 自己的读/算/写线程数（默认 1:2:2）。
            # 它读写的那些 png 是 CPU 干的活：实测默认设置下 rife 会吃掉
            # 170% 的 CPU —— 调成 1:1:1 能降到 122%，代价是自己慢 30%。
            # 想让它尽量别抢 CPU 的机器可以填 1:1:1。
            if rife_j and re.fullmatch(r"\d+:\d+:\d+", str(rife_j).strip()):
                cmd += ["-j", str(rife_j).strip()]
            if custom_n:
                cmd += ["-n", str(out_frames)]
            rc = run(cmd, f"{tag}插帧")
            if rc != 0:
                return False, f"{tag}插帧失败"

        got = len(list(rgb_out.glob("*.png")))
        if got < 2:
            return False, f"插帧没有产出（{got} 帧）"

        # ---- 3) 合成 + 编码 ----
        dst.parent.mkdir(parents=True, exist_ok=True)
        if alpha:
            cmd = [ffmpeg, "-nostdin", "-v", "error", "-y",
                   "-framerate", f"{target_fps:g}", "-i", str(rgb_out / "%08d.png"),
                   "-framerate", f"{target_fps:g}", "-i", str(a_out / "%08d.png")]
        else:
            # 源素材本来就没有透明通道 → 输出也保持不透明（体积更小、兼容性更好）
            cmd = [ffmpeg, "-nostdin", "-v", "error", "-y",
                   "-framerate", f"{target_fps:g}", "-i", str(rgb_out / "%08d.png")]

        # 顺手把源素材的音轨原样搬过来（没有音轨的话 -map 的 ? 会让它自动跳过）。
        # 只处理画面、把声音悄悄丢掉，插普通视频的时候是要被骂的。
        n_in = 2 if alpha else 1          # 前面已经用掉的输入个数
        if keep_audio:
            cmd += ["-i", str(src)]
        if alpha:
            cmd += ["-filter_complex", "[0:v][1:v]alphamerge,format=yuva420p[v]",
                    "-map", "[v]"]
        else:
            cmd += ["-map", "0:v"]
        if keep_audio and info["audio"]:
            cmd += ["-map", f"{n_in}:a?"]
            if info["audio"] in WEBM_AUDIO_OK:
                # opus / vorbis 本来就是 webm 的原生音轨，原样搬、零损失
                cmd += ["-c:a", "copy"]
            else:
                # 别的（aac / mp3 / ac3…）webm 装不下，不改就会直接
                # "Could not write header" 整个失败。这里自动转成 opus。
                log(f"    ℹ️ 音轨是 {info['audio']}，webm 装不下 → 自动转成 opus")
                cmd += ["-c:a", "libopus", "-b:a", "128k"]
        if alpha:
            cmd += ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
                    "-auto-alt-ref", "0", "-row-mt", "1"]
        else:
            cmd += ["-c:v", "libvpx-vp9", "-pix_fmt", "yuv420p", "-row-mt", "1"]

        # VP9 的编码速度旋钮。默认的 cpu-used=0 是「最慢最好」，
        # 而编码这一步实测占总耗时一半以上，是整条流水线最大的开销。
        # 实测（241 帧素材，带透明）：
        #     cpu-used=0（ffmpeg 默认）13.09 秒  CPU 288%
        #     cpu-used=4                7.40 秒  CPU 254%
        #     cpu-used=4 + realtime     5.35 秒  CPU 222%   ← 现在的默认
        # 画质 SSIM 0.9964（肉眼无差别），体积大约 +14%。
        # 注意：cpu-used=5/6 反而比 4 慢（libvpx 配合 -row-mt 时不是单调的），
        # 4 是拐点，别以为越大越快。
        if cpu_used and int(cpu_used) > 0:
            cmd += ["-cpu-used", str(int(cpu_used))]
        if realtime_mode:
            # realtime 会关掉前瞻，解析器把速度排在质量前面。
            # 对「一次编码几万个文件里的一个小片段」这个场景，实测很划算。
            cmd += ["-deadline", "realtime"]

        if threads and int(threads) > 0:
            # 限制编码线程数 = 给 CPU 降温的最直接手段（笔记本/小机箱建议设 2~4）
            cmd += ["-threads", str(int(threads))]
        if kbps and int(kbps) > 0:
            cmd += ["-b:v", f"{int(kbps)}k"]
        else:
            cmd += ["-crf", str(int(crf)), "-b:v", "0"]
        cmd += [str(dst)]
        rc = run(cmd, "合成编码")
        if rc != 0:
            return False, "合成编码失败"

        cost = time.time() - t0
        size = dst.stat().st_size / 1024 / 1024
        kind = "带透明通道" if alpha else "不透明"
        return True, f"{got} 帧输出（{kind}），{size:.1f} MB，耗时 {cost:.0f} 秒"
    except Exception as exc:
        return False, f"出错：{exc}"
    finally:
        if not keep_tmp:
            shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------- 快速查询
def quick_query(args) -> int:
    """给图形界面用的「机器可读」查询：只往 stdout 打一行 JSON。

    为什么要有它：GUI 需要知道「这个文件夹里有哪些素材」「第一个素材多宽多高
    多少帧」—— 如果让 GUI 自己去调 ffprobe、自己解析，就等于把底层的探测
    逻辑复制了一份，两边早晚会不一致。所以这里开两个只读入口，
    GUI 直接复用底层的 probe()，一行判断逻辑都不重复。

    这两个入口不跑任何流水线、不改任何文件，也不做显卡预检（所以很快）。
    """
    cfg = load_config()
    try:
        _ff, ffprobe = find_ffmpeg(cfg)
    except RuntimeError:
        ffprobe = shutil.which("ffprobe") or ""

    if args.列素材:
        root = Path(args.列素材).expanduser()
        files: list[str] = []
        if root.is_dir():
            files = [str(p.relative_to(root)) for p in sorted(root.rglob("*"))
                     if p.is_file() and p.suffix.lower() in VIDEO_EXTS]
        elif root.is_file():
            files = [root.name]
        print(json.dumps({"目录": str(root), "文件": files,
                          "认得的后缀": list(VIDEO_EXTS)}, ensure_ascii=False))
        return 0

    p = Path(args.探素材).expanduser()
    info = probe(ffprobe, p) if (ffprobe and p.is_file()) else {}
    print(json.dumps({"文件": str(p), **info}, ensure_ascii=False))
    return 0


# --------------------------------------------------------------------- 主流程
def main() -> int:
    ap = argparse.ArgumentParser(description="DSH Pet 素材定制插帧工具", add_help=True)
    ap.add_argument("输入", nargs="?", default="", help="要处理的文件或目录（默认 input/）")
    ap.add_argument("--检查", action="store_true", help="只检查环境")
    ap.add_argument("--试跑", type=int, default=0, metavar="N", help="只处理前 N 个文件")
    ap.add_argument("--模型", default="", help="覆盖 config.json 里的插帧模型")
    # 下面三个主要给图形界面(gui.py)用，命令行用户一般不需要碰
    ap.add_argument("--帧率", type=float, default=0, metavar="N", help="覆盖 config.json 里的目标帧率")
    ap.add_argument("--输出", default="", metavar="目录", help="覆盖输出目录")
    ap.add_argument("--允许高风险", action="store_true", help="跳过安全倍数拦截")
    ap.add_argument("--跳过显卡检查", action="store_true", help="不做显卡预检（省 1~2 秒）")
    # 下面两个是给图形界面用的只读查询入口，输出一行 JSON；普通用户不用碰
    ap.add_argument("--列素材", default="", metavar="目录", help="列出目录里能处理的素材（JSON）")
    ap.add_argument("--探素材", default="", metavar="文件", help="探测单个素材的规格（JSON）")
    args = ap.parse_args()

    # 快速查询要在所有人类可读输出之前拦下来，保证 stdout 只有那一行 JSON
    if args.列素材 or args.探素材:
        try:
            return quick_query(args)
        except Exception as exc:
            print(json.dumps({"错误": str(exc)}, ensure_ascii=False))
            return 1

    hr(f"DSH Pet 素材定制插帧工具  {VERSION}")

    broke = fix_line_endings()
    if broke:
        log("⚠️ 发现这些文件的行尾是 Windows 格式（CRLF），已自动修成 LF：")
        for name in broke:
            log(f"     {name}")
        log("   （bash 只认 LF，不修的话 .sh / .command 会报 $'\\r' 错误）")

    cfg = load_config()
    if args.模型:
        cfg["插帧模型"] = args.模型
    if args.帧率:
        cfg["目标帧率"] = args.帧率
    if args.允许高风险:
        cfg["允许超过安全倍数"] = True
    target_fps = float(cfg.get("目标帧率") or 72)
    model = str(cfg.get("插帧模型") or "rife-v4.6")
    # 「使用第几块显卡」可以填 auto（默认）或者具体序号。
    # auto = 看 rife 报出来的设备列表，自己挑一块独显。
    gpu_raw = cfg.get("使用第几块显卡", "auto")
    gpu_auto = str(gpu_raw).strip().lower() in ("auto", "", "自动", "默认")
    try:
        gpu = 0 if gpu_auto else int(gpu_raw)
    except (TypeError, ValueError):
        log(f"⚠️ 配置里的「使用第几块显卡」写的是「{gpu_raw}」，只认 auto 或数字，先按 auto 处理。")
        gpu_auto, gpu = True, 0
    crf = int(cfg.get("视频质量CRF") or 32)
    kbps = int(cfg.get("视频码率kbps") or 0)
    cpu_used = int(cfg.get("编码速度cpu-used") if cfg.get("编码速度cpu-used") is not None else 4)
    realtime_mode = cfg.get("编码实时模式", True) is not False
    rife_j = str(cfg.get("rife读写线程") or "1:2:2").strip()

    # ---- 性能模式：探核 → 算线程预算 → 压低优先级 ----
    # 这一步不改任何"能不能用"的东西，只决定"跑多快、会不会碍着你"
    global _NICE_LEVEL, _IONICE_IDLE, _WIN_FLAGS
    mode = str(cfg.get("性能模式") or "auto")
    cpus, cpus_note = detect_cpus()
    plan = plan_performance(mode, cpus)
    if plan["threads"] is not None:
        threads = int(plan["threads"])
    if plan["rife_j"] is not None:
        rife_j = str(plan["rife_j"])
    if plan["nice"] > 0:
        if os.name == "nt":
            _WIN_FLAGS = int(getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0))
        else:
            _NICE_LEVEL = int(plan["nice"])
            _IONICE_IDLE = bool(plan["ionice"])
    tmp_root, tmp_note = pick_temp_dir(cfg)

    hr("调度")
    log(f"  电脑核数   : {cpus} 个逻辑核 {cpus_note}".rstrip())
    log(f"  性能模式   : {mode}")
    log(f"     └ {plan['why']}")
    log(f"  中间帧放哪 : {tmp_note}")
    threads = int(cfg.get("编码线程数") or 0)
    keep_audio = cfg.get("保留音频", True) is not False
    limit = args.试跑 or int(cfg.get("只处理前N个文件") or 0)
    keep_tmp = bool(cfg.get("处理完删除临时帧") is False)

    # ---- 环境 ----
    hr("环境检查")
    try:
        ffmpeg, ffprobe = find_ffmpeg(cfg)
        rife, model_dir = find_rife(cfg, model)
    except RuntimeError as exc:
        log("✗ " + str(exc))
        return 2
    log(f"  ffmpeg : {ffmpeg}")
    log(f"  rife   : {rife}")
    log(f"  模型目录: {model_dir}")
    if not model_ok(model_dir, model):
        have = sorted(p.name for p in model_dir.glob("rife*") if p.is_dir())
        log(f"  ✗ 找不到模型 {model}，这个目录里有：{', '.join(have) or '（没有）'}")
        return 2
    log(f"  插帧模型: {model}")

    # ---- 显卡预检：搞清楚到底跑在哪块卡上 ----
    # 这一步会真跑一次最小任务，多花 1~2 秒。值得：不然「以为在用独显，
    # 其实一直跑核显 / 软件渲染」这种坑，只能等用户自己想明白「怎么这么慢」。
    if args.跳过显卡检查:
        if gpu_auto:
            log(f"  （跳过了显卡检查 → 没法自动挑卡，先用第 {gpu} 块。")
            log("    想让它自动绑独显，就别加 --跳过显卡检查。）")
    else:
        devs, tail = check_gpus(rife, model)
        if not devs:
            if gpu_auto:
                log(f"  （问不出可用设备 → 没法自动挑卡，先用第 {gpu} 块。）")
            log(f"  ⚠️ 没能问出可用的显示设备（{tail or '没有输出'}）")
            log("     · 多半是没装带 Vulkan 的显卡驱动。")
            log("     · Windows：去显卡官网装驱动（NVIDIA / AMD / Intel 驱动都自带 Vulkan）。")
            log("     · Linux：装 vulkan 驱动（mesa-vulkan-drivers 或 nvidia-driver）。")
            log("     · 硬跑也能出结果，但会掉到 CPU 软件渲染 —— 一张图好几秒，")
            log("       十来秒的素材就是几十分钟起步。强烈建议先把驱动搞定。")
        else:
            why = "配置里指定的"
            if gpu_auto:
                auto_idx, why = pick_best_gpu(devs)
                if auto_idx is not None:
                    gpu = auto_idx
            log("  可用显示设备（rife 自己报的，不是你猜的）：")
            for i, name in devs:
                if is_soft(name):
                    kind = "软件渲染·极慢"
                elif is_integrated(name):
                    kind = "核显"
                else:
                    kind = "独显"
                mark = "  ← 用这块" if i == gpu else ""
                log(f"     [{i}] {name}  〔{kind}〕{mark}")
            picked = dict(devs).get(gpu)
            if picked is None:
                log(f"  ✗ 配置里选的是第 {gpu} 块卡，但一共只报了 {len(devs)} 块。")
                log(f"     把 config.json 的「使用第几块显卡」改成 auto，"
                    f"或者改成 0 ~ {len(devs) - 1} 之间的数字。")
                return 2
            if is_soft(picked):
                log(f"  ⚠️⚠️ 用的这块 [{gpu}] {picked} 是软件渲染，等于拿 CPU 硬算，")
                log("      会比显卡慢几十倍。先把显卡驱动装上，再挑一块真的卡。")
            elif is_integrated(picked):
                better = [i for i, n in devs if not is_soft(n) and not is_integrated(n)]
                if better:
                    log(f"  ⚠️ 用的这块 [{gpu}] {picked} 是核显，而这台机器有独显 "
                        f"[{better[0]}] {dict(devs)[better[0]]}。")
                    log("     把「使用第几块显卡」改成 auto 就会自动绑到独显上。")
                else:
                    log(f"  ℹ️ 用的是 [{gpu}] {picked}（核显）—— 能跑，就是比独显慢一截。")
            elif gpu_auto:
                log(f"  ✅ 自动绑到 [{gpu}] {picked} 上（{why}）。")
            else:
                log(f"  ✅ 用的是你指定的 [{gpu}] {picked}（独显），没问题。")

    if args.检查:
        hr("检查完毕")
        log("  ✅ 环境没问题，把素材丢进 input/ 就能开跑了。")
        return 0

    # ---- 输入 ----
    src_arg = args.输入.strip()
    src_root = Path(src_arg).resolve() if src_arg else (HERE / "input")
    if src_root.is_file():
        files = [src_root]
    elif src_root.is_dir():
        # 按后缀粗筛一遍（只为了别去拿 .txt / .jpg 当素材试），
        # 真正能不能处理交给后面的 ffprobe 判断 —— 所以名单列宽一点没坏处
        files = sorted(p for p in src_root.rglob("*")
                       if p.is_file() and p.suffix.lower() in VIDEO_EXTS)
    else:
        log(f"✗ 找不到输入：{src_root}")
        return 2
    if not files:
        log(f"✗ {src_root} 里没有能处理的素材。")
        log(f"   认这些后缀：{' '.join(VIDEO_EXTS)}")
        return 2
    if limit:
        files = files[:limit]

    # ---- 目标帧率与安全提示 ----
    first = probe(ffprobe, files[0])
    src_fps = first["fps"] or 24.0
    mult = target_fps / src_fps
    safe_max = float(cfg.get("安全倍数上限") or 3.0)
    hr("参数确认")
    log(f"  源素材帧率 : {src_fps:.2f} fps")
    log(f"  目标帧率   : {target_fps:g} fps")
    log(f"  插帧倍数   : {mult:.2f} 倍")
    log(f"  待处理     : {len(files)} 个文件")
    if mult > safe_max and not cfg.get("允许超过安全倍数"):
        log("")
        log("  ⚠️⚠️⚠️  帧率超过实测安全范围  ⚠️⚠️⚠️")
        log(f"     实测：24fps 源素材插到 72fps（3 倍）边缘还很干净；")
        log(f"          往 90 / 120fps 走，快速横向移动和大范围位移处")
        log(f"          会出现边缘重影 / 双层幻影，越快越明显。")
        log(f"     现在要插 {mult:.2f} 倍，已经超过安全上限 {safe_max:g} 倍。")
        log("     确认要试，就把 config.json 里的「允许超过安全倍数」改成 true。")
        return 3
    if mult > safe_max:
        log("  ⚠️ 已允许超过安全倍数，画质风险自负（边缘重影概率高）")

    # 输出目录：命令行 --输出 优先；其次「源目录同级 / <源目录名>_插帧输出」；
    # 都没给（走默认 input/）时才是工具包自带的 output/。
    #
    # 为什么不用通用的 "output"：那样处理两套素材会写进同一个目录、同名文件互相覆盖。
    # 为什么输出目录**不能放到源目录里面**：输出也是 .webm，下次再扫描会把自己的
    # 产物当成素材又插一遍，越滚越大。
    if args.输出.strip():
        out_root = Path(args.输出).resolve()
    elif src_arg:
        base = src_root if src_root.is_dir() else src_root.parent
        out_root = base.parent / (base.name + "_插帧输出")
    else:
        out_root = HERE / "output"

    log("")
    log(f"  输出目录   : {out_root}")

    # ---- 逐个处理 ----
    hr("开始处理")
    ok = fail = skip = 0
    t_start = time.time()
    try:
        for idx, src in enumerate(files, 1):
            rel = src.name if src_root.is_file() else str(src.relative_to(src_root))
            # 输出后缀强制成 .webm —— 透明只有 webm 能装，而 ffmpeg 是看
            # 后缀选封装格式的。不强制的话，mp4 喂进来会原样吐一个 mp4，
            # 里面塞着 VP9、透明还丢了，等于废文件。
            dst = out_root / Path(str(rel)).with_suffix(OUT_EXT)
            log(f"\n[{idx}/{len(files)}] {rel}")
            # 源素材只探一次，后面的「跳过判断」和「真转换」都复用这份结果。
            # 原来这两处各探一次，等于每个文件白起两个 ffprobe 子进程 ——
            # 106 个片段就是白扔 20 秒以上。
            sinfo = probe(ffprobe, src)
            if already_done(ffprobe, dst, target_fps, sinfo["dur"]):
                log("    已存在且规格一致，跳过（可续跑）")
                skip += 1
                continue
            # 自适应：目标帧率不比源高的话，插帧没有意义（反而会降帧）。
            # 素材里混进一个 60fps 的片段、而你在插到 48fps 时就会撞上。
            if sinfo["fps"] > 0 and target_fps <= sinfo["fps"] + 0.01:
                log(f"    跳过：源素材已经是 {sinfo['fps']:.2f}fps，"
                    f"不低于目标 {target_fps:g}fps（插了反而降帧）")
                skip += 1
                continue
            good, msg = convert_one(ffmpeg, ffprobe, rife, model_dir, model, gpu,
                                    src, dst, target_fps, crf, kbps, keep_tmp,
                                    threads, keep_audio, sinfo,
                                    cpu_used, realtime_mode, rife_j, tmp_root)
            if good:
                ok += 1
                log(f"    ✓ {msg}")
            else:
                fail += 1
                log(f"    ✗ {msg}")
            if idx >= 1:
                spent = time.time() - t_start
                done = ok + fail
                if done and idx < len(files):
                    eta = spent / done * (len(files) - idx)
                    log(f"    （已用 {spent/60:.1f} 分钟，预计还要 {eta/60:.1f} 分钟）")
    except KeyboardInterrupt:
        log("\n\n你按了 Ctrl+C。已经处理好的文件都在 output/ 里，重新运行会自动跳过。")

    hr("结果")
    log(f"  成功 {ok} 个，跳过 {skip} 个，失败 {fail} 个")
    log(f"  总耗时 {(time.time()-t_start)/60:.1f} 分钟")
    log(f"  输出在：{out_root}")
    if fail:
        log("  失败的可以再跑一次，已完成的会自动跳过。")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # 兜底：不要让窗口一闪而过
        print(f"\n出错了：{exc}")
        try:
            input("\n按回车键关闭…")
        except Exception:
            pass
        sys.exit(1)
