#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DSH Pet 插帧工具 · 快速自检
============================
**这一个文件就是全部**，不依赖别的脚本，也不依赖任何第三方 Python 包。

它干这几件事：
  1. 把系统和环境信息记下来（操作系统、Python 版本、各种编码 —— 排乱码要用）
  2. 找 ffmpeg / ffprobe / rife-ncnn-vulkan，报告找没找到
  3. 找不齐就告诉你缺哪个、去哪下（不会报错崩掉）
  4. **找齐了就跑一次真转换**（拿自带的测试素材，48fps 最快最小），
     再校验输出规格对不对
  5. 把上面所有东西写进一个「自检报告.txt」，发给作者就能定位问题

用法：双击「一键自检」（.bat / .sh / .command），或者
      python 自检.py
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPORT = HERE / "自检报告.txt"

# 这个脚本有两种摆法：
#   ① 单独发出去 —— 解压出来 HERE 就是根目录（老的自检包就是这么发的）
#   ② 躺在工具包的「自检/」子目录里 —— v0.8 起合并进来，默认就是这种
# 所以「上一级」只有在确认它真的是工具包目录时才纳入搜索：
# 不然万一解压到 Downloads 那种大目录，递归找 ffmpeg 会翻很久。
PARENT = HERE.parent
IN_TOOLKIT = (PARENT / "插帧.py").is_file()
ROOTS = [HERE] + ([PARENT] if IN_TOOLKIT else [])


def config_hints() -> dict:
    """工具包的 config.json 里如果已经填过路径，优先采信它们。"""
    if not IN_TOOLKIT:
        return {}
    try:
        cfg = json.loads((PARENT / "config.json").read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict = {}
    for key, slot in (("ffmpeg路径", "ffmpeg"),
                      ("rife可执行文件路径", "rife"),
                      ("rife模型所在目录", "model_dir")):
        val = str(cfg.get(key) or "").strip()
        if val and Path(val).exists():
            out[slot] = val
    return out


HINTS = config_hints()

FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/"
RIFE_URL = "https://github.com/nihui/rife-ncnn-vulkan/releases"
RIFE_MIRROR = "https://gh-proxy.com/https://github.com/nihui/rife-ncnn-vulkan/releases"

LINES: list[str] = []


def say(text: str = "") -> None:
    """同时打印到屏幕和报告里。"""
    LINES.append(text)
    try:
        print(text, flush=True)
    except Exception:
        pass


def hr(title: str = "") -> None:
    if title:
        say("")
        say("=" * 64)
        say(f"  {title}")
        say("=" * 64)
    else:
        say("-" * 64)


def run(cmd: list[str], timeout: int = 900) -> tuple[int, str]:
    """跑外部命令。stdin 一律给空 —— 不然 ffmpeg 会把输入流抢走。"""
    try:
        p = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=timeout)
        return p.returncode, p.stdout.decode("utf-8", "replace")
    except FileNotFoundError:
        return -1, f"找不到程序：{cmd[0]}"
    except subprocess.TimeoutExpired:
        return -2, "命令超时"
    except Exception as exc:
        return -3, f"执行出错：{exc}"


def shell_out(cmd: str) -> str:
    try:
        p = subprocess.run(cmd, shell=True, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=15)
        return p.stdout.decode("utf-8", "replace").strip()
    except Exception as exc:
        return f"(取不到：{exc})"


