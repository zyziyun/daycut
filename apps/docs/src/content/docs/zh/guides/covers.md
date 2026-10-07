---
title: 封面和缩略图
description: 按各平台的准确尺寸做封面和缩略图：挑出最好的人脸帧，修图美颜，再把封面放到视频第一帧，信息流裁切也能提前预览。
---

你发的每个平台都会有一张对应尺寸的封面，还能预览这个平台的信息流会怎么裁它。同一张封面还可以替换掉视频开头那一秒没用的画面，让缩略图和第一帧对得上。

## 开始之前

- **剪好的视频**，可选一张人脸照片或几张幻灯片截图。
- **一句标题。** 封面标题最好和脚本开头的钩子是同一句话。
- 跑过 `./install.sh`：它会下载封面工具要用的字体，以及 MediaPipe 的人脸和抠图模型。
- HTML 模板需要 **Chrome、Chromium 或 Edge**（或者 `pip install playwright && playwright install chromium`）。

## 选一种版式

| 版式 | 适合 | 样子 |
|---|---|---|
| **拼贴** | 想展示内容的丰富度，不靠脸 | 四张截图斜向拼贴，加标题和标签 |
| **人脸 + 四宫格** | 个人 IP，脸就是点击率 | 抠出来的人像压在 2×2 的幻灯片上 |
| **左右分栏** | 横版帖子（小红书 4:3、YouTube 16:9），有一句金句或「亲测」角度 | 左边修好的照片，右边深色面板放引语、标题、缩略图和标签 |
| **记笔记封面** | 记笔记风格的口播和课程切片 | 16:9 笔记板，外加一张 4:3 中心裁切 |
| **截图框封面** | 以屏幕内容为主 | 深色底、大字、一张倾斜带边框的截图 |

新号一般用脸更有效，已经有辨识度的号可以多用拼贴。

## 在 Mac 应用里

1. 大多数视频项目都自带封面：口播和 vlog 项目会在收件箱里停在 **选封面**，给出排好序的候选帧和封面文字。
2. 想单独做封面，就在首页描述：哪条视频、发哪些平台、用什么版式。
3. 选一帧、改文字。每个平台的封面文件放在对应视频旁边，信息流裁切预览会告诉你缩略图里还剩什么。

## 用 Claude Code 技能

跟 Claude 说要做封面，技能会按 `workflows/cover` 走：

- **挑帧。** 口播素材会按笑容、睁眼、人脸居中给帧打分（`cover.score_frames`），把最好的几张拼成联系表给你挑。说话中的帧（嘴微张、看镜头）比发呆摆拍的好。
- **修图**在做封面之前：瘦脸、放大眼睛、淡妆预设。

  ```bash
  python3 -m vstudio.retouch face.png face_retouched.png --slim .05 --eye .04 --preset natural
  ```

  预设有 `none`、`natural`、`daily`、`glam`，合照加 `--faces all`。
- **抠人像**给四宫格版式用，会生成棋盘格底图检查有没有白边。
- **一次渲染所有平台尺寸**：

  ```bash
  python3 workflows/cover/scripts/render_cover.py work/cover.html -o work/cover.png \
      --platform xiaohongshu --platform douyin --platform youtube
  ```

### 封面放到第一帧

`workflows/polish` 会把封面放到视频开头一秒的画面上，声音不动，总时长不变：

```bash
python3 workflows/polish/scripts/polish.py export.mp4 -o final.mp4 --cover cover.png --check
```

`--check` 会把第一帧存成 PNG，方便确认第 0 帧就是封面。如果开头一秒本身就是钩子画面，就从钩子里挑一帧当封面。

## 各平台尺寸

| 平台 | 封面 | 信息流显示 |
|---|---|---|
| 小红书（3:4 或 9:16 帖子） | 1080×1440 | 整张 |
| 小红书横版 | 1920×1080 | 中间 4:3 |
| 抖音、TikTok | 1080×1920 | 主页网格：中间 3:4 |
| YouTube Shorts | 1080×1920 | 整张 |
| YouTube | 1280×720，不超过 2 MB | 整张；文字放在时间戳左边 |
| B站 | 1146×717（16:10） | 还会被裁成 4:3 和 16:9 |

其他平台的封面尺寸见[平台参考](/docs/zh/reference/platforms/)。凡是信息流会裁切的地方，导出时都会生成一张 `.feed.jpg` 预览，标题可能被裁掉时会提醒你。

## 值得了解的选项

| 选项 | 默认 | 作用 |
|---|---|---|
| 封面强调色 | 青色 `#2dd4bf` | 拼贴和四宫格模板的颜色（persona 里的 `cover.accent`）。左右分栏版式跟随你的品牌色。 |
| 修图预设 | `natural` | `none`、`natural`、`daily`、`glam`。 |
| 抠图引擎 | MediaPipe | `--engine rvm` 头发更干净；它是 GPL-3.0 授权，只有你选了才会下载。 |
| 视频里封面停留 | 1.0 秒 | 封面替换开头多长的画面（`--cover-sec`）。 |

## 示例指令

- 「给这条视频做个小红书和抖音的封面，用我的脸，挑一帧正在说话、看镜头的。」
- 「拼贴封面，用这场分享里四个不同的瞬间，标题：RAG 难的不是检索。」
- 「小红书横版用左右分栏：左边修过的照片，右边放金句，加一个『亲测』印章。」
- 「封面放到第一帧，再给我一张 2 MB 以内的 YouTube 缩略图。」

## 相关

- [cover 工作流参考](/docs/zh/reference/workflows/cover/) 和 [polish](/docs/zh/reference/workflows/polish/)
- [修图参考](/docs/zh/reference/engine/retouch/)
- [一个母版发多个平台](/docs/zh/guides/multi-platform/)
- [主题和品牌](/docs/zh/concepts/themes/)
- [平台参考](/docs/zh/reference/platforms/)
