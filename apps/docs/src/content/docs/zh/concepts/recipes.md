---
title: 配方
description: 千剪的每个工作流都是一份配方清单。一张表看懂 13 个工作流各做什么，以及千剪怎样根据你的一句话和丢进来的视频、照片、文档，自动挑出一个或几个合适的配方，生成一份可以继续用一句话修改的计划。
---

配方就是把一个工作流写成文字：它需要什么素材、接受哪些设置、按什么步骤跑、在哪里停下来问你、最后产出什么。千剪（Reelfold）的每个工作流都有一份，放在 `workflows/<名字>/recipe.yaml`。

## 为什么重要

你不需要记住任何配方名。说清楚要做什么（「把后面讲自媒体的那段单独剪出来发小红书」），把素材丢进来就行。千剪会读你的话和素材，挑出一个或几个配方，先给你一份能改的计划，确认了才开始跑。所有配方格式相同，所以 Mac App 和技能可以用同一种方式运行、暂停、续跑和审片。

## 13 个工作流

| 工作流 | 做出什么 |
|---|---|
| [`talkinghead`](/docs/zh/reference/workflows/talkinghead/) | 口播精剪：去气口、口头禅和重复，加 hook 冷开场、字幕、封面，导出各平台版本 |
| [`promo-recut`](/docs/zh/reference/workflows/promo-recut/) | 宣传片：口播加截图，左右分屏、3D 截图卡片、定格放大、精选插片 |
| [`longform-to-short`](/docs/zh/reference/workflows/longform-to-short/) | 长视频切片：从长录像切出竖屏短视频，或剪成 16:9 课程加分集（课程变体） |
| [`call-clips`](/docs/zh/reference/workflows/call-clips/) | 通话、访谈、播客截取片段，嘉宾遮脸（贴纸跟踪），名字条打码 |
| [`photo-story`](/docs/zh/reference/workflows/photo-story/) | 文艺片：照片和短片配旁白或卡点音乐 |
| [`vlog`](/docs/zh/reference/workflows/vlog/) | 旅行 vlog，舒缓或卡点快节奏，调色、转场、配乐 |
| [`explainer`](/docs/zh/reference/workflows/explainer/) | 3Blue1Brown 风格的讲解动画，AI 配音加双语字幕 |
| [`polish`](/docs/zh/reference/workflows/polish/) | 其他剪辑软件导出后的收尾：首帧换封面、响度、可选加速 |
| [`cover`](/docs/zh/reference/workflows/cover/) | 封面和缩略图，覆盖各平台尺寸 |
| [`slides`](/docs/zh/reference/workflows/slides/) | 给竖屏视频用的方形或全屏幻灯片 |
| [`preproduction`](/docs/zh/reference/workflows/preproduction/) | 口播稿（检查字数和节奏），可选发音跟读练习 |
| [`ai-video`](/docs/zh/reference/workflows/ai-video/) | AI 生成视频（可灵、即梦 Seedance、海螺 MiniMax）：分镜、prompt、积分预算、选镜头、组装 |
| [`batch`](/docs/zh/reference/workflows/batch/) | 批量的引擎看板：试点、全量、例外审片、交付 |

`longform-to-short` 有两份清单（`recipe.yaml` 和 `recipe.course.yaml`），所以配方文件一共 14 份。

## 千剪怎么挑配方

在你的一句话和项目之间，有一步叫「接单」（intake）：

1. **盘点素材。** 看你丢进来的每个文件：时长、横竖屏、有没有人声、有没有人脸、是不是录屏、有没有烧录字幕、文档的标题结构。每个文件会被标上一个角色，比如 `lecture`（讲课）、`talking-head`（口播）、`call`（通话）、`photo`、`script`、`finished-edit`（成片）。素材只读不写，旁边不会多出任何文件。
2. **出计划。** 你选的 AI 模型拿到你的要求、素材摘要和配方目录，提出一个或几个项目。引擎再按配方清单逐项校验配方、输入和参数。配方永远不会被凭空编出来，不合法的部分会被去掉并给出提示。
3. **规则兜底。** 没配置模型或者模型出错时，规则规划器根据常用说法和素材角色生成计划。
4. **修改并应用。** 你可以接着用一句话改（「只发小红书」「每条 60 秒内」），也可以直接改计划。应用后就会建好项目文件夹，可以开始试点。

你在话里明确说的永远优先：平台、条数、倍速、「把嘉宾的脸遮一下」。

### 混合计划和串联

一句话可以生成几个项目。比如一个课程文件夹，可能同时变成长视频切片、一条讲解视频和几份口播稿；同一份计划里的项目归在一个系列下，显示在一起。工作流也可以前后串起来，比如 `preproduction` → 录制 → `talkinghead` → `cover` → `polish`。

## 相关

- [项目](/docs/zh/concepts/projects/)
- [批量与审片](/docs/zh/concepts/batch-review/)
- [接单引擎参考](/docs/zh/reference/engine/intake/)
- [参考总览](/docs/zh/reference/)