# --------------------------------------------------------------- 1 系统信息
def section_system() -> None:
    hr("一、系统与环境信息")
    say(f"  报告生成时间 : {time.strftime('%Y-%m-%d %H:%M:%S')}")
    say(f"  操作系统     : {platform.platform()}")
    say(f"  sys.platform : {sys.platform}   os.name = {os.name}")
    if os.name == "nt":
        say(f"  Windows 版本 : {platform.win32_ver()}")
    say(f"  CPU 架构     : {platform.machine()}")
    say("")
    say(f"  Python 版本  : {sys.version.split()[0]}  ({sys.version.split('(')[0].strip()})")
    say(f"  Python 路径  : {sys.executable}")
    say(f"  是否打包环境 : {bool(getattr(sys, 'frozen', False))}")
    say("")
    say("  —— 编码相关（排「中文乱码」问题全靠这几行）——")
    import locale
    say(f"  系统首选编码 : {locale.getpreferredencoding(False)}")
    say(f"  stdout 编码  : {getattr(sys.stdout, 'encoding', '?')}")
    say(f"  stderr 编码  : {getattr(sys.stderr, 'encoding', '?')}")
    say(f"  文件系统编码 : {sys.getfilesystemencoding()}")
    say(f"  LANG         : {os.environ.get('LANG', '(没设)')}")
    say(f"  PYTHONIOENCODING : {os.environ.get('PYTHONIOENCODING', '(没设)')}")
    say(f"  PYTHONUTF8   : {os.environ.get('PYTHONUTF8', '(没设)')}")
    if os.name == "nt":
        say(f"  终端代码页   : {shell_out('chcp')}")
    say("")
    say(f"  当前工作目录 : {os.getcwd()}")
    say(f"  脚本所在目录 : {HERE}")
    say(f"  临时目录     : {__import__('tempfile').gettempdir()}")
    # 中文能不能正常写文件（Windows 上最容易在这炸）
    try:
        probe = HERE / "._chinese_test_中文测试.txt"
        probe.write_text("中文写入测试", encoding="utf-8")
        back = probe.read_text(encoding="utf-8")
        probe.unlink()
        say(f"  中文写文件   : {'正常' if back == '中文写入测试' else '读回来不对！'}")
    except Exception as exc:
        say(f"  中文写文件   : 失败 —— {exc}")
    # 目录里有没有非 ASCII 文件名（路径带中文有时会出问题）
    say(f"  本目录路径含中文 : {'是' if any(ord(c) > 127 for c in str(HERE)) else '否'}")


# --------------------------------------------------------------- 2 找程序
def find_exe(names: list[str], hint: str | None = None) -> str | None:
    # 0. 工具包 config.json 里填过的绝对路径最可信
    if hint and Path(hint).is_file():
        return hint
    # 1. 系统 PATH
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    # 2. 本目录 / 上一级（工具包根目录）不递归地找一层
    for root in ROOTS:
        for n in names:
            cand = root / n
            if cand.is_file():
                return str(cand)
    # 3. 再往深处递归 —— 只在上面定好的搜索根里翻
    for root in ROOTS:
        for n in names:
            try:
                for p in sorted(root.glob("**/" + n)):
                    if p.is_file():
                        return str(p)
            except OSError:
                continue
    return None


def find_model_dir(exe: str | None, model: str) -> str | None:
    if HINTS.get("model_dir") and (Path(HINTS["model_dir"]) / model).is_dir():
        return HINTS["model_dir"]
    cands: list[Path] = []
    if exe:
        parent = Path(exe).parent
        cands += [parent, parent.parent, parent.parent / "Resources",
                  parent.parent.parent / "Resources"]
    cands += ROOTS
    for c in cands:
        try:
            if (c / model).is_dir():
                return str(c)
        except OSError:
            continue
    bases = ([Path(exe).parent] if exe else []) + ROOTS
    for base in bases:
        try:
            for p in base.glob("**/" + model):
                if p.is_dir():
                    return str(p.parent)
        except OSError:
            continue
    return None


