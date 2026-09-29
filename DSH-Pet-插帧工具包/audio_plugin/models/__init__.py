# -*- coding: utf-8 -*-
"""具体模型都放这里；worker.py 会自动把它们 import 进来登记。

约定：每个文件用 @注册("名字") 登记自己的模型；第三方库一律在 load() 里延迟 import。
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path


def 全部载入() -> list[str]:
    """把本目录下所有模型模块 import 一遍（登记进注册表），返回载入成功的模块名。"""
    已载 = []
    for 项 in sorted(pkgutil.iter_modules([str(Path(__file__).parent)]), key=lambda m: m.name):
        if 项.name.startswith("_"):
            continue
        try:
            importlib.import_module(f"{__name__}.{项.name}")
            已载.append(项.name)
        except Exception as exc:                     # 单个模型坏掉不影响其它模型
            print(f"[外挂] 载入模型模块失败 {项.name}: {exc}", flush=True)
    return 已载
