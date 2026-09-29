#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""音频外挂 · 子进程入口（worker）

主工具**只通过命令行**调它，不做 import：

    python <本文件> --作业 job.json --结果 result.json    处理一个文件
    python <本文件> --自检                                 列出可用模型（JSON）

为什么非要走子进程（而不是在主工具里 import 进来）：
    · AI 模型要 onnxruntime / numpy / librosa —— 而主工具的卖点就是"零第三方依赖"。
      只有把外挂放进**另一个解释器**，才能两边都不破功。
    · onnxruntime 这类原生扩展是真能段错误崩进程的；崩在子进程里 = 主工具毫发无伤。
    · 外挂目录被删、被换成坏的、解释器版本不对 —— 主工具一律只是"这次降级"。

约定：
    · 本文件在 import 阶段**只用标准库**；第三方只允许出现在具体模型的 load() 里。
    · 成功：退出码 0，结果 JSON 的 ok=true。
    · 任何失败：退出码非 0，结果 JSON 的 ok=false 且带错误信息（主工具据此降级）。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # 让 `audio_plugin` 可被找到

from audio_plugin.base import SCHEMA结果, 注册表, 可用模型   # noqa: E402


def 写结果(路径: Path | None, 数据: dict) -> None:
    数据.setdefault("schema", SCHEMA结果)
    if 路径 is None:
        return
    try:
        路径.write_text(json.dumps(数据, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        print(f"[worker] 结果文件写不进去：{exc}", file=sys.stderr, flush=True)


def 自检() -> int:
    from audio_plugin.models import 全部载入
    载入 = 全部载入()
    print(json.dumps({"schema": "pet-audio-selftest/1",
                      "解释器": sys.version.split()[0],
                      "已载入模块": 载入,
                      "模型": 可用模型()}, ensure_ascii=False, indent=2))
    return 0


def 干活(作业路径: Path, 结果路径: Path | None) -> int:
    try:
        作业 = json.loads(作业路径.read_text(encoding="utf-8"))
    except Exception as exc:
        写结果(结果路径, {"ok": False, "消息": f"作业文件读不了：{exc}"})
        return 2

    模型名 = str(作业.get("模型") or "")
    参数 = dict(作业.get("参数") or {})
    参数.setdefault("ffmpeg", 作业.get("ffmpeg") or "")
    起点 = time.time()

    from audio_plugin.models import 全部载入
    全部载入()                                     # 登记所有模型

    cls = 注册表.get(模型名)
    if cls is None:
        写结果(结果路径, {"ok": False, "模型": 模型名,
                          "消息": f"外挂里没有这个模型（可用：{'、'.join(sorted(注册表)) or '无'}）"})
        return 3

    可用, 原因 = cls.available()
    if not 可用:
        写结果(结果路径, {"ok": False, "模型": 模型名, "消息": 原因})
        return 4

    try:
        模型 = cls()
        print(f"[worker] 载入模型 {模型名} …", file=sys.stderr, flush=True)
        模型.load(参数)
        输入 = Path(str(作业.get("输入") or ""))
        输出 = Path(str(作业.get("输出") or ""))
        if not 输入.is_file():
            写结果(结果路径, {"ok": False, "模型": 模型名, "消息": f"输入文件不存在：{输入}"})
            return 5
        输出.parent.mkdir(parents=True, exist_ok=True)
        统计 = 模型.process(输入, 输出, 参数) or {}
        if not 输出.is_file():
            写结果(结果路径, {"ok": False, "模型": 模型名, "消息": "模型跑完了但没产出文件"})
            return 6
        写结果(结果路径, {"ok": True, "模型": 模型名, "输出": str(输出),
                          "耗时": round(time.time() - 起点, 2), "统计": 统计, "消息": ""})
        print(f"[worker] 完成：{输出}", file=sys.stderr, flush=True)
        return 0
    except Exception as exc:
        详情 = traceback.format_exc(limit=3)
        print(详情, file=sys.stderr, flush=True)
        写结果(结果路径, {"ok": False, "模型": 模型名,
                          "消息": f"{type(exc).__name__}: {exc}", "堆栈": 详情})
        return 7


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="DSH Pet 音频外挂 worker")
    p.add_argument("--作业", help="作业 JSON 路径")
    p.add_argument("--结果", help="结果 JSON 写到哪")
    p.add_argument("--自检", action="store_true", help="列出可用模型后退出")
    a = p.parse_args(argv)
    if a.自检:
        return 自检()
    if not a.作业:
        print("要么给 --作业，要么给 --自检", file=sys.stderr)
        return 1
    return 干活(Path(a.作业), Path(a.结果) if a.结果 else None)


if __name__ == "__main__":
    sys.exit(main())
