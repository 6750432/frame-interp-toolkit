#!/usr/bin/env bash
# 把 Bug 库草稿发成上游 issue。用法：bash 发issue.sh [最多发几条]
# ⚠️ 这个沙盒的 locale 是 C，bash 里不能用中文变量名（踩过好几次）
set -u
export PATH=$HOME/.local/bin:$PATH
UPSTREAM="MerZlin/dsh-pet-indesktop"
DRAFTS="$HOME/Desktop/78/给作者-Issue草稿"
LIMIT=${1:-99}

LIST=(
  "DB-001-素材与画布不符 → 整块窗口吞鼠标，且没有任何日志.md"
  "DB-005-主动记忆文件多实例共享，且无锁读改写.md"
  "DB-003-非 Windows 回退播放器的子进程从不回收.md"
  "DB-004-bounded_data() 遇到超大字段会把整份 data 清空.md"
  "DB-002-首帧长度校验失败是静默的（让 DB-001 完全不可诊断）.md"
  "DB-009-3 处 assert 当运行期校验.md"
  "DB-010-parse_agent_event() 不校验 schema 值.md"
  "DB-006-主动记忆落盘缺 fsync.md"
  "DB-008-槽位 seed 配置是非原子写.md"
  "DB-007-ProactiveMemory 类 docstring 与实现矛盾（隐私相关）.md"
  "DB-011-10 个模块在测试里完全没被提到.md"
)

n=0
for f in "${LIST[@]}"; do
  n=$((n+1))
  if [ "$n" -gt "$LIMIT" ]; then break; fi
  path="$DRAFTS/$f"
  if [ ! -f "$path" ]; then echo "  ✘ 找不到：$path"; continue; fi
  base="${f%.md}"
  base="${base/-/ · }"                       # 文件名里 DB-001-xxx 的第一个连字符换成间隔号
  title="[Bug] $base"
  case "$f" in DB-011*) title="[提示] $base";; esac
  echo "── [$n] $title"
  tmp=$(mktemp)
  tail -n +2 "$path" | sed '/./,$!d' > "$tmp"     # 去掉第一行 H1 和开头空行
  gh issue create --repo "$UPSTREAM" --title "$title" --body-file "$tmp" 2>&1 | tail -2
  rm -f "$tmp"
  sleep 3
done
