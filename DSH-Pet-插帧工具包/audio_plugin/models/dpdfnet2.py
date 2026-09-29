#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DPDFNet-2 真实实现（精修档）

模型：Ceva-IP/DPDFNet 的 dpdfnet2（16 kHz，2.49M 参数，ONNX 9.8 MB，CPU 可跑）
依赖：numpy / onnxruntime / librosa / soundfile（都在独立 venv 里，主工具不受影响）

⚠️ 重要前提（写在最前面，免得用错）：**这是语音增强模型**，训练目标是"留下人说话、
去掉别的"。给音乐 / 环境音 / 助眠声场用它，它会把"内容"当成噪声压掉 —— 
所以工具里的链路可以自由组合，用哪一档由你决定；拿它处理非语音素材属实验性质。

约定：第三方库只在 load() 里 import（没装依赖的机器也能 import 本模块问"可用吗"）。
"""

from __future__ import annotations

from pathlib import Path

from ..base import BaseAudioModel, 注册


@注册("dpdfnet2")
class DPDFNet2(BaseAudioModel):
    """Adapter for the DPDFNet-2 speech-enhancement model (16 kHz, ONNX Runtime, runs on CPU).
    
    DPDFNet-2 语音增强模型的适配层（16 kHz，ONNX Runtime，CPU 可跑）。
    """
    requires = ("numpy", "onnxruntime", "librosa", "soundfile")
    说明 = "精修 · DPDFNet-2（16kHz 均衡档，语音增强；CPU 可跑）"

    def load(self, 参数: dict) -> None:
        import dpdfnet                      # 延迟 import：这里开始才要求依赖存在
        self._dpdfnet = dpdfnet
        # 衰减上限：越高降噪越狠（离线场景才允许调大）。默认给 12 dB 比较保守。
        self.attn_limit_db = float(参数.get("attn_limit_db") or 12.0)
        # 模型名允许配置覆盖，方便以后换 baseline / dpdfnet4 / 48k 档
        self.模型名 = str(参数.get("模型") or "dpdfnet2")

    def process(self, 输入: Path, 输出: Path, 参数: dict) -> dict:
        import numpy as np
        import soundfile as sf

        数据, 采样率 = sf.read(str(输入), always_2d=True, dtype="float32")
        声道数 = int(数据.shape[1])
        结果 = np.zeros_like(数据)
        for ch in range(声道数):
            # 逐声道跑（保住立体声，不用先混成单声道丢信息）
            结果[:, ch] = self._dpdfnet.enhance(
                 np.ascontiguousarray(数据[:, ch]),
                sample_rate=int(采样率),
                model=self.模型名,
                attn_limit_db=self.attn_limit_db,
            )
        sf.write(str(输出), 结果, int(采样率), subtype="PCM_16")
        return {
            "模型": self.模型名,
            "输入采样率": int(采样率),
            "声道": 声道数,
            "衰减上限dB": self.attn_limit_db,
            "时长秒": round(len(结果) / float(采样率), 2),
        }
