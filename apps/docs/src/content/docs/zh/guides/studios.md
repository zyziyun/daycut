---
title: 工作室和客户批量
description: 多个客户的批量并排跑，每个客户有自己的风格、品牌色、术语表和 AI 路由，每批都有质检报告和可以直接交付的打包。
---

每个客户一个工作区，这个客户的每一批都从 TA 的平台、剪辑风格、品牌色、字幕术语表和 AI 设置开始。每批结束时有一份质检报告和一个可以直接交给客户的交付包：按平台分的文件夹、发布文案、排期表，以及一份能证明交了哪些文件的清单。

## 开始之前

- **客户的基本信息**：名字、平台、固定风格、品牌色，以及转写容易写错的专有名词。
- **第一批的素材**。
- **一个可以用于付费客户工作的 AI 服务。** Claude Code、Codex 这类订阅制 CLI 是给你自己用的；给客户交付前请看清服务条款，需要时改用 API key 或本地模型。

## 在 Mac 应用里

1. 在设置里打开 **我在帮别人做视频**。打开后，全部项目里会多一个客户筛选，项目上多一个客户字段，还有客户交付和按客户统计的数据。关闭时，所有内容都算你自己的。
2. 打开 **客户管理**，添加一个客户，填好 TA 的平台、风格和品牌。
3. 照常在首页新建项目，并设置所属客户。客户的默认值会填进计划。
4. 审片和你自己的项目一样：只有被标出来的片子才进收件箱。你在审片时确认的字幕修改会加进这个客户的术语表，下一批就不会再错。
5. 这一批通过后，点交付。交付文件夹可以直接打包发给客户。

## 用 Claude Code 技能

先建一次客户：

```bash
python3 -m vstudio.batch client init --client acme --set \
  '{"name": "Acme", "platforms": ["xiaohongshu:full", "douyin"], "tags": ["RAG"], "cleanup_profile": "tight"}'
python3 -m vstudio.batch client update --client acme --set '{"glossary_add": [{"wrong": "rag flow", "right": "RAGFlow"}]}'
```

规格里写了 `client: acme`（或 `plan --client acme`）的批量，会继承客户的平台、标签、术语表、口癖规则、品牌色、去气口力度和确认策略。批量规格里单独写的值优先。

然后交付：

```bash
python3 -m vstudio.batch deliver --batch batch-acme-w41 --zip
python3 -m vstudio.batch metrics --client acme
```

## 客户会记住什么

| 设置 | 作用 |
|---|---|
| `platforms`、`tags` | 每批默认的平台和话题标签。 |
| `style`、`cover_style` | 固定剪辑风格；封面版式（`frame`、`collage`、`face` 或 `text`）。 |
| `brand` | 字幕、面板和封面用的强调色、高亮色、文字色和底色。 |
| `glossary` | 转写常错的词怎么改，每一批的字幕都会用上；你在审片时改字幕，它就会越来越全。 |
| `fillers` | 额外要剪的口头禅，以及永远保留的词。 |
| `cleanup_profile`、`confirm_policy` | 气口和口癖剪得多狠，哪些剪辑要等你点头。 |
| `language`、`asr_prompt` | 转写语言，以及帮助识别的专有名词。 |
| `llm` 路由 | 这个客户的选段、字幕校对和文案分别用哪个 AI。 |
| `delivery` | 每天发几条、发布时间，以及交付后多少天可以清理素材（0 = 永不）。 |

## 质检报告和交付包

每条片子都会过自动检查（响度、有没有剪掉字、字幕是否正常、平台时长、标题长度、安全区、音画同步、黑屏或卡帧）。`deliver` 把通过的片子打包到 `delivery/<客户>-<批次>-<日期>/`：

- 每个平台一个文件夹，放视频和封面
- `文案.md`：每条的标题、正文和标签，外加 AI 生成内容标识的提醒
- `排期表.csv`：发布排期
- `交付说明.md`：条数、时长、平台和质检备注
- `manifest.json`：每个文件的校验值和交付码
- 加 `--zip` 时再打一个压缩包

`metrics` 可以按批次或按客户统计每条的审片时间、返工率、红灯率和单条成本。

### 交付之后的清理

`cleanup-sources` 默认只是演练：列出已过清理日期的交付里具体是哪些文件，并给一个确认码。只有 `--confirm-delete <确认码>` 才会删除，而且只删那份清单。批量文件夹之外的文件，比如客户的原始录音，只会报告，永远不删。

## 示例指令

- 「新建一个客户 Acme：发小红书和抖音，剪得紧一点，品牌红 #E4002B，『RAGFlow』永远这么写。」
- 「用这三段录音开 Acme 这周的批量。」
- 「把 Acme 通过的片子打成压缩包交付，带排期表。」
- 「这个月 Acme 每条平均审了多久？」

## 相关

- [一次做 100 条以上](/docs/zh/guides/batch-100/)
- [批量引擎参考](/docs/zh/reference/engine/batch/)
- [主题和品牌](/docs/zh/concepts/themes/)
- [AI 服务](/docs/zh/concepts/ai-providers/)
- [项目](/docs/zh/concepts/projects/)
