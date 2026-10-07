---
title: 问题排查
description: 千剪常见问题的解决办法：找不到 ffmpeg、whisper 模型下载、缺字体、AI 登录过期、批量太慢、硬盘满了、字幕里的人名地名写错。
---

每一条都写了现象、可能的原因和解决办法。如果看到 `llm-all-failed`、`qc.loudness` 这样的提示代码，可以到[提示和错误代码](/docs/zh/reference/messages/)里查。

## 安装和引擎

### 找不到 ffmpeg

引擎先在 `PATH` 里找 `ffmpeg` 和 `ffprobe`，找不到再用 `static-ffmpeg` 包。

- 安装：`brew install ffmpeg`。
- 或者指定路径：`VSTUDIO_FFMPEG=/path/to/ffmpeg`、`VSTUDIO_FFPROBE=/path/to/ffprobe`。

### 硬件 H.264 编码器用不了

`VSTUDIO_H264_ENCODER`（或 persona 里的 `export.h264_encoder`）决定用哪个编码器：`libx264`（默认）、macOS 上的 `h264_videotoolbox`、Windows 上的 `h264_mf`。引擎会先试编码一次，这台机器上不能用就自动退回 `libx264`，硬件编码失败的命令也会用 libx264 重跑。一般不用管；如果你确实想用硬件编码，检查一下你的 ffmpeg 是否支持。

### whisper 模型下载很慢，或者没有网络

第一次转写会把模型下载到 Hugging Face 缓存（`~/.cache/huggingface/hub`，或 `$HF_HOME/hub`）：Apple Silicon 上 mlx-whisper 用 `whisper-large-v3-turbo`，其他机器上 faster-whisper 用 `large-v3-turbo`。

- 在网络好的时候先完整下载一次，之后都复用。
- 已经有模型的话直接指过去：`VSTUDIO_WHISPER_MLX=/path/to/whisper-large-v3-turbo-mlx` 或 `VSTUDIO_WHISPER_FW=/path/to/faster-whisper-large-v3-turbo`（也可以写 `small` 这样的尺寸名）。
- 再加上 `HF_HUB_OFFLINE=1`，就完全不联网。

### 提示「font '…' not found」

某个字体角色（`cjk`、`cjk-bold`、`serif`、`mono` 等）在 `~/.cache/video-studio/fonts` 里找不到。用到它的地方会换成备用字体，所以这个提示故意很显眼。

- 再跑一次 `./install.sh`，它会下载开源授权的字体。
- 或者在 `persona.local.yaml` 的 `fonts:` 下指向你自己的字体文件；字体集里的某一个字重写成 `path/to/Fonts.ttc#N`。

### 提示「model '…' not found」（MediaPipe）

人脸跟踪、修图、封面挑帧和抠图都用到 MediaPipe 的人脸关键点和分割模型。`./install.sh` 会把它们下载到 `~/.cache/video-studio/models`，缺了就再跑一次。没有模型时，封面会退回居中裁切。

### Mac 应用找不到引擎

应用显示 **演示模式** 而不是 **本机就绪**，说明它没能加载引擎，正在用一个替身跑。

1. 打开设置 → **引擎**，这里会显示 **当前使用** 的引擎文件夹、Python 和数据文件夹。
2. 把 **引擎文件夹（Reelfold 仓库）** 设成包含 `lib/vstudio` 的文件夹，**Python 路径** 设成装好了 `requirements.txt` 的解释器。
3. 也可以用环境变量：引擎用 `VSTUDIO_ENGINE_PATH`，Python 用 `DESK_PYTHON`。应用会先看设置，再看这两个变量，最后用它自己所在的仓库。

### 旧的缓存文件夹

所有缓存都在 `$VSTUDIO_CACHE` 下，默认 `~/.cache/video-studio`。旧版本有一部分写在 `~/.cache/vstudio`，现在只读不写；确定用不到了就可以删掉。

## AI 服务

