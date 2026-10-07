---
title: 千剪是什么
description: 千剪（Reelfold）是免费开源、在本机运行的视频工具：一条素材剪成多条成片，按各个平台的规格分别导出。这里介绍它怎么工作、适合谁。
---

千剪（Reelfold）把一条素材剪成你这一周要发的一组短视频。你用大白话说想做什么，把素材拖进来；千剪规划切片、在你自己的 Mac 上剪辑、自动检查每个文件，只把需要你看的地方拿给你。每个平台各有一份成片、封面、标题、正文和标签。

千剪免费、MIT 协议、完全开源，代码在 [github.com/zyziyun/reelfold](https://github.com/zyziyun/reelfold)。

## 两种用法

两种形态跑的是同一个引擎，在一边好用的做法，换到另一边也一样。

| | 千剪 Mac 应用 | Claude Code 技能 |
|---|---|---|
| 是什么 | 桌面应用（`apps/desk`，基于 Electron） | 把引擎做成 [Claude Code](https://claude.com/claude-code) 的技能（仓库根目录） |
| 怎么下指令 | 首页的输入框：「今天要做什么？」 | 在终端里直接跟 Claude 说 |
| 适合 | 看板式批量、审片网格、辅助发布 | 在素材文件夹里干活、写脚本、一次性的剪辑 |
| 平台 | Apple 芯片的 macOS（Windows 版之后再出） | 能跑 Claude Code、Python 3.10+ 和 ffmpeg 的地方 |
| 安装 | [安装 Mac 应用](/docs/zh/start/install-mac/) | [安装技能](/docs/zh/start/install-skill/) |

技能里由 `SKILL.md` 把每个请求分派到对应的工作流（`workflows/<名称>/WORKFLOW.md`），工作流带着测过的脚本和共享的 Python 库 `vstudio`。

## 一次任务怎么走

1. **说需求。** 说清楚要做什么，加上素材：一段口播、一节 70 分钟的课、一文件夹旅行素材、一份脚本都行。比如：「把这节课切成 10 条竖屏切片，发抖音和小红书，每条一分钟以内」。
2. **出方案。** 千剪读完素材，给出方案：用哪个工作流、切几条、发哪些平台、大概多久、可能花多少钱。开跑之前，直接用一句话改，比如「只要 3 条」「不要 9:16」。
3. **批量剪。** 在你的 Mac 上并行跑。先出一条试看，风格确认了再做剩下的。
4. **审片。** 每个文件都会自动质检（漏字、画面卡住、响度、时长）。你只看被标出来的问题，以及该你拍板的事：哪些口头禅要删、用哪个开头、选哪张封面。
5. **发布。** 发布是辅助式的：Mac 应用在内置浏览器里打开平台自己的上传页，把视频和文案填好，由你按下发布。千剪从不自己发。

每一步的细节见：[项目](/docs/zh/concepts/projects/)、[批量与审片](/docs/zh/concepts/batch-review/)、[发布](/docs/zh/concepts/publishing/)。

## 适合谁

- **批量更新的创作者**：录一次，发一周，每条都按平台要求的尺寸、时长和响度出片。
- **播客和访谈**：一场长对话剪出多条切片，需要时给嘉宾遮脸、名字打码。
- **讲课和做课的人**：把课程、直播回放切成竖屏切片或分集。
- **口播创作者**：去气口、去口头禅和重复，加字幕、记笔记面板，配好封面。
- **工作室**：多个客户的批次并排跑，每个客户的风格和术语表各管各的。

## 哪些在本机运行

转写、剪辑、特效、渲染和质检都在你的 Mac 上完成。AI 用你自己的：已登录的 Claude Code 或 Codex CLI（不需要 API key）、API key（Anthropic、OpenAI、DeepSeek、通义千问、Kimi、智谱 GLM、OpenRouter、Gemini、ElevenLabs），或者本地模型（Ollama、LM Studio、vLLM、llama.cpp、本地 whisper）。

用到 AI 时，发给模型的只有文字（逐字稿、字幕和标题），不会上传视频或音频。内部测试里，一节 72 分钟的课剪成 24 条、每条 4 个平台，共 96 个文件，AI API 费用 0.73 美元，平均每条约 0.03 美元。详见 [AI 服务](/docs/zh/concepts/ai-providers/) 和 [隐私](/docs/zh/concepts/privacy/)。

## 以前叫 video-studio 和日剪

千剪是这个项目的新名字。开源技能和引擎以前叫 **video-studio**，桌面应用以前叫 **Daycut**（日剪）。为了让已有的安装继续能用，有几处名字没变：

- Claude Code 技能仍叫 `video-studio`，安装在 `~/.claude/skills/video-studio`
- Python 包仍叫 `vstudio`
- 只有仓库地址换成了 `github.com/zyziyun/reelfold`

## 相关页面

- [安装 Mac 应用](/docs/zh/start/install-mac/)
- [安装 Claude Code 技能](/docs/zh/start/install-skill/)
- [第一个项目](/docs/zh/start/first-project/)
- [示例指令](/docs/zh/examples/)
