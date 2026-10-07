<p align="center">
  <a href="README.md">English</a> · <a href="README.zh-CN.md">简体中文</a> · <a href="README.fr.md">Français</a>
</p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/brand/wordmark-on-dark.svg">
    <img alt="Reelfold 千剪" src="docs/brand/wordmark-on-light.svg" width="360">
  </picture>
</p>

<p align="center"><b>一条素材，千条成片，一次发到各个平台。</b><br>
说清楚要什么，把素材放进来，每个平台的每一条都给你剪好。</p>

<p align="center">
  <a href="https://reelfold.com/zh/">reelfold.com</a> ·
  <a href="https://github.com/zyziyun/reelfold/releases/latest">下载 macOS 版</a> ·
  <a href="https://github.com/zyziyun/reelfold">在 GitHub 上 Star</a> ·
  <a href="#安装">安装 Claude Code 技能</a> ·
  <a href="LICENSE">MIT</a>
</p>

<p align="center"><sub>免费开源（MIT）。macOS 正式版即将发布，在那之前可以从源码构建（见<a href="#安装">安装</a>）。</sub></p>

**千剪（Reelfold）** 是一个免费开源、本地优先的视频编排工具，给需要批量剪辑的人用。用大白话说清楚这批要什么，放进一段素材：
千剪规划选段，在你自己的电脑上并行剪辑，逐个文件自动质检，只把有问题的例外交给你看。每个平台单独导出成片、封面、标题、
正文和标签。发布是辅助式的：千剪帮你填好平台的上传页面，发布按钮由你自己点，它不会自动发。

同一套引擎，两种用法：

- **千剪 Mac 版**（`apps/desk`）：桌面应用。看板管理批次、网格审片、按逐字稿删改、辅助发布。免费、MIT 开源，
  目前只支持 Apple 芯片，Windows 版之后推出。
- **Claude Code 技能 `video-studio`**（仓库根目录）：把引擎当技能用。直接跟 Claude 说（「去气口，1.3 倍速」
  「这节 70 分钟的课切成 3 条竖屏」），技能告诉 Claude 该走哪个流程，并提供测试过的脚本和共享库。

![口播 · 切片 · 文艺片 · 卡点 vlog · 播客遮脸 · 讲解短片](docs/demos/strip.jpg)
<sub>用这套引擎从头做到尾的六种成片画面，下面有缩略图。</sub>

## 适用场景

| 谁在用 | 千剪做什么 |
|---|---|
| **批量创作者** | 录一次，发一周：一次录制拆成一组短视频，每条按各平台要求的比例、时长和响度导出（`batch`）。 |
| **访谈和播客** | 从一段长对话里切出多条片段，带字幕、说话人构图、嘉宾遮脸和名字打码，按平台分别导出（`call-clips`、`batch` 的 `podcast-clips`）。 |
| **做客户批次的工作室** | 多个客户的批次并行跑，每个客户保留自己的风格和术语表，每批附质检报告（`batch`、projects）。 |
| **口播** | 去气口、口头禅和重复，加字幕、关键词弹字、记笔记面板、进度条、封面和发布文案（`talkinghead`）。 |
| **课程切片** | 长课、讲座切成竖屏片段或分集，带标题条、清晰的代码裁切和章节卡，学员声音可以变声（`longform-to-short`）。 |
| **AI 视频** | 3Blue1Brown 风格讲解短片（AI 配音、中英字幕），或 AI 生成的系列视频（可灵、即梦 / Seedance、MiniMax），带积分预算（`explainer`、`ai-video`）。 |

本地优先、成本友好：语音转写和渲染都在本机完成；只有逐字稿文本、少量关键帧和标题会发给你选的 AI 服务（也可以完全不用
API key，走本地模型或你自己登录的 Claude Code / Codex CLI）。我们的内部测试批次（一节 72 分钟讲座 → 24 条 × 4 个平台 =
96 个文件）AI API 费用是 $0.73，约 $0.03 / 条。

## 安装

