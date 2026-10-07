---
title: Publishing
description: Reelfold publishing is assisted. The app opens each platform's upload page, fills in the file and copy, and you press publish. It never posts alone.
---

Reelfold helps you post, but it never posts on its own. The Mac app opens the platform's own upload page in its built-in browser, sets the video file and types the title, text and tags. You check everything, make the choices only you should make, and press publish yourself.

## Why it matters

A post is public and goes out under your name. The last look should be yours: the right account, the right category, the AI-content label, the audience. Assisted publishing removes the tedious part (dragging files, pasting copy, retyping tags for each platform) and keeps the part that matters with you. It also works on platforms that have no public posting API at all, which includes most Chinese platforms.

## How it works

1. **One persistent login per account.** You sign in to each platform once inside the app's browser. The app never stores your passwords or cookies itself, and when it detects a login page it stops filling.
2. **Fill.** For each post, the app opens the upload page, sets the video file and types the title, body and tags where the page allows it.
3. **You publish.** You review, set category, audience, AI label, subreddit or board as needed, and press the platform's publish button. The app may outline that button; it never clicks it. There is no way to express a click in an adapter.
4. **Posted.** Reelfold watches the page after your click; when the platform confirms, the post is marked posted, with its link when the page shows one. You can also mark it by hand.

Scheduled posts are not just calendar entries: at each post's time Reelfold sends a "Time to post" notification, and clicking it opens the filled upload page. Posts that came due while the app was closed wait at the top of Publish. See [How scheduling works](/docs/guides/scheduling-publishing/#how-scheduling-works).

Each platform's fill steps live in a small adapter file. You can add or override adapters without rebuilding the app, in `~/Library/Application Support/Reelfold/adapters/`. Adapters written without a live session are marked unverified until someone checks them against the real page.

### Official APIs: opt-in only

A few platforms have an official upload API. In the Mac app you can connect one yourself in **Settings › Publishing › Post automatically** (YouTube today, with your own Google Cloud OAuth client; TikTok, X and Instagram are documented but not available yet). Only then do that platform's scheduled posts go out on their own. Sign-in happens on the platform's page in your system browser, the permissions are shown first, and tokens stay in the macOS keychain. With the skill, you turn one on explicitly in a series or project file (`uploader: <name>`), with credentials kept outside the repo, and each upload requires the confirm code of the exact package you reviewed.

### Without the Mac app

With the skill alone, `uploader: manual` gives you the upload page, the steps, the caption text, the cover and a checklist for each post.

## Platform notes

- **Xiaohongshu, Douyin, WeChat Channels, Bilibili, Kuaishou, Weibo, Zhihu:** assisted fill on the creator upload page. Each has an AI-content declaration toggle; tick it yourself when it applies.
- **YouTube:** one channel, long-form and Shorts. A Shorts upload must be vertical or square and at most 3 minutes.
- **Reddit:** you type the subreddit; a title is required and can't be edited later. Read the community's rules on self-promotion first.
- **Pinterest:** the link goes in the destination-link field, never the description. You pick the board.
- **Snapchat Spotlight:** 5 to 60 seconds, 9:16, no watermarks.
- **Kwai:** no desktop web upload; you get a package to post from the phone app.

## In the Mac app

Publish shows your week. Each approved clip has its post copy ready; open it, check the filled page, press publish, then mark it posted.

## With the Claude Code skill

Exports and packages come with covers, post copy and a schedule. Nothing is uploaded unless you have turned on an official API as described above; otherwise you post from the package yourself, or open the project in the Mac app for assisted fill.

## Related

- [Scheduling and publishing guide](/docs/guides/scheduling-publishing/)
- [Platforms reference](/docs/reference/platforms/)
- [Publishing engine reference](/docs/reference/engine/publishing/)
- [Privacy](/docs/concepts/privacy/)
