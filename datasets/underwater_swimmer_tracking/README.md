# 水下横向泳者跟踪数据集

本目录描述一套面向水下画面增强与运动目标跟踪实验的 26 段视频数据集。筛选重点是：水下视角、人物相对画面横向或纵向移动、避免持续正面迎向相机，并包含目标在运动过程中明显偏离画面中心的样本。

## 数据概况

- 26 段 MP4，共约 435.6 MiB。
- 15 段泳池素材，11 段开放水域素材。
- 4 段自然偏移样本：目标在运动阶段主要位于画面中央区域之外，且未通过空间裁剪人为制造偏移。
- 17～19 为竖屏，其余为横屏。
- 同一原视频拆分的片段时间互不重叠；训练/验证/测试划分时必须按 `source_group` 分组，避免同源泄漏。

逐段元数据、来源、时间范围和成品校验值见 [`manifest.csv`](manifest.csv)，完整中文出处说明见 [`PROVENANCE_AND_LICENSES.md`](PROVENANCE_AND_LICENSES.md)。

## 获取方法

出于上游平台对“独立素材再分发”的限制，本公开仓库不提交第三方视频二进制。请先阅读并接受各来源页面的许可，再在本机运行：

```powershell
cd datasets/underwater_swimmer_tracking
powershell -ExecutionPolicy Bypass -File .\build_dataset.ps1
```

依赖：`yt-dlp`、FFmpeg。脚本会优先使用 PATH 中的 `ffmpeg`；若当前 Python 安装了 `imageio-ffmpeg`，也会尝试使用其内置程序。网页结构或上游文件变化可能导致下载失败，亦可能使重新编码文件与清单中的历史 SHA-256 不完全相同。

构建后可运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\verify_dataset.ps1
```

## 推荐实验划分

不要随机按片段划分。以 `source_group` 为最小单位划分数据，否则同一长视频的相邻片段会同时进入训练集和测试集。`natural_offset=true` 的 4 段适合单独报告偏移目标跟踪指标。

## 许可边界

本仓库中的清单、说明和构建脚本采用仓库自身许可（如有）；视频仍受各自来源平台许可约束。本目录不授予对视频本体的额外再分发权。使用者应以来源页面当时的许可条款为准。
