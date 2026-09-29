# -*- coding: utf-8 -*-
"""把《桌宠 Bug 库》拆成一份份可以直接贴到 GitHub Issue 的草稿。

每份 = 一段标准抬头（项目/版本/环境/证据等级）+ 原文那一节 + 一段结尾。
标题单独写在一份清单里，贴的时候直接复制。
"""
import re
from pathlib import Path

来源 = Path.home() / "桌宠Bug库-给作者-2026-09-27.md"
出 = Path.home() / "Desktop/78/给作者-Issue草稿"
出.mkdir(parents=True, exist_ok=True)

文本 = 来源.read_text(encoding="utf-8")
行 = 文本.splitlines()

# 按 "## DB-0xx ·" 切段
段 = []
for i, 行内容 in enumerate(行):
    匹配 = re.match(r"^## (DB-\d{3}) · (.+)$", 行内容)
    if 匹配:
        段.append((匹配.group(1), 匹配.group(2), i))
段.append((None, None, 行.index(next(x for x in 行 if x.startswith("## 附录 A")))))

抬头 = """> 这条来自**第三方环境**的静态审查 + 最小复现，不是项目的 CI。
> 对象：`MerZlin/dsh-pet-indesktop` tag `v4.2.1` · commit `f4cb620`
> 审查环境：Linux Mint 22.3 / X11 / Python 3.12 / Qt 版桌面环境
> 方法：只读克隆（`chmod a-w`）+ AST 扫描 + 纯函数最小复现；标 🔵 的**没有**运行期压测，以你们实机为准。
> 需要复现脚本、原始输出或更多环境信息，随时说，本项目都留着。

---
"""

结尾 = """
---
**补一句**：本条已保留原始输出与复现脚本，需要就说一声。
如果判断是理解错了（比如某处调用链没有跟全），直接指出来，会照改。
"""

清单 = ["# 桌宠 Bug 库 → GitHub Issue 草稿清单", "",
        "仓库：`MerZlin/dsh-pet-indesktop` ｜ 对象版本：`v4.2.1` · `f4cb620`", "",
        "共 11 条。每条对应一个 `.md` 文件，**文件名前缀就是建议的 issue 标题**，",
        "直接新建 issue → 复制文件内容进正文 即可。", "",
        "| 编号 | 建议标题 | 级别 | 证据 | 对应文件 |", "|---|---|---|---|---|"]

摘要 = 文本[文本.index("## 摘要"):文本.index("## DB-001")]
级别表 = {}
for 行内容 in 摘要.splitlines():
    m = re.match(r"^\|\s*\*\*(DB-\d{3})\*\*\s*\|(.+?)\|(.+?)\|(.+?)\|", 行内容)
    if m:
        级别表[m.group(1)] = (m.group(2).strip(), m.group(3).strip(), m.group(4).strip())

for 序号, (编号, 标题, 起) in enumerate(段[:-1]):
    止 = 段[序号 + 1][2]
    正文 = "\n".join(行[起 + 1:止]).strip()
    级别, 证据, _ = 级别表.get(编号, ("?", "?", "?"))
    干净证据 = 证据.replace("**", "").replace("🟢 ", "🟢 ").strip()
    文件名 = f"{编号}-{标题}.md".replace("/", "／").replace("`", "")
    出.joinpath(文件名).write_text(
        f"# {编号} · {标题}\n\n{抬头}\n{正文}\n{结尾}", encoding="utf-8")
    清单.append(f"| {编号} | {标题} | {级别} | {干净证据} | `{文件名}` |")

出.joinpath("00-怎么发.md").write_text("\n".join(清单) + """

---

## 发之前要做的三件事

1. **先搜一下有没有重复的 issue**（作者的仓库里可能已经有人报过）。
2. 一次发一条，标题就用文件名前面那串（例如 `DB-003 · 非 Windows 回退播放器的子进程从不回收`）。
   同一批不要一口气刷 11 条 —— 分开发，作者的 issue 列表看着也舒服。
3. 每条正文里都写了「位置」和「复现」，对方要核对的时候能对上。

## 建议的发布顺序（先发影响最大的）

| 顺序 | 编号 | 为什么先发 |
|---|---|---|
| 1 | DB-001 | 唯一「已经影响真实使用」的：整块窗口吞鼠标，用户会以为电脑卡死 |
| 2 | DB-005 | 主动记忆并发写丢数据，这个是**数据丢失** |
| 3 | DB-003 | 僵尸进程累积，长跑会出事 |
| 4 | DB-004 | 一个超大字段就把整份 data 清空，损失面大 |
| 5 | DB-002 | 它让 DB-001 完全不可诊断，两条一起看 |
| 6~11 | 其余 | 一致性 / 可维护性，不急 |
""", encoding="utf-8")

print(f"  ✓ 出到：{出}")
for f in sorted(出.iterdir()):
    print(f"     {f.stat().st_size:>6} B  {f.name}")
