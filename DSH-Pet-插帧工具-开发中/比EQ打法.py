# -*- coding: utf-8 -*-
"""对着同一条素材，量几种 EQ 打法各自把高频顶高了多少。

目的：给用户一个"今天就能用"的选择，而不是等模型。
"""
import subprocess
from pathlib import Path

源 = Path.home() / "Downloads/firefly-sleep-final.wav"
起, 时长 = 900, 30
频段 = [("80-300", "highpass=f=80,lowpass=f=300"),
        ("1k-2.8k", "highpass=f=1000,lowpass=f=2800"),
        ("2.8k-5k", "highpass=f=2800,lowpass=f=5000"),
        ("5k-8k", "highpass=f=5000,lowpass=f=8000"),
        ("8k-12k", "highpass=f=8000,lowpass=f=12000")]

候选 = {
    "现在用的：环境音·标准": "highpass=f=40,equalizer=f=220:t=q:w=1:g=-8,equalizer=f=500:t=q:w=1:g=-2,equalizer=f=2800:t=q:w=1.2:g=4,highshelf=f=8000:g=4",
    "环境音·轻": "highpass=f=40,equalizer=f=220:t=q:w=1:g=-4.8,equalizer=f=500:t=q:w=1:g=-1.2,equalizer=f=2800:t=q:w=1.2:g=2.4,highshelf=f=8000:g=2.4",
    "语音·标准": "highpass=f=45,lowshelf=f=200:g=-5:width_type=q:width=0.8,equalizer=f=3200:width_type=q:width=1.5:g=3,highshelf=f=9000:g=3:width_type=q:width=1",
    "候选·去尖版（低频照旧，高频只提 1.5 dB）": "highpass=f=40,equalizer=f=220:t=q:w=1:g=-8,equalizer=f=500:t=q:w=1:g=-2,equalizer=f=2800:t=q:w=1.2:g=1.5,highshelf=f=8000:g=1.5",
}


def 段电平(链: str, 段: str) -> float | None:
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-ss", str(起), "-t", str(时长),
                        "-i", str(源), "-af", f"{链},{段},astats=measure_overall=RMS_level:measure_perchannel=none",
                        "-f", "null", "-"], capture_output=True, text=True)
    值 = [float(x.split(":")[-1]) for x in p.stderr.splitlines() if "RMS level dB" in x]
    return 值[0] if 值 else None


def 响度(链: str) -> float:
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-ss", str(起), "-t", str(时长),
                        "-i", str(源), "-af", f"{链},loudnorm=print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    for 行 in p.stderr.splitlines():
        if '"input_i"' in 行:
            return float(行.split(":")[1].strip().strip('",'))
    return float("nan")


基线 = {名: 段电平("anull", 段) for 名, 段 in 频段}
基线响 = 响度("anull")
print(f"源（第 {起} 秒起 {时长} 秒）：响度 {基线响:.2f} LUFS")
print(f"{'频段':>9}" + "".join(f"{k[:14]:>16}" for k in 候选))
print("-" * (9 + 16 * len(候选)))
结果 = {}
for 名, 链 in 候选.items():
    响 = 响度(链)
    结果[名] = (响, {n: 段电平(链, d) for n, d in 频段})

for n, _ in 频段:
    行 = f"{n:>9}"
    for 名 in 候选:
        响, 表 = 结果[名]
        净 = (表[n] - 响) - (基线[n] - 基线响)   # 两边都要先扣掉各自的整体响度
        行 += f"{净:>+16.2f}"
    print(行)

print()
print("（表里是**扣掉整体增益之后**的净变动，"+" = 这一段被相对顶高了，- = 被压低了）")
for 名, (响, _) in 结果.items():
    高频 = [ (结果[名][1][n] - 响) - (基线[n] - 基线响) for n, _ in 频段 if n in ("2.8k-5k", "5k-8k", "8k-12k") ]
    低 = (结果[名][1]["80-300"] - 响) - (基线["80-300"] - 基线响)
    print(f"  {名}")
    print(f"     低频段 {低:+.1f} dB ｜ 高频三段平均 {sum(高频)/len(高频):+.1f} dB")
