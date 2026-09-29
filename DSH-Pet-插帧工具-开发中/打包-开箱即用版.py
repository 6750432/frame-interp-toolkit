#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打「开箱即用版」—— 把 ffmpeg / rife 裁到最小后内置进去。

和 打包.py 的区别：
  打包.py        只打本项目自己写的代码（几十 KB），依赖让用户自己装
  本脚本         把必要的外部程序也裁进来（约 86 MB），用户解压就跑

依赖两个已经解压好的目录（第一次要自己下，之后复用）：
  ~/bundle-build/ffmpeg-win/   ← 从 ffmpeg essentials 包里抽出来的
                                  只有 ffmpeg.exe / ffprobe.exe / LICENSE
  ~/bundle-build/rife-win/     ← 从 rife windows 包里抽出来的
                                  只有 rife-ncnn-vulkan.exe / vcomp140.dll
                                  LICENSE / README.md / rife-v4.6/

怎么来的（记下来免得以后忘）：
  ffmpeg  https://gh-proxy.com/https://github.com/GyanD/codexffmpeg/releases/
          download/9.0.2/ffmpeg-9.0.2-essentials_build.zip        109 MB
          → 只要 bin/ffmpeg.exe + bin/ffprobe.exe（各约 100 MB）
  rife    https://gh-proxy.com/https://github.com/nihui/rife-ncnn-vulkan/
          releases/download/20221029/rife-ncnn-vulkan-20221029-windows.zip   411 MB
          → 只要 rife-ncnn-vulkan.exe + vcomp140.dll + rife-v4.6/（共 17 MB）
            其余 394 MB 全是历史模型，砍掉

⚠️ vcomp140.dll 千万别漏 —— 那是 MSVC 的 OpenMP 运行库，
   缺了 rife 在没装 VC++ 运行库的机器上直接起不来。

用法：python3 打包-开箱即用版.py
"""

import hashlib
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path

HOME = Path.home()
BUILD = HOME / "bundle-build"
SRC = HOME / "DSH-Pet-插帧工具包"
STAGE = BUILD / "DSH-Pet-插帧工具-开箱即用版-Windows"
OUT = HOME / "Desktop" / "78" / "About插帧" / "1-开箱即用版-Windows.zip"
TOP = "DSH-Pet-插帧工具-开箱即用版-Windows"

# 从工具包里带过去的文件
TOOLKIT_FILES = ["插帧.py", "gui.py", "config.json", "README.md",
                 "说明书-保姆级教程.txt", "版本更新记录.txt",
                 "启动界面.bat", "一键插帧.bat",
                 # 音频那一侧（可插拔）：少了这两个，GUI 一点「音频」模式就报错
                 "audio_fix.py", "gui_audio.py"]
# 「音频修复_Python路径」指向本机 venv，必须清空 —— 别的机器上没有这个路径
BLANK_KEYS = ("ffmpeg路径", "rife可执行文件路径", "rife模型所在目录",
              "音频修复_Python路径")

FIRST_READ = """开箱即用版 · 先读这个（第一次用就看这一页）
════════════════════════════════════════════════════

【这个版本跟精简版的区别】
  精简版：要你自己去下 ffmpeg 和 rife，放对文件夹才能跑。
  这个版：程序已经全在里面了，不用下、不用装、不用配，解压出来双击就跑。

【三步】
  第 1 步   双击「启动界面.bat」
  第 2 步   选素材文件夹 → 填目标帧率（默认 72）→ 点「▶ 开始插帧」
  第 3 步   跑完去 output/ 里拿结果

  想用命令行也行：素材丢进 input/，双击「一键插帧.bat」。

【界面上一共有三种模式（左上角切换）】
  插帧   最常用：给桌宠动图补帧，让动作变顺滑。默认就是这个，啥都不用改。
  音频   只修声音、不碰画面 —— 治「听着发闷」「忽大忽小」「尾巴一大段静音」。
         纯音频文件（mp3 / wav / flac / opus…）也能直接拖进来。
  视音   一次搞定：画面插帧 + 声音修复，再把修好的声音**封回视频**一起给你。
  （第一次用就打「插帧」，熟了再试另外两个，互不影响。）

