#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""音频外挂 · 形状定义与注册表（**只依赖标准库**）

这一层只干三件事：
    1. 定义所有模型必须长什么样（BaseAudioModel）
    2. 提供注册表，让具体模型自己来报到（@注册("名字")）
    3. 提供一个"这模型现在能不能用"的自检（缺第三方包时别硬上）

这里**绝不 import 任何第三方库** —— 第三方只在具体模型的 load() 里延迟 import，
这样"没装依赖"的机器也能 import 本模块、问到"这模型可用吗？→ 不可用，原因是…"。
"""

from __future__ import annotations

import abc
import importlib.util
from pathlib import Path

SCHEMA作业 = "pet-audio-job/1"
SCHEMA结果 = "pet-audio-result/1"


class BaseAudioModel(abc.ABC):
    """Common interface of every audio model. Only two methods are required: `load(params)` and `process(src, dst, params) -> dict`.
    
    所有音频模型的统一接口。

    只要求两个方法：
        load(参数)                     加载模型/初始化（只做一次）
        process(输入, 输出, 参数) -> dict  处理一个文件，返回统计字典
    """

    #: 模型名（config 里「音频修复模型」填的就是它）
    name: str = ""
    #: 需要的第三方包（用于自检；空 = 只用标准库/系统程序）
    requires: tuple[str, ...] = ()
    #: 一句话说明（会显示在 GUI 的下拉说明和记录文件里）
    说明: str = ""

    # ------------------------------------------------------------------ 自检
    @classmethod
    def available(cls) -> tuple[bool, str]:
        """这个模型现在能不能用？返回 (可用, 原因)。"""
        缺 = [包 for 包 in cls.requires if importlib.util.find_spec(包) is None]
        if 缺:
            return False, "缺少依赖：" + "、".join(缺) + f"（pip install {' '.join(缺)}）"
        return True, ""

    # ------------------------------------------------------------------ 接口
    @abc.abstractmethod
    def load(self, 参数: dict) -> None:
        """加载模型。这里才允许 import 第三方库。放不下就抛异常，外面会降级。"""

    @abc.abstractmethod
    def process(self, 输入: Path, 输出: Path, 参数: dict) -> dict:
        """处理一个音频文件，写到 输出，返回统计字典（可为空 dict）。"""

    def describe(self) -> str:
        return self.说明 or f"{self.name}（{self.__class__.__name__}）"


# --------------------------------------------------------------------- 注册表
注册表: dict[str, type[BaseAudioModel]] = {}


def 注册(名字: str):
    """装饰器：把一个模型登记进注册表。"""
    def _包(cls: type[BaseAudioModel]) -> type[BaseAudioModel]:
        cls.name = 名字
        注册表[名字] = cls
        return cls
    return _包


def 可用模型() -> dict[str, tuple[bool, str]]:
    """列出所有已注册模型及可用性 —— worker 的 --自检 用它。"""
    return {名: cls.available() for 名, cls in sorted(注册表.items())}
