---
title: 参考总览
description: 千剪参考文档各页的内容：命令行、persona 配置项、平台规格、特效与主题、字幕规则、13 个工作流和引擎说明。
---

参考部分是指南之下更细的一层：每条命令、每个配置项、每个平台的数值和每个工作流的操作手册。这些页面由 [千剪（Reelfold）仓库](https://github.com/zyziyun/reelfold) 里的文件自动生成（引擎自带的平台配置、特效目录、各工作流的 `WORKFLOW.md` 和 `references/` 下的说明），所以和代码保持一致。参考页目前只有英文版。

刚开始用的话，先看 [使用指南](/docs/zh/guides/talking-head/) 和 [示例指令](/docs/zh/examples/)；需要查具体数值或参数时再来这里。

## 基础参考

| 页面 | 内容 |
|---|---|
| [命令行](/docs/zh/reference/cli/) | 引擎命令（`python -m vstudio.*`）：intake、project、batch、cleanup、export、reframe、platform、effects、llm、retouch |
| [persona.yaml 选项](/docs/zh/reference/persona/) | `persona.local.yaml` 的全部选项：语速、响度、品牌色和主题、平台覆盖、标签、文案语气、术语纠错、字体、AI 分配 |
| [平台规格](/docs/zh/reference/platforms/) | 每个平台的配置：画幅、封面尺寸、时长、标题字数、响度 |
| [特效与主题](/docs/zh/reference/effects/) | 特效目录、每个特效由哪些渲染器支持，以及设计主题 |
| [字幕规则](/docs/zh/reference/captions/) | 字幕、卡片和发布文案的规则：人名地名核对、每行长度、强调和对比度 |
| [提示信息与错误码](/docs/zh/reference/messages/) | 引擎每条提示的代码、文字和出现的位置 |

## 工作流

每个工作流既是技能遵循的操作手册，也是 Mac 应用运行的配方。

| 工作流 | 把……做成…… |
|---|---|
| [talkinghead](/docs/zh/reference/workflows/talkinghead/) | 口播素材做成紧凑的带字幕短视频：去口癖、加速、开头预告、记笔记面板、修图、封面、发布文案 |
| [promo-recut](/docs/zh/reference/workflows/promo-recut/) | 口播加截图、链接或另一段视频，做成高级感宣传片：左右分栏、高亮卡片 |
| [longform-to-short](/docs/zh/reference/workflows/longform-to-short/) | 课程、讲座、直播回放剪成课程视频，或者切成分集、竖屏切片 |
| [call-clips](/docs/zh/reference/workflows/call-clips/) | 通话、访谈、播客剪成片段，可遮脸、名字打码 |
| [photo-story](/docs/zh/reference/workflows/photo-story/) | 照片加旁白稿（或纯音乐）做成特效丰富的故事短片 |
| [vlog](/docs/zh/reference/workflows/vlog/) | 空镜素材剪成舒缓调色的 vlog，或快节奏卡点 vlog |
| [explainer](/docs/zh/reference/workflows/explainer/) | 一个主题做成 3Blue1Brown 风格的动画讲解，AI 配音、双语字幕 |
| [polish](/docs/zh/reference/workflows/polish/) | 已导出的成片收尾：封面帧、响度、加速，可选去气口 |
| [ai-video](/docs/zh/reference/workflows/ai-video/) | 剧本或创意用 AI 生成视频（可灵、Seedance、MiniMax），控制积分预算 |
| [cover](/docs/zh/reference/workflows/cover/) | 按各平台尺寸做封面和缩略图 |
| [slides](/docs/zh/reference/workflows/slides/) | 给竖屏视频用的方形或全屏幻灯片 |
| [preproduction](/docs/zh/reference/workflows/preproduction/) | 写口播稿、按平台检查稿子、发音跟读练习 |
| [batch](/docs/zh/reference/workflows/batch/) | 一次做很多条：方案、试看、并行跑、自动质检、审片、发布包 |

## 引擎说明

关于共享引擎如何工作的深入说明。写脚本调用引擎、排查结果或参与开发时有用。

| 页面 | 主题 |
|---|---|
| [Intake](/docs/zh/reference/engine/intake/) | 一句需求加一堆素材，怎么变成方案 |
| [Projects](/docs/zh/reference/engine/projects/) | 配方、条目、确认点、收件箱、系列和发布日历 |
| [Batch](/docs/zh/reference/engine/batch/) | 批量规格、任务列表、调度、质检关卡、审片和打包 |
| [去口癖](/docs/zh/reference/engine/cleanup/) | 气口、口头禅、重复、重录：检测、审阅回复、复核 |
| [成片二次编辑](/docs/zh/reference/engine/output-edit/) | 对做好的成片再编辑：操作、AI 修改、撤销和单步撤回 |
| [AI 服务](/docs/zh/reference/engine/providers/) | 每项 AI 工作分给 API、本地模型，或你的 Claude Code / Codex 登录 |
| [发布](/docs/zh/reference/engine/publishing/) | 一条帖子怎么发到各个平台，以及为什么从不自动发布 |
| [风格规则](/docs/zh/reference/engine/style-rules/) | 标题条、字幕、笔记和卡片背后的设计主题 |
| [审美检查清单](/docs/zh/reference/engine/aesthetics/) | 交片前对每条成片要过的检查项 |
| [声音](/docs/zh/reference/engine/sound/) | 节拍、音效摆放和音量 |
| [修图](/docs/zh/reference/engine/retouch/) | 封面和视频的磨皮、妆容和塑形 |
| [短视频 SOP](/docs/zh/reference/engine/sop-short-video/) | 一条口播短视频从选题到发布的完整流程 |
| [添加特效](/docs/zh/reference/engine/adding-effects/) | 往目录里加一个特效，以及在不同渲染器之间移植 |
| [实测记录](/docs/zh/reference/engine/validation/) | 在真实素材上测过什么，以及已知的限制 |

## 相关页面

- [千剪是什么](/docs/zh/start/what-is-reelfold/)
- [示例指令](/docs/zh/examples/)
- [参与贡献](/docs/zh/contributing/)
