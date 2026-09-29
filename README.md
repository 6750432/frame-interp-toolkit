# DSH-Pet 插帧工具包

给 [dsh-pet 桌宠](https://github.com/MerZlin/dsh-pet-indesktop)的素材做**插帧**与**音频修复**的
第三方工具链。图形界面 + 命令行都有，Windows / Linux / macOS 分系统打包。

> 定位一句话：**带透明的不会丢，带声音的不会没。**
> 桌宠素材是带 alpha 的 webm，普通转码工具会把透明通道吃掉；这个工具只出 webm，
> 并且把音轨原样带走。

**本项目是独立工具链，与上游无隶属关系的第三方作品**，不含上游代码。上游出处与许可见
[`NOTICE.md`](NOTICE.md)。

---

## 它能做什么

### 一、插帧（RIFE）
把 24fps 的桌宠素材插到 48 / 72 / 90 / 120fps。三档预设 + 自定义，
输出帧率、编码线程数、是否走内存盘都可调。

- 17 种输入后缀自适应；音轨按原编码（opus/vorbis）原样复制，aac/mp3 转 opus
- **安全倍数拦截**：插帧倍数超过阈值会拒绝执行 —— 理由是**功耗**，不是画质
- **不会自动降分辨率**，只给文案建议

### 二、音频快修
三种工作模式：`插帧` / `音频`（只修声音）/ `视音`（插帧 + 修音轨再封回视频）。

默认 DSP 链路（全部是 ffmpeg 自带滤镜，零第三方依赖）：

```
去闷 EQ  →  响度标准化（默认 -16 LUFS）  →  剪静音  →  alimiter 兜底
```

EQ 风格分 `语音` / `环境音` 两套；实测同一条素材，语音档只动 0.1 dB、环境音档压 4~8 dB。

### 三、AI 外挂（可选）
`audio_plugin/` 是子进程插件协议（一行 JSON 作业/结果），支持挂外部降噪模型。

| 槽位 | 状态 |
|---|---|
| `dpdfnet2` | ✅ 真跑过（16 kHz 语音增强，CPU 可跑，约 2.7 倍实时） |
| `gtcrn` / `frcrn` | ⚠️ 空壳，选中会**降级回 DSP 链路**，不会崩 |

---

## 快速开始

```bash
cd DSH-Pet-插帧工具包
python3 启动界面.sh          # 图形界面
python3 插帧.py 素材.webm    # 命令行，输出到 output/
```

依赖：`ffmpeg`、`rife-ncnn-vulkan`（插帧）、Python 3。打包脚本会把这些路径写进
`config.json` 的对应键；发布版会**清空**这些键，让用户自己填。

`自检/` 目录里有一键自检，跑完生成 `自检报告.txt`。

---

## 目录

```
DSH-Pet-插帧工具包/        工具本体
  插帧.py                  RIFE 插帧流水线
  audio_fix.py             音频修复：DSP 链路 + 外挂调度（也能当 CLI 跑 --自检）
  audio_plugin/            音频模型插件（子进程 + JSON 协议）
  gui.py / gui_audio.py    图形界面
  自检/                    一键自检脚本
  config.json              设置（发布版里本机路径已清空）
  docs/                    实测数据
DSH-Pet-插帧工具-开发中/    打包脚本与开发期的量测/回归脚本
  打包.py                  按系统打包（会自动裁掉别的系统的启动器）
  打包-开箱即用版.py       组装全内置的 Windows 包
  三模式冒烟.py / 音频回归.py   回归测试
docs/说明书-保姆级教程.txt   面向第一次用的用户
```

---

## 已知限制（诚实交代）

- **macOS 一行没跑过**，也没有 Mac 真机；`一键插帧.command` 是按规范写的，未实测。
- **Windows 侧**只实测过插帧主流程；v0.8 之后新增的黑框/DPI/机械盘检测没在真机跑过。
- **AMD / Intel 显卡无真机**，显卡预检与自动绑独显只在 NVIDIA 上验证过。
- **MP4 输出已暂停**：mp4 的 H.264 装不下 alpha，做出来会丢透明；
  半成品补丁留在 `DSH-Pet-插帧工具-开发中/未完成-MP4支持.patch`。
- 参考数（本机实测，640×360 / 24fps / 10 秒）：48fps 482 帧约 21~26 秒；
  72fps 723 帧约 29~37 秒。**换机器数字会不一样**，别当基准。

---

## 许可与致谢 / License & Credits

本仓库是**第三方独立工具链**，不是上游官方项目。

- **上游根项目：[PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet)**
- **上游移植版（本工具直接服务）：[MerZlin/dsh-pet-indesktop](https://github.com/MerZlin/dsh-pet-indesktop)**

**特别感谢 MerZlin 与 PC2005-cloud** —— 没有这两个项目，就没有这套素材规范可供工具链对齐。

两份上游 MIT 原文**逐字节保留在根目录，版权声明一字未改**：

| 文件 | 内容 |
|---|---|
| [`LICENSE`](LICENSE) | MerZlin / dsh-pet-indesktop 的 MIT 原文 |
| [`LICENSE-UPSTREAM-dsh-pet`](LICENSE-UPSTREAM-dsh-pet) | PC2005-cloud / dsh-pet 的 MIT 原文 |
| [`LICENSE-LOCAL`](LICENSE-LOCAL) | **本仓库自己那部分**的 MIT（`Copyright (c) 2026 BZYS17Mintstar (6750432)`） |

三者的许可条款文本相同（都是 MIT），区别只在版权人与适用范围。
完整的归属划分见 [`NOTICE.md`](NOTICE.md)。
