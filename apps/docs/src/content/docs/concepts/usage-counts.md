---
title: 'Privacy: what Reelfold sends'
description: The Mac app can share anonymous usage counts, only if you turn it on. Every field it sends, how to turn it off, and how to delete what was sent.
---

The Reelfold Mac app can share a few anonymous counts with us, such as "a batch of 12 clips finished". It is **off unless you turn it on**, at first run or in **Settings › General › Privacy › Share anonymous usage counts**. While it is off, nothing is sent, ever, and no ID is created.

We use the counts for one thing: knowing how many people actually use Reelfold (installed it and finished a batch), so we can keep it free and find people to learn from.

## Every field that is sent

One event is a small JSON object posted over HTTPS to `https://t.reelfold.com/api/v1/ping`:

| Field | Example | What it is |
|---|---|---|
| `id` | `6f1c…-…` | A random ID made on your computer the first time you turn sharing on. Not tied to your name, email, Mac or Apple ID. You can replace it at any time. |
| `v` | `0.2.0` | The app version. |
| `os`, `arch` | `darwin`, `arm64` | The operating system and processor type. |
| `locale` | `zh-CN` | The app's interface language (English, 简体中文 or Français). |
| `ev` | `batch_done` | The event name, one of the five below. |
| `day` | `2026-10-14` | The day it happened (UTC). No time of day. |
| `n` | `{ "clips": 12 }` | Small whole numbers, only for the events listed below. |

| Event | When | Numbers |
|---|---|---|
| `app_open` | The app is open (at most once a day) | none |
| `first_batch_done` | Your first finished batch (once) | none |
| `batch_done` | A batch or project finished | `clips`, and when known `formats` and `minutes_in` (rounded) |
| `export_done` | Clips exported or delivered | `count` |
| `publish_package` | A publish package was made | `platform_count` |

That is the complete list. The app never sends file names, folder paths, titles, captions, transcripts, prompts, AI provider names or keys, publishing accounts, or anything from your footage. Batches run in the demo engine are not counted.

## What the server keeps

- Exactly the fields above, plus the server's own date. **Your IP address is not stored or logged**; it is only held in memory for about a minute to rate-limit requests. No cookies, no user agent, no device fingerprint.
- Anything that is not in the table is dropped before storage; an event with an unexpected value is dropped whole.
- Raw events are deleted after **13 months**. Daily totals without any ID (for example "40 clips made on 14 October") are kept.
- The data is stored in Cloudflare D1 (Cloudflare Workers) and is read only by the Reelfold maintainer, as totals.

The server code is open: [`apps/telemetry`](https://github.com/zyziyun/reelfold/tree/main/apps/telemetry), and the app side is [`apps/desk/src/main/usage.ts`](https://github.com/zyziyun/reelfold/blob/main/apps/desk/src/main/usage.ts).

## How it is sent

From the app's background process, with a short timeout; it never slows down or blocks the app. When you are offline, events wait on your computer (in the app's profile folder, `usage.json`) and go out with the next one; events older than 13 days are dropped instead. Development builds, automated tests and CI never send anything.

## Turn it off

**Settings › General › Privacy** → switch off **Share anonymous usage counts**. Anything still waiting to be sent is discarded at once.

## Delete what was sent

**Settings › General › Privacy › Delete my usage data** asks the server to delete every event of your current ID (`DELETE https://t.reelfold.com/api/v1/installs/<id>`), then gives you a new ID. Daily totals that contain no ID stay. **New ID** alone starts fresh without deleting.

If you no longer have the app, contact us (address in the [privacy policy](https://reelfold.com/privacy/)) with your ID if you still have it; without the ID the events cannot be linked to you.

## The skill and the website

- The Claude Code skill (`video-studio`) sends no usage data at all.
- The website and these docs may count page views with [Cloudflare Web Analytics](https://www.cloudflare.com/web-analytics/), which uses no cookies and stores no personal data.

## Related

- [Privacy](/docs/concepts/privacy/)
- [Privacy policy](https://reelfold.com/privacy/)