def section_tools() -> dict:
    hr("二、外部程序检查")
    info: dict = {}
    names = ["ffmpeg.exe", "ffmpeg"] if os.name == "nt" else ["ffmpeg"]
    info["ffmpeg"] = find_exe(names, HINTS.get("ffmpeg"))
    pnames = ["ffprobe.exe", "ffprobe"] if os.name == "nt" else ["ffprobe"]
    info["ffprobe"] = find_exe(pnames)
    if not info["ffprobe"] and info["ffmpeg"]:
        # ffprobe 一般就跟 ffmpeg 挨着，顺手看一眼
        sib = Path(info["ffmpeg"]).parent / pnames[0]
        if sib.is_file():
            info["ffprobe"] = str(sib)
    rnames = ["rife-ncnn-vulkan.exe", "rife-ncnn-vulkan"] if os.name == "nt" \
        else ["rife-ncnn-vulkan"]
    info["rife"] = find_exe(rnames, HINTS.get("rife"))
    info["model_dir"] = find_model_dir(info["rife"], "rife-v4.6")

    for key, label, url in (("ffmpeg", "ffmpeg", FFMPEG_URL),
                            ("ffprobe", "ffprobe", FFMPEG_URL),
                            ("rife", "rife-ncnn-vulkan", RIFE_URL)):
        val = info[key]
        if val:
            say(f"  {label:18s} ✅ 找到：{val}")
        else:
            say(f"  {label:18s} ❌ 没找到")
            say(f"     去哪下：{url}")
            if key == "rife":
                say(f"     国内打不开就用中转：{RIFE_MIRROR}")
            if key in ("ffmpeg", "ffprobe"):
                say(f"     下完把 bin 里的 ffmpeg / ffprobe 放到工具包根目录"
                    f"（也就是本文件的上一级）")
    if info["model_dir"]:
        say(f"  {'模型 rife-v4.6':18s} ✅ 在：{info['model_dir']}")
    else:
        say(f"  {'模型 rife-v4.6':18s} ❌ 没找到（rife 的压缩包里自带，整个文件夹放进来就行）")

    if info["ffmpeg"]:
        rc, out = run([info["ffmpeg"], "-version"], timeout=30)
        first = out.splitlines()[0] if out else "(没输出)"
        say(f"  ffmpeg 自报版本 : {first}")
    return info


# --------------------------------------------------------------- 3 素材
def section_assets() -> list[Path]:
    hr("三、测试素材")
    # 顺序有讲究：自带的测试素材永远排第一 —— 别去抓用户 input/ 里的
    # 真素材来跑测试，那玩意儿可能几十秒长，一跑就是半天。
    for d in [HERE / "测试素材", HERE / "input", HERE] + \
             ([PARENT / "测试素材"] if IN_TOOLKIT else []):
        if d.is_dir():
            files = sorted(p for p in d.rglob("*.webm"))
            if files:
                say(f"  在 {d.name}/ 里找到 {len(files)} 个 .webm：")
                for f in files[:6]:
                    size = f.stat().st_size / 1024
                    say(f"      {f.name}  ({size:.0f} KB)")
                return files
    say("  ❌ 没找到任何 .webm 素材")
    return []


# --------------------------------------------------------------- 4 真跑
def probe(ffprobe: str, path: Path) -> dict:
    """先按 VP9 解码读取（这样才看得见 alpha），读不到再让 ffmpeg 自动判断。"""
    def ask(extra):
        rc, out = run([ffprobe, "-v", "error", *extra, "-select_streams", "v:0",
                       "-show_entries", "stream=width,height,r_frame_rate,pix_fmt,codec_name",
                       "-of", "default=nw=1", str(path)], timeout=60)
        return out
    out = ask(["-c:v", "libvpx-vp9"])
    if "width=" not in out:
        out = ask([])
    d: dict = {}
    for line in out.splitlines():
        k, _, v = line.partition("=")
        d[k.strip()] = v.strip()
    rc2, out2 = run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                     "-of", "csv=p=0", str(path)], timeout=60)
    d["duration"] = out2.strip()
    return d


