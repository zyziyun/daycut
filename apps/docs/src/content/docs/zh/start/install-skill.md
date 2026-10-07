---
title: 安装 Claude Code 技能
description: 三条命令装好 Claude Code 的 video-studio 技能：install.sh 会下载什么、Whisper 模型怎么离线用、怎么更新和检查安装是否正常。
---

Claude Code 技能就是把千剪（Reelfold）的引擎打包给 [Claude Code](https://claude.com/claude-code) 用。装好以后，你直接跟 Claude 说要怎么剪（「去气口，1.1 倍速」），技能会告诉 Claude 该走哪个工作流，背后有测过的脚本和共享库。技能的名字仍然是 `video-studio`。

## 需要什么

**必需**

- Claude Code
- Python 3.10+
- `ffmpeg`（`brew install ffmpeg` 或 `apt install ffmpeg`）

**按需安装**

| 你想做 | 需要 |
|---|---|
| 讲解视频、宣传片二剪（HyperFrames） | Node 18+ 和 `npx hyperframes` |
| HTML 封面和幻灯片 | Chrome / Chromium，或 Playwright |
| AI 配音（OpenAI TTS） | `OPENAI_API_KEY` |
| 音乐曲库 | HeyGen CLI |
| 更准的卡点节拍 | `librosa` |
| HEIC 照片 | `pillow-heif`（macOS 上没装会改用 `sips`） |
| 用你自己克隆的声音 | `mlx-audio` 和 Qwen3-TTS 模型 |

## 安装

运行这三行：

```bash
git clone https://github.com/zyziyun/reelfold ~/.claude/skills/video-studio
~/.claude/skills/video-studio/install.sh
cp ~/.claude/skills/video-studio/persona.example.yaml ~/.claude/skills/video-studio/persona.local.yaml
```

1. 克隆到 Claude Code 读取技能的位置。
2. `install.sh` 安装 Python 依赖，下载字体和模型（见下文）。可以重复运行，已经下好的文件会跳过。
3. `persona.local.yaml` 存放你的个人偏好：默认语速、响度、品牌色、标题规则、话题标签、术语纠错、字体，以及每项工作用哪个 AI。这个文件不进 git，你的设置不会被提交到仓库。全部选项见 [persona.yaml 选项](/docs/zh/reference/persona/)。

装完后新开一个 Claude Code 会话，让它加载技能。

## install.sh 会下载什么

所有东西都放在一个缓存目录 `~/.cache/video-studio` 里（用 `VSTUDIO_CACHE` 可以换位置）：

| 内容 | 位置 | 协议 |
|---|---|---|
| 思源黑体（Noto Sans SC）、思源宋体（Noto Serif SC）、STIX Two Text、JetBrains Mono | `fonts/` | SIL OFL 1.1 |
| MediaPipe 人脸关键点、人像分割、多类别人像分割（修图用） | `models/` | Apache-2.0 |
| `requirements.txt` 里的 Python 包；Apple 芯片另装 `mlx-whisper`，其他机器装 `faster-whisper` | 你的 Python 环境 | 各自的协议 |

最后如果缺 `ffmpeg` 或 `npx`，脚本会提醒你。设 `SKIP_PIP=1` 可以跳过 Python 包，只下载字体和模型。

逐字稿、TTS 配音等可复用的结果也存在这个缓存里。Mac 应用用的是同一个目录，所以不会重复下载。

## Whisper 模型和离线使用

第一次转写时会把 Whisper 模型下载到 Hugging Face 缓存（`~/.cache/huggingface/hub`，或 `$HF_HOME/hub`）：

- mlx-whisper（Apple 芯片）用 `mlx-community/whisper-large-v3-turbo`
- faster-whisper 用 `large-v3-turbo`（`Systran/faster-whisper-large-v3-turbo`）

想用手头已有的模型，或者在不联网的机器上用，把路径告诉引擎：

```bash
export VSTUDIO_WHISPER_MLX=/path/to/whisper-large-v3-turbo-mlx    # MLX 模型文件夹（config.json + weights），或 HF 仓库 id
export VSTUDIO_WHISPER_FW=/path/to/faster-whisper-large-v3-turbo  # CTranslate2 模型文件夹，或 small 这样的尺寸名
export HF_HUB_OFFLINE=1                                           # 完全不联网
```

转写后端自动选择：优先 mlx-whisper，其次 faster-whisper；都没有且设置了 `OPENAI_API_KEY` 时，用 OpenAI 的 `whisper-1`。

## 选择 AI

每个 AI 步骤（挑片段、校对字幕、术语表、发布文案）都可以用你已登录的 Claude Code 或 Codex CLI（不需要 API key）、API key，或本地模型。在 `persona.local.yaml` 里设置：

```yaml
llm:
  default: {provider: claude-code}
```

按任务分别指定、备用顺序和费用：见 [AI 服务](/docs/zh/concepts/ai-providers/)。

## 检查安装

看看这台机器上有哪些 AI 服务、转写和 TTS 引擎可用（不会发送任何数据）：

```bash
cd ~/.claude/skills/video-studio/lib && python3 -m vstudio.llm providers
```

也可以跑一遍测试（用合成素材，不联网，需要先装 `pytest`）：

```bash
cd ~/.claude/skills/video-studio && python3 -m pytest tests -q
```

## 从旧仓库地址迁移

如果你是在它还叫 video-studio 时克隆的，把远程地址指向新仓库就行。文件夹名、技能名和 `vstudio` 包名都不变：

```bash
git -C ~/.claude/skills/video-studio remote set-url origin https://github.com/zyziyun/reelfold
```

旧版本会把一部分缓存写到 `~/.cache/vstudio`。现在仍会读取，但不再写入；确认用不上之后可以删掉。

## 更新

```bash
git -C ~/.claude/skills/video-studio pull
~/.claude/skills/video-studio/install.sh
```

重新运行 `install.sh` 会装上新增的 Python 依赖和新的字体、模型，不会动你的 `persona.local.yaml`。

## 相关页面

- [第一个项目](/docs/zh/start/first-project/)
- [示例指令](/docs/zh/examples/)
- [命令行参考](/docs/zh/reference/cli/)
- [安装 Mac 应用](/docs/zh/start/install-mac/)