【建议先花十几秒体检一下】
  双击 自检/一键自检.bat —— 它会拿自带的测试素材**真跑一遍**，
  跑完生成「自检报告.txt」。报告说「全流程通了」你再开工，
  省得插到一半才发现哪里没配好。报告看不懂就直接反馈给作者。

【唯一的门槛：电脑上要有 Python 3.8 以上】
  这是唯一需要你自己装的东西。没有的话双击脚本会提示你去哪下。
  装的时候记得勾上「Add Python to PATH」，不勾后面全废。
  https://www.python.org/downloads/

  为什么不做成不用 Python 的单文件 exe：那要在 Windows 上打包，
  这边是 Linux 环境，跨不过去。将来可以补一个。

【里面装了什么（你不用管，只是让你放心）】
  ffmpeg.exe / ffprobe.exe ................. 拆帧、合帧、编码
  rife-ncnn-vulkan.exe + rife-v4.6/ ........ 插帧本体（跑显卡）
  vcomp140.dll ............................. rife 需要的运行库
  插帧.py / gui.py / config.json ........... 主程序和配置
  audio_fix.py / gui_audio.py / audio_plugin/   音频快修（只修声音那一套）
  docs/ .................................... 界面截图和配图
  说明书-保姆级教程.txt .................... 出问题先翻这个
  版本更新记录.txt ......................... 每版改了什么
  自检/ .................................... 一键自检（建议先跑一次）

【第一次跑注意两件事】
  · 开头会多花 1~2 秒 —— 脚本在问显卡（它会把机器上所有能算的显示
    设备列出来，然后自动挑一块独显绑上）。看到「自动绑到 [0] XXX」就对了。
  · 插帧只读你给的源目录、只写 output/，绝对不碰你的原素材。
    但还是建议自己备份一份。

【跑不动 / 报错怎么办】
  先翻「说明书-保姆级教程.txt」里那张「出问题了？先照这张表对号入座」，
  九成的坑都在上面。还不行就把黑框里的原文反馈给作者。
