# -*- coding: utf-8 -*-
"""演示/自检用假模型 —— 不装任何第三方库，用来验证"外挂通道"本身是通的。

它能干的事：
    · 正常模式：把音频整体调低 3 dB（可辨认的变化）
    · 崩溃模式（参数 crash=true）：直接 os._exit(9)，用来验证主工具的降级是否可靠
    · 卡死模式（参数 hang=秒数）：睡死过去，用来验证超时保护
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from ..base import BaseAudioModel, 注册


@注册("mock")
class MockModel(BaseAudioModel):
    """Zero-dependency mock model used by the tests: volume only, and it can simulate crash / hang to exercise the fallback path.
    
    零依赖的假模型，测试用：只调音量；能用 `crash` / `hang` 模拟崩溃与卡死，专门用来验证降级逻辑。
    """
    requires = ()                                    # 故意零依赖，谁都能跑
    说明 = "演示用假模型（零依赖，只调音量；支持 crash/hang 用于验证降级）"

    def load(self, 参数: dict) -> None:
        self.ffmpeg = str(参数.get("ffmpeg") or shutil.which("ffmpeg") or "ffmpeg")

    def process(self, 输入: Path, 输出: Path, 参数: dict) -> dict:
        if str(参数.get("crash", "")).lower() in ("1", "true", "yes"):
            print("[mock] 故意崩溃", flush=True)
            os._exit(9)                              # 模拟段错误：进程直接没
        if 参数.get("hang"):
            time.sleep(float(参数["hang"]))           # 模拟卡死
        cmd = [self.ffmpeg, "-hide_banner", "-nostdin", "-v", "error",
               "-i", str(输入), "-af", "volume=-3dB", "-y", str(输出)]
        p = subprocess.run(cmd, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if p.returncode != 0:
            raise RuntimeError(f"ffmpeg 失败：{p.stdout.decode('utf-8', 'replace')[:300]}")
        return {"模型处理": "整体 -3 dB"}