**桌面版（macOS，Apple 芯片）**：免费、MIT 开源。第一个正式版发布后（即将推出）从
[GitHub Releases](https://github.com/zyziyun/reelfold/releases/latest) 下载。AI 用你自己的 Claude Code / Codex 订阅、API key 或本地模型。

正式版发布前，可以从源码构建（macOS，Apple 芯片；Node 22+、Python 3.10+、`ffmpeg`）：

```bash
git clone https://github.com/zyziyun/reelfold && cd reelfold
./install.sh && npm install
npm run desk
```

**Claude Code 技能**：技能名仍然是 `video-studio`，目录仍是 `~/.claude/skills/video-studio`：

```bash
git clone https://github.com/zyziyun/reelfold ~/.claude/skills/video-studio
~/.claude/skills/video-studio/install.sh
cp ~/.claude/skills/video-studio/persona.example.yaml ~/.claude/skills/video-studio/persona.local.yaml
```

以前从旧仓库克隆过？把远程地址改到新仓库：
`git -C ~/.claude/skills/video-studio remote set-url origin https://github.com/zyziyun/reelfold`。

依赖：Python 3.10+、`ffmpeg`。可选：Node 18+ 和 `npx hyperframes`（explainer、promo-recut），Chrome / Playwright
（HTML 封面和幻灯片），`OPENAI_API_KEY`（AI 配音）。Apple 芯片上转写用 `mlx-whisper`，其他平台用 `faster-whisper`。
Whisper 模型、AI 服务商、缓存目录和 H.264 编码器的设置见英文 README 的
[Engine setup](README.md#engine-setup-skill) 和 [references/PROVIDERS.md](references/PROVIDERS.md)。

## 引擎覆盖的流程

| 流程 | 把什么 → 变成什么 |
|---|---|
| `talkinghead` | 口播素材 → 精剪短视频：去气口 / 口头禅 / 重复、加速、字幕、推近、弹字、记笔记面板、进度条、高光预告、B-roll、美颜、封面、发布文案 |
| `promo-recut` | 口播 + 截图 / 链接 / 另一段视频 → 高级感宣传片：左右分栏、3D 截图卡片高亮、定格放大、精选插片 |
| `longform-to-short` | 课程、讲座、直播、录屏 → 剪成课程和 / 或 N 条短视频，竖屏切片（3:4 / 9:16），代码放大，封面和发布包 |
| `call-clips` | Zoom / Meet / Teams / 访谈 → 竖屏、三人同框或横屏片段，遮脸（贴纸）和名字打码 |
| `photo-story` | 照片 + 旁白稿 → 文艺片（多种镜头、叠加、转场、胶片质感），可纯音乐卡小节，可用你自己克隆的声音 |
| `vlog` | 航拍 / 旅行 / 手机素材 → `calm`（调色、变速、交叉淡化、配乐）或 `fun`（卡点、变速、转场、弹字、音效） |
| `explainer` | 一个主题 → 3Blue1Brown 风格动画讲解，AI 配音 + 中英字幕，16:9 长视频或竖屏短片 |
| `polish` | 已导出的成片 → 可选去气口、首帧封面、响度、加速、交付标签，一个或多个平台 |
| `ai-video` | 脚本或想法 → AI 生成视频：角色设定、分镜 prompt、积分预算、选条、拼接、多平台投稿包 |
| `batch` | 一次几十到几百条：试跑、可续跑的并行任务、质检关卡、只看例外的审片页、发布包 |
| `cover`、`slides`、`preproduction` | 各平台尺寸封面、幻灯片、写稿和发音练习 |

还有：统一的去气口工具（[references/CLEANUP.md](references/CLEANUP.md)）、平台配置和多平台导出
（[references/PLATFORMS.md](references/PLATFORMS.md)）、人脸跟随重构图、卡点和音效
（[references/SOUND.md](references/SOUND.md)）、特效库（[references/EFFECTS.md](references/EFFECTS.md)）、
美颜（[references/RETOUCH.md](references/RETOUCH.md)）。真实素材的测试记录和已知限制：
[references/VALIDATION.md](references/VALIDATION.md)。

## 怎么说：示例

| 你想要 | 可以这么说 | 流程 |
|---|---|---|
| 口播精剪 | 「把这个口播剪一下：去气口、去口头禅和重复，1.1倍速，加字幕、记笔记、进度条，发小红书」 | `talkinghead` |
| 只清理语音 | 「这段录音去气口、去嗯啊和重复，不确定的列给我确认」 | `cleanup` |
| 长视频切片 | 「这个 70 分钟的课切成 3 条竖屏短视频，每条一个知识点，代码放大，带封面和发布文案」 | `longform-to-short` |
| 播客 / 通话片段 | 「从这个 Zoom 播客里找一段最有意思的 1 分钟，嘉宾遮脸、名字打码，竖屏」 | `call-clips` |
| 批量 | 「这门课切 50 条，小红书和抖音各一版，我只看有问题的」 | `batch` |
| 多平台 | 「同一条导出小红书 3:4、抖音、YouTube Shorts，各自安全区和响度」 | `python -m vstudio.export` |

更多示例见英文 README 的 [What to say](README.md#what-to-say-example-prompts)。

## 样片

| | |
|---|---|
| **口播精剪**（`talkinghead`） ![](docs/demos/talkinghead.jpg) | **长视频切片**（`longform-to-short`） ![](docs/demos/longform-slices.jpg) |
| **文艺片**（`photo-story`） ![](docs/demos/photo-story.jpg) | **快节奏旅游 vlog**（`vlog` fun） ![](docs/demos/fun-vlog.jpg) |
| **播客剪辑 + 遮脸**（`call-clips`） ![](docs/demos/call-clips.jpg) | **讲解短片**（`explainer` 竖屏） ![](docs/demos/explainer-vertical.jpg) |

## 原名 video-studio / 日剪 Daycut

千剪（Reelfold）是这个项目的新名字。开源技能和引擎之前叫 **video-studio**，桌面版之前叫 **日剪 / 日更剪（Daycut）**。
Claude Code 技能名仍然是 `video-studio`，Python 包仍然是 `vstudio`，装在 `~/.claude/skills/video-studio` 的旧安装照常
可用；只是仓库地址换成了 `github.com/zyziyun/reelfold`。

## 许可

代码采用 MIT 许可（见 `LICENSE`），包括 `apps/desk` 和 `apps/site`。字体和模型在安装时从上游下载，遵循各自的许可
（SIL OFL 1.1、Apache-2.0），本仓库不再分发。`workflows/cover` 里可选的 RVM 抠像引擎是 GPL-3.0，只有你选用时才会下载。
HTML 转视频的流程基于 [HyperFrames](https://hyperframes.heygen.com)。
