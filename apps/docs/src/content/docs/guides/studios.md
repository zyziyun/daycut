---
title: Studios and client batches
description: Run batches for several clients side by side, each with its own style, brand, glossary and AI routes, a QC report per batch, and a delivery package.
---

You get one workspace per client, so every batch for that client starts from their platforms, style, brand colours, caption glossary and AI setup. Each batch ends with a QC report and a delivery package you can hand over: per-platform folders, the post copy, a posting schedule and a manifest that proves which files were delivered.

## Before you start

- **The client's basics**: name, platforms, house style, brand colours, terms they use that a transcript tends to get wrong.
- **Their source material** for the first batch.
- An AI route you are allowed to use for paid client work. Subscription CLIs such as Claude Code and Codex are meant for your own use; check your provider's terms and use an API key or a local model where they call for it.

## In the Mac app

1. In Settings, turn on **I make videos for other people**. It adds a client filter in All projects, a client field on projects, client delivery and per-client numbers. Off, everything is yours.
2. Open **Clients** and add one. Set their platforms, style and brand.
3. Start a project as usual from Home and set its client. The client's defaults fill the plan.
4. Review works the same as for your own projects: only the flagged clips come to your Inbox. Caption fixes you accept are added to that client's glossary, so the next batch gets them right.
5. When the batch is approved, deliver it. The delivery folder is ready to zip and send.

## With the Claude Code skill

Create the client once:

```bash
python3 -m vstudio.batch client init --client acme --set \
  '{"name": "Acme", "platforms": ["xiaohongshu:full", "douyin"], "tags": ["RAG"], "cleanup_profile": "tight"}'
python3 -m vstudio.batch client update --client acme --set '{"glossary_add": [{"wrong": "rag flow", "right": "RAGFlow"}]}'
```

A batch with `client: acme` in its spec (or `plan --client acme`) inherits the client's platforms, tag set, glossary, filler rules, brand colours, cleanup profile and confirm policy. Anything set in the batch spec wins.

Then deliver:

```bash
python3 -m vstudio.batch deliver --batch batch-acme-w41 --zip
python3 -m vstudio.batch metrics --client acme
```

## What a client keeps

| Setting | What it does |
|---|---|
| `platforms`, `tags` | Default platforms and hashtags for every batch. |
| `style`, `cover_style` | House editing style; cover layout (`frame`, `collage`, `face` or `text`). |
| `brand` | Accent, highlight, ink and ground colours for captions, panels and covers. |
| `glossary` | Corrections for terms the transcript gets wrong, applied to the captions of every batch. Grows as you fix captions in review. |
| `fillers` | Extra filler words to cut, and words to always keep. |
| `cleanup_profile`, `confirm_policy` | How hard pauses and fillers are cut, and which cuts wait for a yes. |
| `language`, `asr_prompt` | Transcript language and terms that help recognition. |
| `llm` routes | Which AI handles planning, proofreading and copy for this client. |
| `delivery` | Posts per day, post times, and how many days after delivery the sources may be cleaned up (0 = never). |

## The QC report and the delivery

Every clip passes the automatic checks (loudness, lost words, caption sanity, platform length, title length, safe area, sync, black or frozen frames). `deliver` packages the approved clips into `delivery/<client>-<batch>-<date>/`:

- one folder per platform with the videos and their covers
- `文案.md`: title, body and tags per post, plus a reminder about AI-content labels
- `排期表.csv`: the posting schedule
- `交付说明.md`: counts, durations, platforms and QC notes
- `manifest.json`: a checksum of every file and a delivery code
- a zip, with `--zip`

`metrics` reports review time per clip, rework and red rates, and cost per clip, per batch or per client.

### Cleaning up after delivery

`cleanup-sources` is a dry run: it lists the exact files of deliveries past their cleanup date and a code. Only `--confirm-delete <code>` deletes, and only that list. Files outside the batch folder, such as the client's original recordings, are reported and never deleted.

## Example prompts

- "Set up a client called Acme: Xiaohongshu and Douyin, tight cleanup, their brand red #E4002B, and 'RAGFlow' is always spelled like that."
- "Start this week's batch for Acme from these three recordings."
- "Deliver the approved Acme clips as a zip with the schedule."
- "How long did review take per clip for Acme this month?"

## Related

- [A batch of 100+ videos](/docs/guides/batch-100/)
- [Batch engine reference](/docs/reference/engine/batch/)
- [Themes and brand](/docs/concepts/themes/)
- [AI providers](/docs/concepts/ai-providers/)
- [Projects](/docs/concepts/projects/)
