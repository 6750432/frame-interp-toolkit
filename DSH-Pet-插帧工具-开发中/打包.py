#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 ~/DSH-Pet-插帧工具包 打成一个可以直接发群的 zip。

为什么要写脚本而不是随手 zip 一下 —— 每次手搓都会忘掉某一步，
而这几步全是"忘了就发出去一个坏包"的性质：

  1. 清掉 __pycache__ / *.pyc（打进去又大又脏，而且 pyc 是不能跨版本用的）
  2. 清空 config.json 里本机的绝对路径（不清的话别人拿到的是
     ~/xxx 这种写死的路径，脚本会先报一句警告才回退到自动找）
  3. 保留 input/ output/ 的空目录条目（有些解压工具会跳过空目录，
     而 input/ 不存在的话脚本会直接报"找不到输入"）
  4. 用 Python 的 zipfile 而不是命令行的 zip —— 后者会把中文名存成
     #U4e00#U952e 这种转义形式（桌宠发行版那批素材名八成就是这么来的）

用法：python3 打包.py [版本号]     # 默认 0.6
"""

import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

HOME = Path.home()
SRC_TOOL = HOME / "DSH-Pet-插帧工具包"
OUT_DIR = HOME / "Desktop" / "78" / "About插帧"
# 注：自检（工具包里的 自检/ 子目录）从 v0.8 起就跟工具包捆在一起打，
# 不再单独出一个「快速自检包」的 zip 了 —— 用户少下一个东西。

# 打包时要清空的「本机专属」配置项
BLANK_KEYS = ("ffmpeg路径", "rife可执行文件路径", "rife模型所在目录",
              # 音频外挂的解释器路径 —— 指向本机 venv，别的机器上没有
              "音频修复_Python路径")

# 不打包的垃圾
JUNK_DIRS = {"__pycache__", ".git", ".idea", ".vscode", "自检输出", "._tmp_自检"}
JUNK_EXTS = {".pyc", ".pyo", ".bak", ".orig", ".rej", ".log"}
# 自检报告里带着本机的用户名和路径，绝不能打进包里发出去
JUNK_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini", "自检报告.txt"}


def blank_paths(stage: Path) -> None:
    """把 config.json 里本机的路径清空，其它键原样保留。"""
    p = stage / "config.json"
    cfg = json.loads(p.read_text(encoding="utf-8"))
    for k in BLANK_KEYS:
        if k in cfg:
            cfg[k] = ""
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")


def is_junk(p: Path) -> bool:
    return (p.name in JUNK_NAMES
            or p.suffix.lower() in JUNK_EXTS
            or any(part in JUNK_DIRS for part in p.parts))



def dir_entry(name: str) -> zipfile.ZipInfo:
    """目录条目必须自己写权限位。

    ZipInfo("xxx/") 的默认 external_attr 等于 0o600 ——
    用命令行 unzip 解出来就是 drw-------，**没有 x 位 = 目录进不去**，
    里面的脚本、素材统统读不到。文件管理器（Thunar / Ark / 7-Zip）
    会按自己的默认值来，所以本地试的时候完全看不出来。
    """
    zi = zipfile.ZipInfo(name)
    zi.external_attr = (0o40755 << 16) | 0x10   # drwxr-xr-x + DOS 目录位
    zi.compress_type = zipfile.ZIP_DEFLATED
    return zi

def make_zip(stage: Path, out: Path, top: str) -> list[str]:
    """打 zip。目录条目也写进去，免得空目录被解压工具吃掉。"""
    written = []
    dirs: set[str] = set()
    files: list[Path] = []
    for root, subdirs, names in os.walk(stage):
        subdirs[:] = [d for d in subdirs if d not in JUNK_DIRS]
        rp = Path(root).relative_to(stage)
        if str(rp) != ".":
            dirs.add(rp.as_posix())
        for n in sorted(names):
            f = Path(root) / n
            if is_junk(f):
                continue
            files.append(f)
            rel = f.relative_to(stage)
            for parent in rel.parents:
                if str(parent) != ".":
                    dirs.add(parent.as_posix())

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for d in sorted(dirs):
            zf.writestr(dir_entry(f"{top}/{d}/"), b"")
            written.append(f"{top}/{d}/")
        for f in sorted(files):
            arc = f"{top}/{f.relative_to(stage).as_posix()}"
            zf.write(f, arc)
            written.append(arc)
    return written


def check_zip(out: Path) -> None:
    """打完自查：中文标志位、路径有没有漏出去。"""
    print(f"  ── 自查 {out.name} ──")
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        bad = []
        for n in names:
            if n.endswith("/"):
                continue
            i = zf.getinfo(n)
            if any(ord(c) > 127 for c in n) and not (i.flag_bits & 0x800):
                bad.append(n)
        print(f"     条目 {len(names)} 个｜中文名缺 UTF-8 标志位：{len(bad)} 个"
              + (" ✔" if not bad else " ✘ " + str(bad)))
        # config.json 检查
        for n in names:
            if n.endswith("config.json"):
                cfg = json.loads(zf.read(n).decode("utf-8"))
                leaks = [k for k in BLANK_KEYS if cfg.get(k)]
                print(f"     config.json 本机路径泄漏：{leaks or '无'} ✔"
                      if not leaks else f"     config.json 里还有本机路径！{leaks} ✘")
                print(f"     使用第几块显卡 = {cfg.get('使用第几块显卡')!r}"
                      f"｜目标帧率 = {cfg.get('目标帧率')!r}")



# ──────────────────────────────────────────────────────────────
# 按系统分包（v0.8 起）
# 一个包里塞三套启动器（.bat / .sh / .command），用户根本分不清该点哪个，
# 点错了还以为工具坏了。所以每个包里只留它自己系统的。
SYSTEMS = [
    # (键, 文件名里的中缀, 允许的启动器后缀, 排在交付目录里的序号)
    ("windows", "Windows", {".bat"},     2),
    ("linux",   "Linux",   {".sh"},      3),
    ("macos",   "macOS",   {".command"}, 4),
]
LAUNCHER_STEMS = ("启动界面", "一键插帧", "一键自检")
LINUX_ONLY = ("装个桌面图标.sh",)


def first_read(system: str) -> str:
    """每个包顶部放一张只讲自己系统的「先读这个」。"""
    if system == "windows":
        return """精简版 · 先读这个（Windows）