def section_convert(tools: dict, assets: list[Path]) -> None:
    hr("四、实际转换测试")
    need = [tools.get("ffmpeg"), tools.get("ffprobe"), tools.get("rife"), tools.get("model_dir")]
    if not all(need) or not assets:
        say("  ⏭ 跳过 —— 上面还有东西没准备好（先把缺的补上，再跑一次这个脚本）")
        return

    ffmpeg, ffprobe, rife, model_dir = need[0], need[1], need[2], need[3]
    src = assets[0]
    say(f"  拿这个片段试：{src.name}")
    info = probe(ffprobe, src)
    say(f"  源素材：{info.get('width')}x{info.get('height')} "
        f"{info.get('r_frame_rate')} {info.get('pix_fmt')} "
        f"时长 {info.get('duration')}s")
    if info.get("pix_fmt") and "yuva" not in info["pix_fmt"]:
        say(f"  ⚠️ 这个素材不带 alpha（{info.get('pix_fmt')}）—— 还能测流程，但透明通道测不到")

    pix = str(info.get("pix_fmt") or "")
    has_alpha = any(pix.startswith(p) for p in
                    ("yuva", "rgba", "bgra", "argb", "abgr", "ya8", "ya16", "gbrap"))
    dec = {"vp9": ["-c:v", "libvpx-vp9"], "vp8": ["-c:v", "libvpx"]}.get(
        str(info.get("codec_name") or "").lower(), [])
    say(f"  编码 {info.get('codec_name')} / 像素格式 {pix} / "
        f"{'带透明通道' if has_alpha else '不透明'}")

    outdir = HERE / "自检输出"
    outdir.mkdir(exist_ok=True)
    dst = outdir / (src.stem + "_48fps.webm")
    tmp = HERE / "._tmp_自检"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    rgb, alp, rgb2, alp2 = tmp/"r", tmp/"a", tmp/"r2", tmp/"a2"
    for d in (rgb, alp, rgb2, alp2):
        d.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    steps = [("拆彩色帧", [ffmpeg, "-nostdin", "-v", "error", "-y", *dec,
                       "-i", str(src), "-vf", "format=rgb24", str(rgb/"%05d.png")])]
    if has_alpha:
        steps.append(("拆透明通道", [ffmpeg, "-nostdin", "-v", "error", "-y", *dec,
                                 "-i", str(src), "-vf", "alphaextract,format=gray",
                                 str(alp/"%05d.png")]))
    for label, cmd in steps:
        t = time.time()
        rc, out = run(cmd)
        ok = rc == 0
        say(f"  {'✅' if ok else '❌'} {label:12s} 退出码 {rc}  用时 {time.time()-t:.1f}s")
        if not ok:
            say("      " + (out.strip().splitlines() or ["(没输出)"])[-1][:160])
            say("  ⛔ 这一步就失败了，后面的跳过")
            shutil.rmtree(tmp, ignore_errors=True)
            return

    n = len(list(rgb.glob("*.png")))
    say(f"  拆出 {n} 帧，目标 48fps → 应输出 {n*2} 帧")
    jobs = [("RIFE 彩色插帧", rgb, rgb2)]
    if has_alpha:
        jobs.append(("RIFE 透明插帧", alp, alp2))
    for label, srcdir, dstdir in jobs:
        t = time.time()
        rc, out = run([rife, "-i", str(srcdir), "-o", str(dstdir),
                       "-m", "rife-v4.6", "-g", "0", "-n", str(n*2)])
        ok = rc == 0
        say(f"  {'✅' if ok else '❌'} {label:12s} 退出码 {rc}  用时 {time.time()-t:.1f}s")
        if not ok:
            say("      " + (out.strip().splitlines() or ["(没输出)"])[-1][:160])
            shutil.rmtree(tmp, ignore_errors=True)
            return

    t = time.time()
    if has_alpha:
        enc = [ffmpeg, "-nostdin", "-v", "error", "-y",
               "-framerate", "48", "-i", str(rgb2/"%08d.png"),
               "-framerate", "48", "-i", str(alp2/"%08d.png"),
               "-filter_complex", "[0:v][1:v]alphamerge,format=yuva420p",
               "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
               "-auto-alt-ref", "0", "-row-mt", "1",
               "-crf", "32", "-b:v", "0", str(dst)]
    else:
        enc = [ffmpeg, "-nostdin", "-v", "error", "-y",
               "-framerate", "48", "-i", str(rgb2/"%08d.png"),
               "-c:v", "libvpx-vp9", "-pix_fmt", "yuv420p", "-row-mt", "1",
               "-crf", "32", "-b:v", "0", str(dst)]
    rc, out = run(enc)
    ok = rc == 0
    say(f"  {'✅' if ok else '❌'} {'合成编码':12s} 退出码 {rc}  用时 {time.time()-t:.1f}s")
    shutil.rmtree(tmp, ignore_errors=True)
    if not ok:
        say("      " + (out.strip().splitlines() or ["(没输出)"])[-1][:160])
        return

    got = probe(ffprobe, dst)
    say("")
    say(f"  输出文件：{dst.name}  ({dst.stat().st_size/1024:.0f} KB)")
    say(f"  输出规格：{got.get('width')}x{got.get('height')} "
        f"{got.get('r_frame_rate')} {got.get('pix_fmt')} 时长 {got.get('duration')}s")
    ok_fmt = ("yuva" in str(got.get("pix_fmt"))) if has_alpha else \
             ("yuva" not in str(got.get("pix_fmt")))
    good = (got.get("width") == info.get("width")
            and got.get("r_frame_rate") == "48/1" and ok_fmt)
    say(f"  规格校验：{'✅ 通过（尺寸一致、48fps、透明通道状态正确）' if good else '❌ 不对，见上面'}")
    say(f"  总用时  ：{time.time()-t0:.0f} 秒")
    if good:
        say("")
        say(f"  🎉 全流程通了！输出文件在：{outdir}")


