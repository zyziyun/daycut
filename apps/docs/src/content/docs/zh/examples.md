---
title: 示例指令
description: 千剪里好用的说法，按场景整理：口播去气口、只做去口癖、长视频切片、播客遮脸、vlog、讲解视频、批量排期，以及成片的二次修改。
---

跟千剪（Reelfold）说话，就像给剪辑师交代需求。下面这些说法在 Mac 应用的输入框和 Claude Code 技能里都能用。把素材交给它（在应用里拖进来，或者跟 Claude 说文件名），细节按你的情况改。

## 怎么说需求

一句好用的需求讲清三件事：

1. **素材**：「这段口播」「这节 70 分钟的课」「这些航拍和照片」。
2. **成品**：剪几条、每条多长、要加什么（字幕、记笔记面板、封面、发布文案）。
3. **平台**：小红书、抖音、视频号、B站、YouTube Shorts 等。平台决定了画幅、安全区、响度和文案字数，所以一般不用自己报尺寸。

没说的部分，会用你的默认设置（persona 里的偏好）或者从素材本身推断。如果有哪件事没法默认、又会影响结果，比如给谁遮脸、要旁白还是纯音乐，开跑之前它会先问你。

## 口播

<div class="rf-prompts">

| 你想要 | 可以这样说 | 工作流 |
|---|---|---|
| 精剪口播 | 「把这个口播剪一下：去气口、去口头禅和重复，1.1 倍速，加字幕、记笔记、进度条，发小红书」 | [talkinghead](/docs/zh/reference/workflows/talkinghead/) |
| 开头高光预告 | 「开头加 3 句高光预告，关键词弹字，再出一个抖音和 Shorts 版本」 | [talkinghead](/docs/zh/reference/workflows/talkinghead/) |
| 换成精剪风 | 「换成快节奏的精剪风：推镜、弹字、印章、加音效」 | [talkinghead](/docs/zh/reference/workflows/talkinghead/) |
| 修图美颜 | 「帮我磨皮加个淡妆，封面再 P 瘦一点」 | [talkinghead](/docs/zh/reference/workflows/talkinghead/)、[cover](/docs/zh/reference/workflows/cover/) |
| 插 B-roll | 「说到后台数据那里，切到这段录屏，声音别断」 | [talkinghead](/docs/zh/reference/workflows/talkinghead/) |

</div>

## 只去口癖

<div class="rf-prompts">

| 你想要 | 可以这样说 | 工作流 |
|---|---|---|
| 只清理语音 | 「这段录音去气口、去嗯啊和重复，不确定的列给我确认」 | [cleanup](/docs/zh/reference/engine/cleanup/) |
| 剪映导出后再清理 | 「剪映导出的这条再去一下气口，第一帧别黑，响度调好」 | [polish](/docs/zh/reference/workflows/polish/) |
| 轻一点 | 「轻轻处理一下就行：长停顿缩短，换气声留着，别把节奏剪没了」 | [cleanup](/docs/zh/reference/engine/cleanup/) |

</div>

## 长视频、课程和通话

<div class="rf-prompts">

| 你想要 | 可以这样说 | 工作流 |
|---|---|---|
| 课程切成分集 | 「这个 70 分钟的课切成 3 条竖屏短视频，每条一个知识点，代码放大，带封面和发布文案」 | [longform-to-short](/docs/zh/reference/workflows/longform-to-short/) |
| 直播回放竖屏切片 | 「把这场直播切成 10 条竖屏切片，每条一分钟以内，上面加标题条，屏幕内容裁到看得清」 | [longform-to-short](/docs/zh/reference/workflows/longform-to-short/) |
| 剪成课程 | 「把这段录屏剪成课程：去掉浏览器头和书签栏，加章节和字幕，学员变声」 | [longform-to-short](/docs/zh/reference/workflows/longform-to-short/) |
| 播客、通话片段 | 「从这个 Zoom 播客里找一段最有意思的 1 分钟，嘉宾遮脸、名字打码，竖屏」 | [call-clips](/docs/zh/reference/workflows/call-clips/) |
| 从成片里挑一段 | 「把后面关于自媒体的思考单独剪出来发小红书」 | [talkinghead](/docs/zh/reference/workflows/talkinghead/) |

</div>

## 宣传片、文艺片和 vlog

<div class="rf-prompts">

| 你想要 | 可以这样说 | 工作流 |
|---|---|---|
| 高级感宣传片 | 「左右分栏，截图做 3D 卡片加高光，说到那句停 2 秒把 prompt 放大，后面插精选片段 1.1 倍速」 | [promo-recut](/docs/zh/reference/workflows/promo-recut/) |
| 文艺片 | 「用这些展览照片做一个文艺片，纯音乐，分三章，草稿和成品对比、放大镜、胶片质感」 | [photo-story](/docs/zh/reference/workflows/photo-story/) |
| 带旁白的照片故事 | 「这些旅行照片配上这份稿子，用我自己的声音念旁白，9:16」 | [photo-story](/docs/zh/reference/workflows/photo-story/) |
| 卡点快节奏 vlog | 「迪士尼照片和片段剪一个快节奏卡点 vlog，DAY 标签、地点、音效、弹字，9:16」 | [vlog](/docs/zh/reference/workflows/vlog/)（fun） |
| 舒缓 vlog | 「这些航拍剪一个舒缓的 vlog，调色、慢速、配轻音乐」 | [vlog](/docs/zh/reference/workflows/vlog/)（calm） |