════════════════════════════════════════════════════
【先确认你下对包了没】
  开箱即用版：ffmpeg / rife / 模型全塞好了，80 多 MB，解压就能跑。
  这个精简版：只有工具本体（几百 KB），你**得自己已经装好**
              ffmpeg 和 rife-ncnn-vulkan** 才能跑。
  → 不确定自己有没有，就别用这个包，去下「开箱即用版」。

【三步】
  第 1 步   双击「启动界面.bat」
  第 2 步   选素材文件夹 → 填目标帧率（默认 72）→ 点「开始插帧」
  第 3 步   跑完去 output/ 里拿结果

【这个包里只有 Windows 的东西】
  启动界面.bat ／ 一键插帧.bat ／ 自检\一键自检.bat
  （.sh 是 Linux 的、.command 是 macOS 的 —— 这个包里**没有**，免得点错）

【唯一门槛：电脑上要有 Python 3.8 以上】
  装的时候记得勾「Add Python to PATH」，不勾后面全废。
  双击没反应 / 黑框一闪就没了 → 看「打不开看这里.txt」。

【心里没底就先自检】
  双击 自检\一键自检.bat —— 它会拿自带素材真跑一遍，生成
  「自检报告.txt」，缺什么、错在哪一眼就看得出来。
"""

    if system == "linux":
        return """精简版 · 先读这个（Linux）
════════════════════════════════════════════════════
【⚠️ Linux 上第一件事：别双击 .sh】

  Linux 的文件管理器默认把 .sh 当**文本文件**打开 ——
  你双击「启动界面.sh」，多半只弹出一屏代码，程序一点动静都没有。
  这不是工具坏了，是文件管理器的默认策略（Thunar 连问都不问）。

  ★ 正确姿势：在这个文件夹**空白处右键 → 「在这里打开终端」**，
    然后跑这一行：

        bash 启动界面.sh

    不想用右键菜单也行，直接开终端把下面整行粘进去（路径按实际改）：

        bash ~/下载/DSH-Pet-插帧工具包-Linux/启动界面.sh

  ★ 想以后能双击：跑一次

        bash 装个桌面图标.sh

    它会在你桌面上放一个图标，以后双击那个就行 ——
    不受上面那条策略影响，也不用改任何系统设置。

