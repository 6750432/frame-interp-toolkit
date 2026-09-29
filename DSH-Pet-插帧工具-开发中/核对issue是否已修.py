# -*- coding: utf-8 -*-
"""核对：报送的 11 条，在作者最新 main 上还成不成立。

对比对象：
  旧 = /tmp/审阅版                     （所审的 f4cb620 / v4.2.1）
  新 = /tmp/上游main/dsh-pet-indesktop-main  （作者默认分支最新 2786c15）
"""
import re
import subprocess
from pathlib import Path

OLD = Path("/tmp/审阅版")
NEW = Path("/tmp/上游main/dsh-pet-indesktop-main")


def 读(根, 路径):
    p = 根 / 路径
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""


def 行号查(文本, 模式):
    出 = []
    for i, l in enumerate(文本.splitlines(), 1):
        if re.search(模式, l):
            出.append((i, l.strip()))
    return 出


print("=" * 62)
print("DB-001 · 素材与画布不符 → 整块窗口吞鼠标")
print("=" * 62)
for 名, 根 in (("旧 f4cb620", OLD), ("新 main", NEW)):
    t = 读(根, "pet/window.py")
    调用 = [i for i, l in 行号查(t, r"_sync_mask\(\)") if "def " not in l]
    print(f"  {名}：_sync_mask() 被调用的行号 = {调用}")
    # showEvent 里有没有
    m = re.search(r"def showEvent.*?(?=\n    def )", t, re.S)
    print(f"      showEvent 里提到 _sync_mask：{'是' if m and '_sync_mask' in m.group(0) else '否'}")
    # 无帧退化守卫
    守卫 = 行号查(t, r"hasattr\(self, .*_frames|if not self\._frames|QRegion\(0,\s*0,\s*1,\s*1\)")
    print(f"      无帧兜底（退化 mask / 无帧守卫）：{守卫 if 守卫 else '没有'}")

print()
print("  作者这次 window.py 到底改了什么（与本条是否相关）")
d = subprocess.run(["diff", "-u", str(OLD / "pet/window.py"), str(NEW / "pet/window.py")],
                   capture_output=True, text=True).stdout
增 = [l for l in d.splitlines() if l.startswith("+") and not l.startswith("+++")]
删 = [l for l in d.splitlines() if l.startswith("-") and not l.startswith("---")]
print(f"      净增 {len(增)} 行 / 净删 {len(删)} 行")
关键词 = ("mask", "showEvent", "mouseTransparent", "setMask", "input")
命中 = [l.strip()[:90] for l in 增 + 删 if any(k in l for k in 关键词)]
print(f"      跟输入区/遮罩相关的改动：{len(命中)} 行")
for l in 命中[:6]:
    print("        ", l)

print()
print("=" * 62)
print("DB-002 · 首帧长度校验失败是静默的")
print("=" * 62)
for 名, 根 in (("旧", OLD), ("新", NEW)):
    t = 读(根, "pet/webm_clip.py")
    行 = t.splitlines()
    附近 = [(i, l.strip()) for i, l in enumerate(行, 1)
            if 1840 < i < 1870 and ("return None" in l or "if " in l)]
    print(f"  {名} 第 1840~1870 行附近：")
    for i, l in 附近[:6]:
        print(f"      {i}: {l[:86]}")
    日志 = [i for i, l in 行号查(t, r"(log|logging|print|warn)") if 1830 < i < 1880]
    print(f"      这一段里有没有任何日志/警告：{'有 ' + str(日志) if 日志 else '没有'}")

print()
print("=" * 62)
print("DB-003~010 · 涉及的文件有没有被改过")
print("=" * 62)
文件 = {
    "DB-003": "pet/click_sound.py",
    "DB-004/010": "pet/agent_event_protocol.py",
    "DB-005/006/007": "pet/proactive_memory.py",
    "DB-005": "pet/proactive.py",
    "DB-008": "pet/slot_manager.py",
    "DB-009": "pet/catalog.py",
    "DB-009b": "pet/festival_data.py",
}
for 编号, f in 文件.items():
    同 = (OLD / f).read_bytes() == (NEW / f).read_bytes()
    print(f"  {编号:<12} {f:<34} {'没变 → 结论仍成立' if 同 else '**变了，要复查**'}")

print()
print("=" * 62)
print("DB-011 · 没被测试提到的模块数（现在的数字）")
print("=" * 62)
for 名, 根 in (("旧", OLD), ("新", NEW)):
    模块 = {p.stem for p in (根 / "pet").rglob("*.py")
            if not p.name.startswith("__") and "test" not in p.name}
    测试文本 = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                       for p in (根 / "tests").rglob("*.py"))
    没提到 = sorted(m for m in 模块 if m not in 测试文本)
    print(f"  {名}：pet/ 下 {len(模块)} 个模块，测试里完全没提到 {len(没提到)} 个")
    if 名 == "新":
        print("      新增的测试文件：", end="")
        print(", ".join(sorted(p.name for p in (根 / "tests").glob("*.py")
                               if p.name not in {q.name for q in (OLD / "tests").glob("*.py")})[:6]))
