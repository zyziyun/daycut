---
title: AI 模型
description: 千剪用你自己的 AI：已登录的 Claude Code 或 Codex、你自己的 API key，或者本地模型。了解哪些步骤会用到 AI，怎样按任务分别指定模型、设置按顺序尝试的备用模型，备用提示是什么意思，以及每一步大概花多少钱。
---

千剪（Reelfold）不自带 AI，用的是你已经有的：已经登录的 Claude Code 或 Codex 命令行、你自己选的服务商的 API key，或者跑在你自己电脑上的模型。每项任务都可以分别指定。

## 为什么重要

花多少钱、效果怎么样、文字发到哪里，都由你决定。已经在付费的订阅可以直接拿来做规划，不额外花钱；本地模型能让一切留在你的 Mac 上。某个服务商挂了或者登录过期，备用模型可以顶上，并且会明确告诉你这次是谁回答的。

## 哪些步骤会用到 AI

| 步骤 | AI 做什么 |
|---|---|
| 接单 | 把你的一句话和素材变成计划 |
| 选段规划 | 从长录像里挑出要切的片段，配标题和 hook |
| 字幕校对和术语表 | 修正语音识别听错的人名和术语 |
| 发布文案和脚本 | 写标题、正文、口播稿 |
| 成片二次编辑 | 把一句话的修改要求变成具体编辑步骤 |

语音识别和配音是另外两套：转写默认在本地跑（Apple Silicon 上的 whisper），配音可以用本地声音、你自己的克隆声音，或者在线服务。所有文字类步骤在完全没有模型时也能跑，走规则方案。

## 三种接入方式

| 方式 | 支持的服务 | 说明 |
|---|---|---|
| 命令行登录，不用 API key | Claude Code、Codex | 用你已登录的订阅。运行时不开放任何工具，在一个空的临时文件夹里跑，不会往你的项目里写东西 |
| API key | Anthropic、OpenAI、DeepSeek、通义千问 Qwen、Kimi、智谱 GLM、OpenRouter、Gemini；配音用 ElevenLabs | 配置文件里只写环境变量名，不写 key 本身 |
| 本地 | Ollama、LM Studio、vLLM、llama.cpp；本地 whisper；你自己的 whisper 或 TTS 服务 | 数据不离开你的电脑 |

:::note[订阅命令行是给你自己用的]
Claude Code 和 Codex 的订阅有各自的用量限制和使用条款。如果要用它们大批量做收费的客户项目，先看清服务商当前的条款，条款要求的地方改用 API key 或本地模型。
:::

## 按任务分配和备用模型

每项任务（接单、选段规划、校对、术语表、文案、脚本、成片编辑）都可以单独指定模型，没单独指定的用默认。每条设置还可以按顺序列出备用模型：第一个失败了，就试下一个。某次运行里明确点名的模型不会切换到备用。

切到备用时，你会看到提示，而不是悄悄换掉：

- `llm-fallback`：「Claude Code 没成功（登录过期），改用了 Codex」。任务照常完成。
- `llm-all-failed`：链条里所有模型都失败了。这一步会停下并列出它们。有规则方案的地方（选段规划、接单）会用规则补上，并告诉你。

失败原因包括：登录过期、没登录、没安装、缺少 key、触发限流、超时。

## 费用

API 调用按 token 计费，每一步都会报告花费。订阅命令行和本地模型记为 0。内部测试里，一节 72 分钟的课切成 24 条、每条 4 个平台（共 96 个文件），API 总花费 0.73 美元，大约每条 0.03 美元。

## 在 Mac App 里

「设置 → AI 账号与模型」里能看到每个服务的状态（Claude Code 登录过期会直接显示过期），可以在内置终端里登录命令行工具，API key 存进 macOS 钥匙串，也可以设置默认模型、每项任务的模型和备用顺序。

## 用 Claude Code 技能

在 `persona.local.yaml` 里写一段 `llm:`，然后在 `lib/` 目录下检查：

```bash
python3 -m vstudio.llm providers   # 这台电脑上哪些能用；不会发送任何内容
python3 -m vstudio.llm route       # 每项任务用哪个模型，以及为什么
python3 -m vstudio.llm test --provider ollama --model llama3.2:1b   # 发一次很小的测试请求
```

## 相关

- [隐私](/docs/zh/concepts/privacy/)
- [Persona 参考](/docs/zh/reference/persona/)
- [模型服务引擎参考](/docs/zh/reference/engine/providers/)
- [引擎提示信息](/docs/zh/reference/messages/)
