# 出处与许可说明

- 整理日期：2026-09-14
- 数据规模：26 段 MP4
- 筛选条件：水下视角；人物相对画面横向或纵向运动；排除持续正面迎向相机、纯水面俯拍和无人物空镜。
- 处理方式：从公开视频截取互不重叠的连续时间段，去除音轨，编码为 H.264/yuv420p；未添加水印。
- 详细到片段的起止时间、成品大小和 SHA-256：见 [`manifest.csv`](manifest.csv)。

## 许可提示

- Pexels 素材按 [Pexels License](https://www.pexels.com/license/) 提供，可免费使用和修改，通常无需署名；许可对将素材作为独立库存媒体再次销售或分发设有限制。
- Mixkit 条目 3168 与 43088 的页面标注为 [Mixkit Stock Video Free License](https://mixkit.co/license/#videoFree)。
- 本公开仓库只提供元数据和本地构建脚本，不公开第三方视频二进制，也不授予额外的视频再分发权。
- 来源条款和页面可能更新；使用或发布前应重新核对当时条款。

## 原始来源

| 来源组 | 片段 | 场景 | 平台／作者 | 原始页面 |
|---|---:|---|---|---|
| `pexels_9044173` | 001–003 | 泳池水下，男孩佩戴美人鱼尾横向游过 | Pexels／Kindel Media | [9044173](https://www.pexels.com/video/a-boy-swimming-underwater-with-a-mermaid-tail-9044173/) |
| `pexels_8685953` | 004–005 | 泳池侧下方视角，竞技泳者横向游动 | Pexels／Kindel Media | [8685953](https://www.pexels.com/video/a-male-swimmer-training-in-a-swimming-pool-8685953/) |
| `pexels_4866633` | 006–012 | 开放水域水下侧视，穿潜水服泳者横向游动 | Pexels／Renato Machelett | [4866633](https://www.pexels.com/video/man-swimming-underwater-4866633/) |
| `pexels_6959430` | 013 | 海底低机位，自由潜水者横向游过 | Pexels／Daniel Torobekov | [6959430](https://www.pexels.com/video/man-swimming-underwater-6959430/) |
| `pexels_8685955` | 014 | 泳池底部侧视，多名训练泳者横向游动 | Pexels／Kindel Media | [8685955](https://www.pexels.com/video/slow-motion-video-of-swimmers-underwater-8685955/) |
| `pexels_8685997` | 015–016 | 泳池底部侧视，多泳者沿泳道横向通过 | Pexels／Kindel Media | [8685997](https://www.pexels.com/video/underwater-footage-of-people-swimming-in-a-pool-8685997/) |
| `pexels_37236357` | 017–019 | 竖屏泳池水下侧视，自由潜水者横向游动 | Pexels／Tam Freemanfreemind | [37236357](https://www.pexels.com/video/underwater-freediving-in-a-swimming-pool-37236357/) |
| `mixkit_3168` | 020–021 | 泳池水下近距离侧视，男子横向通过 | Mixkit／页面未署名 | [3168](https://mixkit.co/free-stock-video/man-swimming-in-a-pool-3168/) |
| `mixkit_43088` | 022 | 泳池水下侧视，女子横向游过 | Mixkit／页面未署名 | [43088](https://mixkit.co/free-stock-video/woman-swimming-underwater-43088/) |
| `pexels_8050292` | 023 | 固定泳池水下机位，竞技泳者自然偏移运动 | Pexels／SHVETS production | [8050292](https://www.pexels.com/video/people-swimming-underwater-8050292/) |
| `pexels_13548155` | 024 | 海底固定宽景，潜水者沿右下区域移动 | Pexels／Mohammadreza Dehghanpour | [13548155](https://www.pexels.com/video/scuba-diving-on-sea-bottom-13548155/) |
| `pexels_11194812` | 025 | 海底宽景，多名潜水者在上部和侧边移动 | Pexels／Hirsh Philippe | [11194812](https://www.pexels.com/video/divers-on-bottom-of-sea-11194812/) |
| `pexels_8515873` | 026 | 海底宽景，自由潜水者在下方／右侧移动 | Pexels／ArtHouse Studio | [8515873](https://www.pexels.com/video/a-man-swimming-underwater-8515873/) |

## 质量检查记录

- 26 个本地成品均已用 FFmpeg 完整解码，未发现损坏文件。
- 第 23～26 段仅做时间截取，未做空间裁剪；目标在运动阶段主要位于中央 40%×40% 区域之外。
- 同一来源拆分的片段时间不重叠，但实验划分仍应按 `source_group` 分组，防止同源数据泄漏。