# --------------------------------------------------------------- 5 结论
def section_result(tools: dict, assets: list[Path], converted: bool) -> None:
    hr("五、结论")
    missing = []
    if not tools.get("ffmpeg"):
        missing.append("ffmpeg")
    if not tools.get("ffprobe"):
        missing.append("ffprobe")
    if not tools.get("rife"):
        missing.append("rife-ncnn-vulkan")
    if not tools.get("model_dir"):
        missing.append("rife 的模型目录")
    if not assets:
        missing.append("测试素材")
    if missing:
        say(f"  ❌ 还缺：{'、'.join(missing)}")
        say("     补上之后 **再跑一次这个脚本**，它自己会继续往下测。")
    elif converted:
        say("  ✅ 环境齐全，而且实际转换已经跑通。")
        say("     结论：这台机器可以正常用这个工具包。")
    else:
        say("  ⚠️ 环境看着齐全，但转换没跑（看第四节）")


def main() -> int:
    say("DSH Pet 插帧工具 · 快速自检报告")
    say("=" * 64)
    say("（这份文件是自动生成的。遇到问题，把整个文件发给作者就行。）")
    converted = False
    try:
        section_system()
        tools = section_tools()
        assets = section_assets()
        if all([tools.get("ffmpeg"), tools.get("ffprobe"),
                tools.get("rife"), tools.get("model_dir")]) and assets:
            section_convert(tools, assets)
            converted = (HERE / "自检输出").is_dir() and any(
                (HERE / "自检输出").glob("*.webm"))
        else:
            section_convert(tools, assets)
        section_result(tools, assets, converted)
    except Exception as exc:
        hr("出错了")
        import traceback
        say(f"  自检脚本自己崩了：{exc}")
        say(traceback.format_exc())
        say("  把这个报告整个发出去，就能定位。")
    finally:
        hr()
        say("报告结束。把「自检报告.txt」发给作者即可。")
        try:
            REPORT.write_text("\n".join(LINES) + "\n", encoding="utf-8-sig")
            print(f"\n>>> 报告已写入：{REPORT}", flush=True)
        except Exception as exc:
            print(f"\n>>> 报告写入失败：{exc}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback
        traceback.print_exc()
        try:
            input("\n按回车键关闭…")
        except Exception:
            pass
        sys.exit(1)