"""


def build_stage() -> None:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)

    for f in TOOLKIT_FILES:
        shutil.copy2(SRC / f, STAGE / f)
    shutil.copytree(SRC / "docs", STAGE / "docs")
    # 音频外挂目录（模型插件）：一起带过去，缺了也不致命 ——
    # 主程序会自动降级成自带 DSP，绝不会因为外挂不在就罢工
    shutil.copytree(SRC / "audio_plugin", STAGE / "audio_plugin",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # 「自检」子目录也一起带过去 —— 和精简版保持一致：
    # 解压一个包，先体检再干活
    # 只留 Windows 的那份自检启动器（.sh/.command 是 Linux/macOS 的）
    shutil.copytree(SRC / "自检", STAGE / "自检",
                    ignore=shutil.ignore_patterns("自检输出", "._tmp_自检",
                                                  "自检报告.txt",
                                                  "一键自检.sh", "一键自检.command"))

    # 路径清空，靠自动查找（.bat 会先 cd 到脚本目录，
    # Windows 上 shutil.which 会先查当前目录，所以能找到 .\ffmpeg.exe）
    p = STAGE / "config.json"
    cfg = json.loads(p.read_text(encoding="utf-8"))
    for k in BLANK_KEYS:
        cfg[k] = ""
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")

    # 内置程序
    pairs = [
        (BUILD / "ffmpeg-win" / "ffmpeg.exe", "ffmpeg.exe"),
        (BUILD / "ffmpeg-win" / "ffprobe.exe", "ffprobe.exe"),
        (BUILD / "ffmpeg-win" / "LICENSE", "程序许可证-ffmpeg.txt"),
        (BUILD / "rife-win" / "rife-ncnn-vulkan.exe", "rife-ncnn-vulkan.exe"),
        (BUILD / "rife-win" / "vcomp140.dll", "vcomp140.dll"),
        (BUILD / "rife-win" / "LICENSE", "程序许可证-rife.txt"),
    ]
    for src, dst in pairs:
        if not src.exists():
            raise SystemExit(f"✘ 缺文件：{src}\n  先照脚本头部的说明把两个发布包下下来抽好。")
        shutil.copy2(src, STAGE / dst)
    shutil.copytree(BUILD / "rife-win" / "rife-v4.6", STAGE / "rife-v4.6")

    # 空目录 + 指路牌
    (STAGE / "input").mkdir(exist_ok=True)
    (STAGE / "output").mkdir(exist_ok=True)
    (STAGE / "input" / "把要插帧的-webm-放这里.txt").write_text(
        "# 把要插帧的 .webm 素材丢进这个文件夹，然后双击上一层的「一键插帧.bat」。\n"
        "# 结果会出现在 output/ 里。\n"
        "# （这个说明文件本身不用管，脚本只认 .webm）\n", encoding="utf-8")

    with open(STAGE / "0-先读这个（第一次用）.txt", "wb") as f:
        f.write(b"\xef\xbb\xbf")
        f.write(FIRST_READ.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8"))



def dir_entry(name: str) -> zipfile.ZipInfo:
    """目录条目要自己写权限位 —— 默认的 0o600 解出来是 drw-------，
    在 Linux / macOS 上等于「这个目录进不去」。详见 打包.py 里的注释。"""
    zi = zipfile.ZipInfo(name)
    zi.external_attr = (0o40755 << 16) | 0x10
    zi.compress_type = zipfile.ZIP_DEFLATED
    return zi

def make_zip() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    dirs = set()
    files = []
    for root, sub, names in os.walk(STAGE):
        rp = Path(root).relative_to(STAGE)
        if str(rp) != ".":
            dirs.add(rp.as_posix())
        for name in sorted(names):
            files.append(Path(root) / name)
            rel = (Path(root) / name).relative_to(STAGE)
            for parent in rel.parents:
                if str(parent) != ".":
                    dirs.add(parent.as_posix())
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for d in sorted(dirs):
            z.writestr(dir_entry(f"{TOP}/{d}/"), b"")
        for f in sorted(files):
            z.write(f, f"{TOP}/{f.relative_to(STAGE).as_posix()}")
            n += 1
    return n


def verify() -> None:
    size = OUT.stat().st_size
    with zipfile.ZipFile(OUT) as z:
        names = z.namelist()
        bad = [x for x in names if not x.endswith('/')
               and any(ord(c) > 127 for c in x) and not (z.getinfo(x).flag_bits & 0x800)]
        tops = {x.split('/')[0] for x in names}
        need = ["ffmpeg.exe", "ffprobe.exe", "rife-ncnn-vulkan.exe", "vcomp140.dll",
                "rife-v4.6/flownet.bin", "rife-v4.6/flownet.param",
                "插帧.py", "gui.py", "config.json", "启动界面.bat", "一键插帧.bat",
                "自检/自检.py", "自检/一键自检.bat", "自检/说明.txt",
                "自检/测试素材/左转奔跑.webm"]
        missing = [f"{TOP}/{x}" for x in need if f"{TOP}/{x}" not in names]
        cfg = json.loads(z.read(f"{TOP}/config.json").decode("utf-8"))
        leaks = [k for k in BLANK_KEYS if cfg.get(k)]
        print(f"\n  ── 自查 ──")
        print(f"     zip {size/1024/1024:.1f} MB｜条目 {len(names)}｜单顶层文件夹 {'✔' if tops=={TOP} else '✘ '+str(tops)}")
        print(f"     中文名缺 UTF-8 标志位：{len(bad)} 个 {'✔' if not bad else '✘'}")
        print(f"     缺文件：{missing or '无'} {'✔' if not missing else '✘'}")
        print(f"     config 本机路径泄漏：{leaks or '无'} {'✔' if not leaks else '✘'}")
        print(f"     显卡设置 = {cfg.get('使用第几块显卡')!r}｜目标帧率 = {cfg.get('目标帧率')!r}")
    print(f"\n  指纹 {hashlib.sha256(OUT.read_bytes()).hexdigest()}")
    print(f"  位置 {OUT}")


def main() -> int:
    print("  组装开箱即用版…")
    build_stage()
    unpacked = sum(os.path.getsize(os.path.join(r, f))
                   for r, _, fs in os.walk(STAGE) for f in fs)
    n = make_zip()
    print(f"  打完：{n} 个文件｜解压后 {unpacked/1024/1024:.1f} MB")
    verify()
    return 0


if __name__ == "__main__":
    sys.exit(main())
