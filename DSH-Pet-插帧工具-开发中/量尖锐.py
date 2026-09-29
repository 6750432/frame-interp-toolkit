# -*- coding: utf-8 -*-
"""量一量「尖锐」到底从哪来：源 vs 本工具处理后的成品，逐频段对比。

思路：把同一个 30 秒窗口分别过带通，量各段 RMS，再对齐整体电平做差。
如果 2.8k / 8k 这两段是**自身 EQ 顶上去的**，那"尖锐"就是工具造成的，
改 EQ 就行，不用上模型。反之才需要外挂模型。
"""
import json
import subprocess
import sys
from pathlib import Path

源 = Path.home() / "Downloads/firefly-sleep-final.wav"
成品 = Path.home() / "Desktop/78/音频诊断/整片修复/2a-保响度-正中目标.opus"
起 = 900      # 从第 15 分钟取 30 秒
时长 = 30

# 源是 24 kHz → 奈奎斯特 12 kHz，所以最高只能量到 12k
频段 = [
    ("80-300",   "highpass=f=80,lowpass=f=300"),
    ("300-1k",   "highpass=f=300,lowpass=f=1000"),
    ("1k-2.8k",  "highpass=f=1000,lowpass=f=2800"),
    ("2.8k-5k",  "highpass=f=2800,lowpass=f=5000"),
    ("5k-8k",    "highpass=f=5000,lowpass=f=8000"),
    ("8k-12k",   "highpass=f=8000,lowpass=f=12000"),
]


def 量(文件: Path, 段: str) -> float | None:
    """返回这一段的 RMS 电平（dBFS）。"""
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostdin", "-ss", str(起), "-t", str(时长),
         "-i", str(文件), "-af", f"{段},astats=measure_overall=RMS_level:measure_perchannel=none",
         "-f", "null", "-"],
        capture_output=True, text=True)
    值 = []
    for 行 in p.stderr.splitlines():
        if "RMS level dB" in 行:
            值.append(float(行.split(":")[-1]))
    return 值[0] if 值 else None


def 总响度(文件: Path) -> float:
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostdin", "-ss", str(起), "-t", str(时长),
         "-i", str(文件), "-af", "loudnorm=print_format=json", "-f", "null", "-"],
        capture_output=True, text=True)
    for i, 行 in enumerate(p.stderr.splitlines()):
        if '"input_i"' in 行:
            return float(行.split(":")[1].strip().strip('",'))
    return float("nan")


print(f"窗口：第 {起} 秒起 {时长} 秒")
响源, 响成 = 总响度(源), 总响度(成品)
整体差 = 响成 - 响源
print(f"整体响度：源 {响源:.2f} LUFS ｜ 成品 {响成:.2f} LUFS ｜ 成品比源 {整体差:+.2f} dB")
print()
print(f"{'频段':>10} {'源 dBFS':>10} {'成品 dBFS':>10} {'净变动 dB':>11}")
print("-" * 46)
明细 = []
for 名, 链 in 频段:
    a, b = 量(源, 链), 量(成品, 链)
    if a is None or b is None:
        print(f"{名:>10} {'量不出来':>10}")
        continue
    净 = (b - 整体差) - a            # 扣掉整体增益，只看"形状"变了多少
    明细.append((名, a, b, 净))
    print(f"{名:>10} {a:>10.2f} {b:>10.2f} {净:>+11.2f}")

print()
高 = [x for x in 明细 if x[0] in ("2.8k-5k", "5k-8k", "8k-12k")]
if 高:
    平均 = sum(x[3] for x in 高) / len(高)
    print(f"高频三段（2.8k 以上）平均净变动：{平均:+.2f} dB")
    if 平均 > 1.5:
        print("  ⚠️ 高频是自身 EQ 顶上去的 —— 「尖锐」很可能是工具造成的，先改 EQ。")
    elif 平均 < -1.5:
        print("  ✔ 高频反而被压了一点，尖锐应该来自源素材本身。")
    else:
        print("  – 高频基本没动，尖锐来自源素材本身或 TTS 合成痕迹。")
