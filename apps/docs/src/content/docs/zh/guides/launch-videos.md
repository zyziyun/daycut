---
title: 给你的产品做发布视频
description: 用产品的一次发布，做出演示视频、README 动图、每个功能一条短片、Product Hunt 配图、中英文发布文案和发布排期。
---

一次发布或更新要用到的东西，全部用真实产品录出来：30–60 秒的演示视频（16:9、9:16、1:1，动态字幕，镜头推近到每一次点击，片尾 Logo，轻背景音），README 用的 15 秒循环动图，每个功能一条 10–20 秒短片（X、LinkedIn、Shorts、TikTok、小红书），Product Hunt 配图和 OG 图，每个平台的中英文文案，以及一份发布排期建议。不会替你发布任何内容。

## 开始之前

- **产品**：名字、一句话介绍、官网。
- **这次改了什么**：CHANGELOG 的一节、一段 git 提交范围（`feat:`、`fix:` 这类 Conventional Commits 会变成功能点，杂务和 CI 不算），或者粘贴的更新说明。
- **要录的东西**：网页应用的地址或一个 Electron 应用，里面放可以公开的示例数据（不要真名、邮箱、账号名或别人的脸）。已有的截图或录屏也可以用。
- **品牌**：Logo、图标、一个强调色，字体可选（任意 OFL 字体文件）。

## 在 Mac 应用里

1. 在首页点「给我的应用做发布视频」，或者直接描述（「用这份更新日志给 v1.4 做一套发布素材」），把更新日志和 Logo 拖进来。
2. **产品、品牌与功能**。从草稿里挑 3–6 个功能，每个写一句屏幕字幕，用【】标出要高亮的词；再写录制脚本：每个功能点哪里、输入什么。
3. 项目会录制产品、渲染所有视频、做配图、写文案、排出发布计划。每条视频先过首轮自检再给你看。
4. **审片发布**。读 `COPY.md`，看视频，自己发布。

## 用 Claude Code 技能

把更新日志交给 Claude，说清要发布什么。技能按 `workflows/launch-kit` 来做，所有设置都在一个 `launch.config.yaml` 里：

```bash
LK="python3 $VSTUDIO/workflows/launch-kit/scripts/launch_kit.py"
$LK features launch.config.yaml     # 从更新日志起草功能列表
$LK capture launch.config.yaml      # 用 Playwright 录制产品
$LK all launch.config.yaml          # 渲染、配图、文案、排期、首轮自检
```

录制时产品以 2 倍分辨率运行，光标平滑移动，并记录每个镜头里每次点击发生的时间和位置。镜头据此推近到操作处，两次操作之间再拉回。

## 产出

| 文件夹 | 内容 |
|---|---|
| `demo/` | 16:9、9:16、1:1 演示视频（加上 `zh` 还有中文字幕的 16:9 和 9:16），每条带封面 |
| `readme/` | 无缝循环的 15 秒 MP4 和 GIF |
| `clips/` | 每个功能一条：1:1 给 X 和 LinkedIn，9:16 给 Shorts、TikTok、Reels 和小红书 |
| `stills/` | Product Hunt 配图（1270×760，含首图）和 1200×630 OG 图 |
| `copy/` | `COPY.md`：Product Hunt 字段、发布帖和每条短片的文案，按平台分中英文 |
| `schedule/` | 发布当天各平台发演示视频，之后每个工作日发一条功能短片 |

## 常用选项

| 选项 | 默认 | 作用 |
|---|---|---|
| `languages` | `[en]` | 加上 `zh` 会出中文字幕版和中文文案。 |
| `demo.max_seconds` | 60 | 超长时压缩每个场景，但每个不少于 4 秒。 |
| `brand.theme` | editorial | 品牌色所依托的主题：纸色、墨色和一个强调色。 |
| `music` | auto | 默认用内置曲库生成的背景音（可随意使用）。也可以写情绪、`none`，或自己的曲子（必须写明授权）。 |
| `voiceover` | 关 | AI 配音，画面上会标注「AI 配音」。 |
| `schedule.accounts` | 无 | 配合 `schedule --apply`，把排期作为待发帖子放进发布日历。 |

平台一律国际平台在前，中文平台在后。

## 示例指令

- 「用 CHANGELOG.md 给我的应用 v1.4 做一套发布素材，录 localhost:3000 上的网页版。」
- 「演示视频只放三个功能，控制在 40 秒以内。」
- 「加上中文字幕和小红书、B站的文案。」
- 「同步那一幕的字幕太长了，缩短一下，只重渲那一条短片。」

## 相关

- [宣传片二剪](/docs/zh/guides/promo-recut/)：口播介绍自己的作品
- [多平台导出](/docs/zh/guides/multi-platform/)
- [排期与发布](/docs/zh/guides/scheduling-publishing/)
- [主题](/docs/zh/concepts/themes/)
- [launch-kit 工作流参考](/docs/zh/reference/workflows/launch-kit/)
