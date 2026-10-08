---
title: 水印
description: 给导出的每个视频加上你的账号名、你的 logo 或自动生成的 logo，放在各平台的安全区内，并避开字幕。
---

设置一次，之后每次导出都会带上你的水印：可以是干净的账号名文字、你自己的 PNG logo，或者千剪根据账号名生成的 logo。它放在你选的角落，在每个平台的安全区之内、字幕上方，平台按钮和字幕都不会挡住它。

没设置之前不会加任何水印。单个视频也可以不加。

## 在 Mac 应用里

1. 打开 **设置 › 水印**。
2. 填上你的账号名（比如 `@你的账号`）。填好后水印就设置好了，**默认给每个视频加水印** 会一起打开。
3. 选择用什么：
   - **账号名**：直接用干净的文字。
   - **生成 logo**：点 **生成 logo**，再选样式：**胶囊**（深色圆角底）、**首字母**（圆形里放首字母，旁边是账号名）或 **纯文字**。在你的 Mac 上本地生成，不调用任何在线服务。
   - **我的 logo**：把 PNG 拖进框里，或点 **选择文件**。透明背景效果最好。
4. 选 **角落**、**大小** 和 **不透明度**。两张预览（竖屏 9:16 和横屏 16:9）由引擎绘制，和导出时的位置完全一样。
5. 在 **平台** 里点一下某个平台，这个平台的视频就不加水印。

某一个视频不想加：打开这个片段，点 **导出**，导出前取消勾选 **水印**。这个开关默认跟随你的设置。

## 用 Claude Code 技能或终端

设置保存在 `~/.config/vstudio/watermark.json`（或 `$VSTUDIO_HOME/watermark.json`），应用和技能共用。也可以在 `persona.local.yaml` 的 `watermark:` 下写默认值；设置文件优先。

```bash
export PYTHONPATH="$PWD/lib:$PYTHONPATH"
python3 -m vstudio.watermark set --text @你的账号 --default on
python3 -m vstudio.watermark set --kind generate --style monogram --position top-left
python3 -m vstudio.watermark set --image ~/logo.png          # 你自己的 logo（会复制一份进来）
python3 -m vstudio.watermark set --platform douyin=off       # 抖音永远不加
python3 -m vstudio.watermark preview --aspect 9:16 --out preview.jpg
python3 -m vstudio.watermark show
```

所有导出路径都会加：`vstudio.export`（所有批量配方、长视频切片、polish、vlog）和应用里的最终导出。单次导出可以关掉：

- `python3 -m vstudio.export master.mp4 --platforms tiktok --watermark off`
- 批量任务或 spec 里写 `watermark: false`
- `python3 -m vstudio.project output render --quality final --watermark off`

## 位置规则

| 设置 | 默认 | 作用 |
|---|---|---|
| 角落 | 右下 | 在平台安全区内（避开点赞 / 评论那一列和平台自己的字幕栏）。下方的角落会上移到字幕带上面。 |
| 大小 | 24 % | 水印放进边长为画面短边这个比例的正方形里，9:16 和 16:9 上看起来一样大。 |
| 不透明度 | 80 % | |
| 边距 | 2 % | 安全区内再留出的距离。 |

已经带水印的视频（引擎导出的成片）再次编辑、重新导出时不会再叠一层。剪辑器里的预览不加水印，水印只加在最终导出上。

## 相关

- [一个母版，多个平台](/docs/zh/guides/multi-platform/)
- [封面和缩略图](/docs/zh/guides/covers/)
- [Persona 参考](/docs/zh/reference/persona/)
- [CLI 参考](/docs/zh/reference/cli/#vstudiowatermark)