</div>

## 讲解视频和 AI 视频

<div class="rf-prompts">

| 你想要 | 可以这样说 | 工作流 |
|---|---|---|
| 讲解视频 | 「做一个 3Blue1Brown 风格的讲解短视频，讲 CUDA 在 GPU 上怎么跑，竖屏，中英双语字幕」 | [explainer](/docs/zh/reference/workflows/explainer/) |
| 从文档出讲解 | 「按这份 PDF 的几个章节，做 5 条讲解短视频」 | [explainer](/docs/zh/reference/workflows/explainer/) |
| AI 短剧 | 「按这个剧本用可灵做 AI 短剧第 3 集，角色和前两集保持一致，预算 200 积分」 | [ai-video](/docs/zh/reference/workflows/ai-video/) |

</div>

## 封面、发布包和多平台

<div class="rf-prompts">

| 你想要 | 可以这样说 | 工作流 |
|---|---|---|
| 发布包 | 「给这条视频做封面、标题、正文和标签，小红书 + B站」 | [cover](/docs/zh/reference/workflows/cover/)、[polish](/docs/zh/reference/workflows/polish/) |
| 只做封面 | 「从这条视频里挑一帧做 B站封面，两行大标题」 | [cover](/docs/zh/reference/workflows/cover/) |
| 一条发多个平台 | 「同一条导出小红书 3:4、抖音、YouTube Shorts，各自安全区和响度」 | [export](/docs/zh/reference/cli/#vstudioexport) |
| 先写稿 | 「帮我写一篇 90 秒的口播稿，发视频号，再给我做个难读词的跟读练习」 | [preproduction](/docs/zh/reference/workflows/preproduction/) |

</div>

## 批量和排期

<div class="rf-prompts">

| 你想要 | 可以这样说 | 工作流 |
|---|---|---|
| 一整批 | 「这个文件夹里 30 条口播，全部去气口出成片，发抖音和小红书，只把没过质检的拿给我看」 | [batch](/docs/zh/reference/workflows/batch/) |
| 一条录像发一周 | 「这场直播切 14 条，每条 60 秒内，打包成抖音和视频号的发布包」 | [batch](/docs/zh/reference/workflows/batch/) |
| 排期 | 「从周一开始每天发两条，中午 12 点和晚上 7 点」 | [batch](/docs/zh/reference/workflows/batch/) |

</div>

千剪不会替你发。排期给你的是一张发布日历和打包好的文件；到发的时候，Mac 应用帮你填好上传页，由你按下发布。见 [排期与发布](/docs/zh/guides/scheduling-publishing/)。

## 成片二次修改

每条做好的成片都能用一句话再改。在 Mac 应用里，可以先在时间线上选中一段或选中一句字幕，这时「这段」「这里」就指你选中的部分。

<div class="rf-prompts">

| 你想要 | 可以这样说 | 工作流 |
|---|---|---|
| 掐头、加速 | 「开头剪掉两秒，整体 1.2 倍速」 | [output edit](/docs/zh/reference/engine/output-edit/) |
| 剪掉一段 | 「剪掉这段」（先选中） | [output edit](/docs/zh/reference/engine/output-edit/) |
| 改字幕 | 「字幕大一点，关键词标黄」 | [output edit](/docs/zh/reference/engine/output-edit/) |
| 换整体风格 | 「换成小红书风格的主题」 | [output edit](/docs/zh/reference/engine/output-edit/) |
| 加效果 | 「0:12 说到『三个步骤』的时候弹个大字，0:40 加一张章节卡」 | [output edit](/docs/zh/reference/engine/output-edit/) |
| 再出一个尺寸 | 「再出一个 16:9 的 B站版本」 | [output edit](/docs/zh/reference/engine/output-edit/) |
| 只撤回一步 | 「把加音乐那一步撤掉，后面改的都留着」 | [output edit](/docs/zh/reference/engine/output-edit/) |
| 所有成片一起改 | 「所有切片都去掉系列标签」 | [output edit](/docs/zh/reference/engine/output-edit/) |

</div>

## 后续修改的小技巧

- **开跑前改方案。** 短短一句就够：「只要小红书」「每条 60 秒内」「5 条」「1.2 倍」「原速」「英文」「剪干净一点」「轻一点」「遮脸」「不遮脸」「加 hook」「不要 hook」「横屏」「竖屏」「卡点」「舒缓」。你没提到的部分保持不变。
- **成片出来后一次只改一件事。** 每次修改都是一步，可以单独撤销，方便对比和回退。
- **指明位置。** 说时间（「0:12 那里」），引用原话（「说到『三个步骤』那句」），或者在应用里直接选中。
- **原视频里烧进去的字**（水印、原素材自带的字幕）没法靠修改去掉或换样式。遇到这种情况，千剪会告诉你需要从素材重新渲染。
- **说清哪些别动。** 「字幕保持不变，只换封面」，能避免改到你不想改的地方。

## 相关页面

- [第一个项目](/docs/zh/start/first-project/)
- [配方](/docs/zh/concepts/recipes/)
- [成片二次编辑](/docs/zh/concepts/output-edits/)
- [参考总览](/docs/zh/reference/)
