# -*- coding: utf-8 -*-
"""音频快修 · 回归测试（今天动过 audio_fix.py 和 gui_audio.py，跑一遍确认没坏）

覆盖：
  A. 纯音频入口（只修声音）—— 用现成的 30 秒片段
  B. 封回视频入口（mp4 源 + 输出方式=视频）—— 验证音轨换成 AAC、视频流原样复制
  C. 降级路径：链路里塞一个不存在的外挂，必须自动降级成 DSP、不能抛异常
  D. 链路空数组：必须"什么都不做"地安全返回
"""
import json
import subprocess
import sys
import time
from pathlib import Path

工具包 = Path.home() / "DSH-Pet-插帧工具包"
sys.path.insert(0, str(工具包))
import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("audio_fix", 工具包 / "audio_fix.py")
af = importlib.util.module_from_spec(spec)
sys.modules["audio_fix"] = af
spec.loader.exec_module(af)

工作 = Path("/tmp/音频回归")
工作.mkdir(exist_ok=True)
结果 = []


def 记(名称, 通过, 备注=""):
    print(("  ✔ " if 通过 else "  ✘ ") + 名称 + (f"   {备注}" if 备注 else ""))
    结果.append((名称, 通过, 备注))


def 探一下(路径):
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json",
                        "-show_streams", "-show_format", str(路径)],
                       capture_output=True, text=True)
    return json.loads(r.stdout or "{}")


print("=" * 62)
print("A. 纯音频：只修声音")
print("=" * 62)
源A = Path.home() / "Desktop/78/音频诊断/1-原声片段-28分00秒起30秒.opus"
if not 源A.is_file():
    记("A 素材存在", False, str(源A))
else:
    t0 = time.time()
    r = af.run_audio_pipeline(源A, 工作, 配置={
        "音频修复_处理链路": ["dsp"], "音频修复_EQ风格": "环境音",
        "音频修复_强度": "标准", "音频修复_输出格式": "opus",
        "音频修复_输出方式": "音频", "音频修复_裁静音": True,
    })
    用时 = time.time() - t0
    记("A 跑通（没抛异常）", isinstance(r, dict), f"{用时:.1f} 秒")
    记("A ok = True", r.get("ok") is True, str(r.get("消息"))[:70])
    记("A 有输出文件", bool(r.get("输出")) and Path(r["输出"]).is_file(),
       str(r.get("输出")))
    if r.get("输出") and Path(r["输出"]).is_file():
        info = 探一下(r["输出"])
        音频 = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
        记("A 输出是 opus 音轨", bool(音频) and 音频[0].get("codec_name") == "opus",
           f"{音频[0].get('codec_name') if 音频 else '?'}")
    统计 = r.get("统计") or {}
    print(f"      统计：{json.dumps(统计, ensure_ascii=False, default=str)[:220]}")

print()
print("=" * 62)
print("B. 封回视频：mp4 源 + 输出方式=视频")
print("=" * 62)
源B = 工作 / "源-带声音-12秒.mp4"
if not 源B.is_file():
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error",
                    "-f", "lavfi", "-i", "testsrc=size=320x180:rate=24:duration=12",
                    "-f", "lavfi", "-i", "sine=frequency=180:sample_rate=48000:duration=12",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", str(源B)], check=True)
    记("B 造出 mp4 测试源", 源B.is_file(), f"{源B.stat().st_size / 1024:.0f} KB")
if 源B.is_file():
    r = af.run_audio_pipeline(源B, 工作, 配置={
        "音频修复_处理链路": ["dsp"], "音频修复_EQ风格": "语音",
        "音频修复_输出格式": "opus",          # 故意选 opus：封进 mp4 必须自动换成 aac
        "音频修复_输出方式": "视频", "音频修复_视频容器": "",
        "音频修复_裁静音": True,               # 故意开着：选视频时必须自动关掉
    })
    记("B 跑通（没抛异常）", isinstance(r, dict))
    记("B ok = True", r.get("ok") is True, str(r.get("消息"))[:70])
    出 = Path(r.get("输出") or "/nonexistent")
    记("B 有输出文件", 出.is_file(), 出.name)
    if 出.is_file():
        info = 探一下(出)
        流 = {s.get("codec_type"): s.get("codec_name") for s in info.get("streams", [])}
        记("B 容器跟随源（mp4）", 出.suffix.lower() == ".mp4", 出.suffix)
        记("B 音轨自动换成 aac（不是 opus，否则哑巴）", 流.get("audio") == "aac",
           f"音频={流.get('audio')}")
        记("B 视频流原样复制（h264）", 流.get("video") == "h264",
           f"视频={流.get('video')}")
        时长 = float((info.get("format") or {}).get("duration") or 0)
        记("B 长度没被剪短（选视频时自动关掉裁静音）", abs(时长 - 12) < 1.2,
           f"时长 {时长:.2f}s（源 12s）")

print()
print("=" * 62)
print("C. 降级：链路里塞一个不存在的外挂")
print("=" * 62)
try:
    r = af.run_audio_pipeline(源A, 工作, 配置={
        "音频修复_处理链路": ["dsp", "根本没这个模型"],
        "音频修复_EQ风格": "环境音", "音频修复_输出方式": "音频",
        "音频修复_输出格式": "opus", "音频修复_降级时提醒": True,
    })
    记("C 没抛异常", True)
    记("C ok = True（降级也要出结果）", r.get("ok") is True, str(r.get("消息"))[:80])
    记("C 记录里说明降级了",
       bool(r.get("降级")) or "降级" in json.dumps(r, ensure_ascii=False),
       f"降级={r.get('降级')}")
except Exception as exc:
    记("C 没抛异常", False, repr(exc))

print()
print("=" * 62)
print("D. 空链路：必须安全地什么都不做")
print("=" * 62)
try:
    r = af.run_audio_pipeline(源A, 工作, 配置={"音频修复_处理链路": [],
                                              "音频修复_模型": "无"})
    记("D 没抛异常", True, f"ok={r.get('ok')} 跳过={r.get('跳过')}")
except Exception as exc:
    记("D 没抛异常", False, repr(exc))

print()
print("=" * 62)
坏 = [n for n, ok, _ in 结果 if not ok]
print(("全部通过 ✔" if not 坏 else f"有 {len(坏)} 项没过：" + "、".join(坏)))
print("=" * 62)
sys.exit(0 if not 坏 else 2)
