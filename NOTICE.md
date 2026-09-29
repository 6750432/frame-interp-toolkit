# 版权与来源声明 / Notices

本仓库是 **dsh-pet 桌宠生态的第三方工具链**，与上游两个项目均无隶属关系。
上游许可原文**逐字节保留，版权声明一字未改**。

---

## 一、上游链条

```
PC2005-cloud/dsh-pet            （最初的桌宠项目）
        └── MerZlin/dsh-pet-indesktop   （三平台移植版）
                └── 本仓库（工具链，服务于上面的桌宠素材）
```

| 项目 | 仓库 | 版权行 | 许可 |
|---|---|---|---|
| 上游根项目 | [PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet) | `Copyright (c) 2026 PC2005-cloud` | MIT |
| 移植版（本工具直接服务） | [MerZlin/dsh-pet-indesktop](https://github.com/MerZlin/dsh-pet-indesktop) | `Copyright (c) 2026 Merzlin` | MIT |

两份原文分别放在：

- [`LICENSE`](LICENSE) —— MerZlin / dsh-pet-indesktop 的 MIT 原文（**逐字节**）
- [`LICENSE-UPSTREAM-dsh-pet`](LICENSE-UPSTREAM-dsh-pet) —— PC2005-cloud / dsh-pet 的 MIT 原文（**逐字节**）

## 二、本仓库自己的部分

- 版权：`Copyright (c) 2026 BZYS17Mintstar (6750432)`
- 生成说明：`Generated with the assistance of AI (DeepSeek V4), guided by human architectural intuition.`
- 许可：MIT —— 全文见 [`LICENSE-LOCAL`](LICENSE-LOCAL)
- 范围：`DSH-Pet-插帧工具包/`、`DSH-Pet-插帧工具-开发中/` 下的全部源码、脚本与文档。

---

## 三、需要说清楚的一点

**本仓库不含上游代码。** 它是一个**独立编写的工具链**：读取 dsh-pet 的素材（`.webm`），
做插帧与音频修复，再写回符合该桌宠规范的素材。

根目录之所以放上游的 MIT 原文，是为了：
1. 满足上游 MIT「版权声明与许可声明须随本软件的所有副本一并提供」的要求；
2. 把「致敬谁、依据什么规范」写清楚，而不是只在 README 里提一句。

如果你要用本工具处理上游素材，**请同时遵守上游两份 MIT**（条款文本与本项目相同）。

## 四、一句话

用本工具 → 遵守 [`LICENSE-LOCAL`](LICENSE-LOCAL)。
分发自上游的素材 → 遵守 [`LICENSE`](LICENSE) 与 [`LICENSE-UPSTREAM-dsh-pet`](LICENSE-UPSTREAM-dsh-pet)。
三者都是 MIT。
