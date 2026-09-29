# -*- coding: utf-8 -*-
"""整片跑一遍：把那份 58 分钟的助眠录音真做一次快修。

用法：python3 跑整片.py 保真|保响度
两个策略分开跑（一次几分钟），方便对着听。
"""
import importlib.util
import sys
import time
from pathlib import Path

工具包 = Path.home() / "DSH-Pet-插帧工具包"
sys.path.insert(0, str(工具包))
spec = importlib.util.spec_from_file_location("audio_fix", 工具包 / "audio_fix.py")
af = importlib.util.module_from_spec(spec)
sys.modules["audio_fix"] = af
spec.loader.exec_module(af)

策略 = sys.argv[1] if len(sys.argv) > 1 else "保响度"
源 = Path.home() / "Downloads/firefly-sleep-final.wav"
出 = Path.home() / "Desktop/78/音频诊断/整片修复" / 策略   # ⚠️ 按策略分开存，不然两次会互相覆盖
出.mkdir(parents=True, exist_ok=True)

print("=" * 62)
print(f"整片快修 ｜ 策略 = {策略}")
print("=" * 62)
t0 = time.time()
r = af.run_audio_pipeline(源, 出, 配置={
    "音频修复_处理链路": ["dsp"],
    "音频修复_强度": "标准",
    "音频修复_EQ风格": "环境音",       # 实测这条素材语音风格几乎不动
    "音频修复_响度目标": -16,
    "音频修复_裁静音": True,           # 尾巴那一大段死寂要剪掉
    "音频修复_输出格式": "opus",
    "音频修复_削峰策略": 策略,
    "音频修复_输出方式": "音频",
})
r2 = r.get("统计") or {}
print("-" * 62)
print(f"  ok        = {r.get('ok')}   用时 {time.time() - t0:.1f} 秒")
print(f"  输出      = {r.get('输出')}")
if r.get("输出") and Path(r["输出"]).is_file():
    大 = Path(r["输出"]).stat().st_size / 1024 / 1024
    print(f"  体积      = {大:.1f} MB")
print(f"  前响度    = {r2.get('前响度')}  LUFS   真峰值 {r2.get('前真峰值')} dBTP")
print(f"  后响度    = {r2.get('后响度')}  LUFS   真峰值 {r2.get('后真峰值')} dBTP")
print(f"  前后时长  = {r2.get('前时长')} → {r2.get('后时长')} 秒（裁掉 {r2.get('裁掉秒数')} 秒静音）")
print(f"  最大变动  = {r2.get('最大变动段')}  {r2.get('最大变动值')} dB")
print(f"  降级      = {r.get('降级') or '无'}")
