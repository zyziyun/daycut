---
title: 隐私：千剪会发送什么
description: 千剪 Mac 版可以分享匿名使用次数，但只有你打开才会发送。这里列出发送的每一个字段、怎么关闭、怎么删除已发送的数据。
---

千剪 Mac 版可以把几个匿名次数发给我们，比如“一批 12 条切片完成”。**默认关闭，只有你打开才会发送**：首次运行时可以勾选，之后在 **设置 › 通用 › 隐私 › 分享匿名使用次数** 里随时开关。关闭时什么都不会发送，也不会生成 ID。

这些次数只用来做一件事：知道到底有多少人真的在用千剪（装了并且跑完过一批），好让它一直免费，也能找到愿意交流的用户。

## 发送的每一个字段

每个事件是一个很小的 JSON，通过 HTTPS 发到 `https://t.reelfold.com/api/v1/ping`：

| 字段 | 例子 | 含义 |
|---|---|---|
| `id` | `6f1c…-…` | 你第一次打开分享时在本机随机生成的 ID，和你的名字、邮箱、电脑、Apple ID 都没有关系，随时可以换新。 |
| `v` | `0.2.0` | 应用版本号。 |
| `os`、`arch` | `darwin`、`arm64` | 操作系统和处理器类型。 |
| `locale` | `zh-CN` | 应用的界面语言（English、简体中文或 Français）。 |
| `ev` | `batch_done` | 事件名，只有下面五种。 |
| `day` | `2026-10-14` | 发生的日期（UTC），不含具体时间。 |
| `n` | `{ "clips": 12 }` | 几个小整数，只有下表列出的事件才有。 |

| 事件 | 什么时候 | 数字 |
|---|---|---|
| `app_open` | 应用开着（每天最多一次） | 无 |
| `first_batch_done` | 第一次跑完一批（只发一次） | 无 |
| `batch_done` | 一批或一个项目跑完 | `clips`（条数），知道时还有 `formats`（格式数）和 `minutes_in`（素材分钟数，取整） |
| `export_done` | 导出或交付了切片 | `count`（条数） |
| `publish_package` | 生成了发布包 | `platform_count`（平台数） |

完整清单就是这些。应用绝不发送文件名、文件夹路径、标题、字幕、逐字稿、指令、AI 服务商名称或密钥、发布账号，也不发送素材里的任何内容。演示引擎里跑的批次不计入。

## 服务器保存什么

- 只保存上面这些字段，加上服务器自己的日期。**不保存、不记录你的 IP 地址**：IP 只在内存里停留约一分钟，用来限流。不用 cookie，不记录浏览器信息，不做设备指纹。
- 表里没有的内容在保存前就丢掉；有异常值的事件整个丢掉。
- 原始事件 **13 个月** 后删除。不含任何 ID 的每日合计（比如“10 月 14 日共做了 40 条”）会一直保留。
- 数据存在 Cloudflare D1（Cloudflare Workers），只有千剪的维护者能看，而且看到的只是合计数。

服务器代码是开源的：[`apps/telemetry`](https://github.com/zyziyun/reelfold/tree/main/apps/telemetry)；应用这一侧在 [`apps/desk/src/main/usage.ts`](https://github.com/zyziyun/reelfold/blob/main/apps/desk/src/main/usage.ts)。

## 怎么发送

由应用的后台进程发送，有很短的超时，不会让应用变慢或卡住。没联网时，事件先存在你电脑上（应用资料文件夹里的 `usage.json`），下次联网再一起发；超过 13 天的直接丢掉。开发版、自动化测试和 CI 永远不会发送。

## 关闭

**设置 › 通用 › 隐私** → 关掉 **分享匿名使用次数**。还没发出去的内容会立刻清空。

## 删除已发送的数据

**设置 › 通用 › 隐私 › 删除我的使用数据**：让服务器删除当前 ID 的所有事件（`DELETE https://t.reelfold.com/api/v1/installs/<id>`），然后换一个新 ID。不含 ID 的每日合计会保留。只点 **换新 ID** 则从零开始计数，但不删除旧数据。

如果你已经卸载了应用，可以带着你的 ID（如果还记得）联系我们，联系方式见[隐私政策](https://reelfold.com/zh/privacy/)；没有 ID 就无法把这些事件和你对应起来。

## 技能和网站

- Claude Code 技能（`video-studio`）不发送任何使用数据。
- 官网和文档可能用 [Cloudflare Web Analytics](https://www.cloudflare.com/web-analytics/) 统计浏览量：不用 cookie，不保存个人信息。

## 相关

- [隐私](/docs/zh/concepts/privacy/)
- [隐私政策](https://reelfold.com/zh/privacy/)
