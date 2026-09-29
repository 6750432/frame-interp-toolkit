# -*- coding: utf-8 -*-
"""收拾刚才发歪的标题 + 关掉两条重复的。

⚠️ 教训记一笔：标题里 `${base/-/ · }` 只替换**第一个**连字符，
   而 "DB-001-素材…" 的第一个连字符在 DB-001 里面 —— 于是变成 "DB · 001-素材…"。
   正确做法是取前 6 个字符当编号，第 7 位那个 "-" 去掉。
"""
import subprocess
from pathlib import Path

R = "MerZlin/dsh-pet-indesktop"
DRAFTS = Path.home() / "Desktop/78/给作者-Issue草稿"

# issue 号 → 草稿文件名
映射 = {
    195: "DB-001-素材与画布不符 → 整块窗口吞鼠标，且没有任何日志.md",
    196: "DB-005-主动记忆文件多实例共享，且无锁读改写.md",
    199: "DB-003-非 Windows 回退播放器的子进程从不回收.md",
    200: "DB-004-bounded_data() 遇到超大字段会把整份 data 清空.md",
    201: "DB-002-首帧长度校验失败是静默的（让 DB-001 完全不可诊断）.md",
    202: "DB-009-3 处 assert 当运行期校验.md",
    203: "DB-010-parse_agent_event() 不校验 schema 值.md",
    204: "DB-006-主动记忆落盘缺 fsync.md",
    205: "DB-008-槽位 seed 配置是非原子写.md",
    206: "DB-007-ProactiveMemory 类 docstring 与实现矛盾（隐私相关）.md",
    207: "DB-011-10 个模块在测试里完全没被提到.md",
}
重复 = {197: 195, 198: 196}


def 跑(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


print("===== ① 关掉两条重复的 =====")
for 号, 原 in 重复.items():
    备注 = (f"这条是重复提交，内容和 #{原} 完全一样。"
            f"关掉这条，讨论请去 #{原}。抱歉刷了两条。")
    code, out = 跑(["gh", "issue", "close", str(号), "--repo", R, "--comment", 备注])
    print(f"  #{号} → {'已关闭' if code == 0 else '失败：' + out}")

print()
print("===== ② 修正标题 =====")
for 号, 文件 in 映射.items():
    名 = 文件[:-3]                      # 去掉 .md
    编号, 其余 = 名[:6], 名[7:]          # "DB-001" + 剩下的（第 7 位是那个连字符）
    前缀 = "[提示]" if 编号 == "DB-011" else "[Bug]"
    标题 = f"{前缀} {编号} {其余}"
    code, out = 跑(["gh", "issue", "edit", str(号), "--repo", R, "--title", 标题])
    print(f"  #{号}  {'✓' if code == 0 else '✘ ' + out}  {标题}")
