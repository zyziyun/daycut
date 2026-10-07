---
title: 一次做 100 条以上
description: 在自己的 Mac 上规划、估算并批量跑一百条以上的短视频：先试看几条，之后只审自动质检标出来的那些。
---

一条长录音或一个文件夹的素材，变成一百条以上的成片，每条按平台导出，带字幕、封面和发布文案。你只需要看试看的几条、没通过检查的几条和一小部分随机抽查，其余直接进发布包。

## 开始之前

- **素材**：一条长录音（课程、直播回放、播客），或者一个文件夹的片段。
- **时间、硬盘空间和一个 AI 服务。** 转写和渲染都在本地跑，只有选段、字幕校对和发布文案会调用你的 AI 服务，而且只发文字。内部测试里，一节 72 分钟的课做成 24 条 × 4 个平台 = 96 个文件，AI 接口花了 0.73 美元，约每条 0.03 美元。
- **大概的想法**：切多少条、每条多长、发哪些平台。也可以让千剪（Reelfold）先提一份清单。

## 大批量是怎么跑的

1. **规格。** 一个文件写明配方、素材、每条都继承的默认值（平台、版式、去气口力度、倍速）和预算；每条一行，写区间、标题、钩子和标签。
2. **规划切片。** `plan-segments` 根据逐字稿起草清单：区间卡在词边界上，标题按各平台字数检查，附带钩子候选和笔记。你过一遍，删、挪、改标题。草稿不要不看就直接跑。
3. **估算。** 机器时间、实际耗时、存储和 API 费用；跑过一次试看后会按你这台机器的实测数据算。估算超出你设的预算时，`run` 不会开始。
4. **先试看。** 几条先完整跑完，然后整批停下。看版式、字幕、钩子和响度，改好规格再确认。
5. **全量跑。** 按资源队列并行（转写、渲染、AI 调用）。可以续跑：崩了或 Ctrl-C 之后再跑一次，做完的步骤不会重做。失败太多、红灯太多或花费超预算时，熔断会让整批暂停。
6. **质检关卡。** 每条都会自动检查：响度和真峰值、剪辑有没有吃掉字、字幕有没有凭空多出来的内容、各平台时长、标题长度、字幕区是否在安全区内、音画是否同步、有没有黑屏或卡帧。
7. **只审例外。** 你看到的是红灯的、绿灯里随机抽的 10%，以及等你点头的去口癖剪辑。其余可以一键通过。
8. **打包和清理。** 通过的片子按平台分文件夹，带排期表和确认码；然后删掉可以重新生成的中间文件。

## 在 Mac 应用里

1. 在首页描述这批要做什么，把录音拖进来：「这门课切 40 条竖屏，发小红书和抖音。」
2. 在计划里看一遍建议的切片清单，用一句话改。
3. 项目会先做第 1 条试看。在项目里看一下，没问题就让剩下的继续跑。
4. 收件箱只收需要你的：没过检查的、被抽查的、等你确认的口癖剪辑，同类的可以一次答完。
5. 片子通过后打包，再拖到发布页的周历上。

## 用 Claude Code 技能

跟 Claude 说要做批量，它会按 `workflows/batch` 走。在项目文件夹里对应的命令：

```bash
python3 -m vstudio.batch plan-segments --source raw/lecture.mp4 --count 40 --min 45 --max 150
python3 -m vstudio.batch plan batch.yaml
python3 -m vstudio.batch estimate --batch batch-course
python3 -m vstudio.batch run --batch batch-course --pilot 3
python3 -m vstudio.batch review --batch batch-course        # 打开 review/index.html
python3 -m vstudio.batch run --batch batch-course --confirm-pilot
python3 -m vstudio.batch review --batch batch-course --approve-green
python3 -m vstudio.batch package --batch batch-course --per-day 2 --start 2026-10-10
```

`status` 显示进度、质检灯和暂停原因。解决之后 `run --resume` 继续。

### 硬盘空间

一百条 × 几个平台，占用会很快涨上去。查看并回收：

```bash
python3 -m vstudio.batch du --batch batch-course       # 按部分和步骤统计占用
python3 -m vstudio.batch clean --batch batch-course    # 删掉可以重新生成的中间文件
```

`clean` 会保留 JSON、封面、联系表和预览，以后要改时只重建需要的部分。它不会删你的原始录音。

## 值得了解的选项

| 选项 | 位置 | 作用 |
|---|---|---|
| `budget` | 规格 | `max_usd`、`max_hours`、`max_storage_gb`，超预算 `run` 会拒绝。 |
| `--pilot N` | run | 先完整跑 N 条，然后等你审。 |
| `qc.sample_pct` | 规格 | 绿灯里抽多少比例给人看（默认 10）。 |
| `concurrency` | 规格或 `--concurrency` | 调整并行上限，例如 `cpu-render=2`。 |
| `variants` | 规格 | 按钩子、平台或语言展开成多个版本。 |
| `max_len` | 规格或单行 | 给某个平台出更短的版本，例如 `douyin: 60`。 |
| `breaker` | 规格 | 失败率超过多少就暂停（默认 4 条之后超过 0.3）。 |

## 示例指令

- 「这门 3 小时的课切 60 条左右竖屏，每条 45 秒到两分半，发小红书和抖音。先给我看清单。」
- 「先跑 3 条试看，没问题的话剩下的晚上跑完。」
- 「每条出 3 个钩子版本，各导出 Shorts 和 TikTok。」
- 「这批占了多少硬盘？能重新生成的都清掉。」

## 相关

- [批量和审片](/docs/zh/concepts/batch-review/)
- [批量引擎参考](/docs/zh/reference/engine/batch/) 和 [batch 工作流](/docs/zh/reference/workflows/batch/)
- [长视频切片](/docs/zh/guides/long-video-to-clips/)
- [工作室和客户批量](/docs/zh/guides/studios/)
- [排期和发布](/docs/zh/guides/scheduling-publishing/)