【这个包里只有 Linux 的东西】
  启动界面.sh ／ 一键插帧.sh ／ 自检/一键自检.sh ／ 装个桌面图标.sh
  （.bat 是 Windows 的、.command 是 macOS 的 —— 这个包里**没有**，免得点错）

【要准备什么】
  Python 3.8 以上（Debian/Ubuntu/Mint 的软件源里叫 python3），外加你自己
  装好的 ffmpeg 和 rife-ncnn-vulkan。

【心里没底就先自检】
  开终端跑   bash 自检/一键自检.sh
  它会拿自带素材真跑一遍，生成「自检报告.txt」，缺什么一眼就看出来。

【其他问题】
  看同目录的「打不开看这里.txt」。
"""

    return """精简版 · 先读这个（macOS）
════════════════════════════════════════════════════
⚠️ 先说清楚：**macOS 上这个工具一次都没在真机上跑过**
   （作者手里没有 Mac）。能不能跑通、哪里会翻车，都是照文档写的，
   没实测过。愿意帮忙试的话，把终端输出发出来就行。

【三步】
  第 1 步   双击「启动界面.command」
            没反应 / 提示「来自身份不明的开发者」：
              右键（Control + 单击）→「打开」→ 再点一次「打开」；
              或者先在终端里跑一遍：
                  chmod +x 启动界面.command 一键插帧.command 自检/一键自检.command
  第 2 步   选素材文件夹 → 填目标帧率（默认 72）→ 点「开始插帧」
  第 3 步   跑完去 output/ 里拿结果

【这个包里只有 macOS 的东西】
  启动界面.command ／ 一键插帧.command ／ 自检/一键自检.command
  （.bat 是 Windows 的、.sh 是 Linux 的 —— 这个包里**没有**，免得点错）

【要准备什么】
  Python 3.8 以上（用 Homebrew 装个 python），外加你自己装好的
  ffmpeg 和 rife-ncnn-vulkan。

【心里没底就先自检】
  双击 自检/一键自检.command，或者终端里跑   python3 自检/自检.py

【其他问题】
  看同目录的「打不开看这里.txt」。
"""


def trim_to_system(stage: Path, system: str, suffixes: set[str]) -> list[str]:
    """把 stage 裁成「只属于一个系统」：删掉别的系统的启动器。"""
    removed: list[str] = []
    for p in sorted(stage.rglob("*")):
        if not p.is_file():
            continue
        drop = False
        if p.stem in LAUNCHER_STEMS and p.suffix in (".bat", ".sh", ".command"):
            drop = p.suffix not in suffixes
        elif p.name in LINUX_ONLY:
            drop = system != "linux"
        if drop:
            removed.append(p.relative_to(stage).as_posix())
            p.unlink()
    return removed


def main() -> int:
    ver = sys.argv[1] if len(sys.argv) > 1 else "0.6"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not SRC_TOOL.is_dir():
        print(f"  ✘ 源目录不存在：{SRC_TOOL}")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="dshpet_pack_"))
    outs: list[Path] = []
    try:
        for key, mid, suffixes, idx in SYSTEMS:
            top = f"DSH-Pet-插帧工具包-{mid}"
            stage = tmp / top
            shutil.copytree(SRC_TOOL, stage, ignore=shutil.ignore_patterns(*JUNK_DIRS))
            blank_paths(stage)
            for name in ("input", "output"):
                d = stage / name
                d.mkdir(parents=True, exist_ok=True)
                for child in list(d.iterdir()):
                    shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink()
            removed = trim_to_system(stage, key, suffixes)
            (stage / "0-先读这个（第一次用）.txt").write_text(
                "\ufeff" + first_read(key), encoding="utf-8")
            out = OUT_DIR / f"{idx}-精简版-{mid}-v{ver}.zip"
            wrote = make_zip(stage, out, top)
            outs.append(out)
            print(f"\n  ✔ {out.name}   {out.stat().st_size / 1024:.0f} KB   {len(wrote)} 条目")
            print(f"     裁掉的别的系统的启动器：{removed or '无'}")
            check_zip(out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n  ── 指纹 ──")
    import hashlib
    for out in outs:
        print(f"     {hashlib.sha256(out.read_bytes()).hexdigest()}  {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
