# -*- coding: utf-8 -*-
"""AI 模型空壳（尚未实现的档位占位）

dpdfnet2 已经有真实现了（models/dpdfnet2.py），这里只剩还没接的两个。

按约定：**先把接口留足，实现后填**。这三个名字现在就能在 GUI 里选到，
但因为没有装依赖（也没写实现），`available()` 会直接说清楚缺什么，
链路执行时会被判为"不可用"→ 自动降级为粗修，绝不会让主流程出错。

真实现的时候：把 process() 里那句 raise 换成真正的模型调用即可，其它地方一个字不用改。
"""

from __future__ import annotations

from pathlib import Path

from ..base import BaseAudioModel, 注册


class _未实现(BaseAudioModel):
    """Stub base class: it states "not implemented yet" in plain words instead of raising an obscure import error.
    
    空壳基类：把"还没实现"这件事说清楚，而不是抛一堆看不懂的错。
    """

    requires: tuple[str, ...] = ("numpy", "onnxruntime")
    还没有实现 = True
    对应链路 = "精修"

    def load(self, 参数: dict) -> None:
        raise NotImplementedError(f"{self.name} 尚未实现（{self.对应链路}档，等模型接进来）")

    def process(self, 输入: Path, 输出: Path, 参数: dict) -> dict:
        raise NotImplementedError(f"{self.name} 尚未实现")

    @classmethod
    def available(cls) -> tuple[bool, str]:
        可用, 原因 = super().available()
        if not 可用:
            return False, 原因
        return False, f"{cls.name} 的推理实现还没接进来（接口已留好）"


@注册("gtcrn")
class GTCRN(_未实现):
    """GTCRN slot — declared but not implemented. Selecting it degrades to the built-in DSP chain instead of failing.
    
    GTCRN 槽位：只声明、未实现。选中它不会报错，而是降级回内置的 DSP 链路。
    """
    说明 = "精修 · GTCRN（极轻量，约 48.2K 参数，适合老机器）"
    对应链路 = "精修"
    requires = ("numpy", "onnxruntime", "soundfile")


@注册("frcrn")
class FRCRN(_未实现):
    """FRCRN slot — declared but not implemented. Selecting it degrades to the built-in DSP chain instead of failing.
    
    FRCRN 槽位：只声明、未实现。选中它不会报错，而是降级回内置的 DSP 链路。
    """
    说明 = "超精修 · FRCRN（高保真，算力要求高）"
    对应链路 = "超精修"
    requires = ("torch",)