### 「所有 AI 模型都失败了」（`llm-all-failed`）

指定的 AI 和所有备用都失败了，提示里会列出试过哪些。

- 看看这台 Mac 上有什么：在仓库的 `lib` 文件夹里运行 `python3 -m vstudio.llm auth status`，或者在应用里打开设置 → **AI 账号与模型**。
- 修好第一个失败的（登录、key、本地服务），或者加一个备用：应用里按任务设置；persona 里在路由上写 `fallback: [codex, ollama]`。

「Claude Code 没成功，改用了 Codex」这类 `llm-fallback` 提示不是错误，活已经由下一个 AI 做完了。

### Claude Code 登录过期

应用会用一句话的往返来检查 Claude Code，因为它自己的状态在令牌过期后仍可能显示「已登录」。

- 在应用里：设置 → AI 账号与模型 → **重新登录**，登录在应用内置的终端里完成。
- 在终端里：运行 `claude`，然后 `/login`（或 `claude auth login`）。

引擎从来看不到你的密码或令牌。因为登录过期停下的任务不会丢东西：登录后再跑一次，做完的步骤不会重做。

## 批量

### 批量跑得慢

- 大批量开始前先跑 `estimate`。在空闲的 Mac 上跑过一次试看后，估算会用你这台机器的实测速度（`bench` 可以看这张表）。
- 转写一次只跑一个（whisper 独占 GPU），渲染会并行几个。Mac 同时在忙别的事时，用 `--concurrency cpu-render=2` 调低；空闲时才考虑调高。
- `VSTUDIO_H264_ENCODER=h264_videotoolbox` 让所有编码用 Mac 的硬件编码器。
- 长视频修图用 `fast` 预设，比 `quality` 快三倍左右。

### 硬盘满了

```bash
python3 -m vstudio.batch du --batch <批次>      # 看空间被谁占了
python3 -m vstudio.batch clean --batch <批次>   # 删掉可以重新生成的中间文件
```

`clean` 会保留 JSON、封面、联系表和预览。已交付的客户批量可以用 `cleanup-sources`：先演练列出过了清理日期的素材文件，只有带上它给出的确认码才会删除。批量文件夹之外你自己的录音永远不会被删。

## 字幕和剪辑

### 字幕里的人名、地名、术语写错了

语音识别是按读音写名字的。

- 烧录字幕前会先校对并核对专有名词：地名对齐到标准写法，你的术语表在所有地方统一套用。这一步别跳过。
- 在 `persona.local.yaml` 里加自己的修正：`subtitles: {term_fixes: [["[Tt]runking", "chunking"]]}`（一个正则和它的替换）。客户批量用客户的术语表。
- 转写前就把关键术语告诉它（`asr: {prompt: "LangChain, RAG"}`）。
- 在审片时改单条字幕。如果改动多了或少了实际说出来的字，会被拒绝，除非重新听那段音频确认确实是这么说的。

### 去气口剪多了

1. `python -m vstudio.cleanup verify 输出文件` 会把剪好的片子重新转写一遍，丢了实词会报错，并给出原片和成片里的时间。
2. 把盖住它的那条剪辑保留下来：回复 `保留 7`（或 `--keep 7`），再应用一次。
3. 经常这样的话，换更温和的档位（`gentle` 会多留停顿和换气），或者在 persona 的 `cleanup.never_cut` 里加上不想被剪的词。

在应用里，可能是真词的口癖剪辑会在收件箱里等你确认，想留的就选保留。

## 相关

- [提示和错误代码](/docs/zh/reference/messages/)
- [常见问题](/docs/zh/help/faq/)
- [AI 服务](/docs/zh/concepts/ai-providers/) 和 [AI 服务参考](/docs/zh/reference/engine/providers/)
- [去气口参考](/docs/zh/reference/engine/cleanup/)
- [安装 Mac 应用](/docs/zh/start/install-mac/) 和 [安装技能](/docs/zh/start/install-skill/)
