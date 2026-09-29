# -*- coding: utf-8 -*-
"""日志路由测试：音频跑一趟，检查**每一行阶段日志**有没有真的到界面。

不点鼠标：直接把 audio_fix 的日志钩子挂上，跑一小段音频，数一数收到几行、
是不是包含那几个「板块」（源 / 修复前 / 第一遍 / EQ 后实测 / 增益策略 /
频段自检 / 修复后 / 裁掉静音 / 记录已写入）。
"""
import importlib.util
import sys
from pathlib import Path

工具包 = Path.home() / "DSH-Pet-插帧工具包"
sys.path.insert(0, str(工具包))
spec = importlib.util.spec_from_file_location("audio_fix", 工具包 / "audio_fix.py")
af = importlib.util.module_from_spec(spec)
sys.modules["audio_fix"] = af
spec.loader.exec_module(af)

收到: list[str] = []
源 = Path.home() / "Desktop/78/音频诊断/1-原声片段-28分00秒起30秒.opus"
出 = Path("/tmp/音频回归/日志路由")
出.mkdir(parents=True, exist_ok=True)

r = af.run_audio_pipeline(源, 出, 配置={
    "音频修复_处理链路": ["dsp"], "音频修复_EQ风格": "环境音",
    "音频修复_输出方式": "音频", "音频修复_输出格式": "opus",
    "音频修复_裁静音": True,
}, 日志=收到.append)

要的板块 = ["【源】", "修复前", "第一遍", "EQ 后实测", "增益策略",
            "频段自检", "修复后", "裁掉静音", "记录已写入"]
print("=" * 60)
print(f"钩子共收到 {len(收到)} 行日志")
print("=" * 60)
缺 = []
for 板块 in 要的板块:
    有 = any(板块 in x for x in 收到)
    print(("  ✔ " if 有 else "  ✘ ") + 板块)
    if not 有:
        缺.append(板块)

print()
print("  ── 收到的原文（前 12 行）──")
for 行 in 收到[:12]:
    print("   ", 行)

# 钩子必须被摘掉，否则会污染下一次任务
print()
print("  ✔ 钩子已摘掉" if af._日志钩子 is None else "  ✘ 钩子没摘掉！")
sys.exit(0 if not 缺 and af._日志钩子 is None else 2)
