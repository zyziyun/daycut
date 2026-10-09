# Changelog

All notable changes to Reelfold (the Mac app, the engine and the Claude Code skill) are listed here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/) (pre-1.0: minor versions may change behaviour).

App releases are tagged `v*`; engine-only releases are tagged `engine-v*`.

## [Unreleased]

### Added

- **Archive projects** (Mac app): 「Remove from list」 is now **Archive** (归档 / Archiver) in a project's menu and in
  bulk select, with an undo toast. An **Archived** tab at the end of All projects shows archived projects dimmed with
  their archive date and a **Restore** button (single or bulk); search and type filters work there, and an archived
  project still opens. Nothing on disk is deleted, and a project with a run going is never archived. Engine:
  `POST /api/history/archive` / `restore` (`{dir}` or `{dirs}`), `GET /api/history?archived=1`.

## [0.2.2] - 2026-10-08

### Added

- **Promo template**: `pip:` windows (screen full-screen, speaker tile bottom-right), card `scene:` kinds (tiles,
  flow, bars, stat, toast, ranking, columns, checklist, swatch) and card `video:`, a `hooks:` montage at the start,
  `crop: auto` that removes browser bars from screen recordings, and a footage map printed at build.
- Live progress while a plan is made; an agent's live status on the project page.
- **Watermark**: your handle, your own PNG logo, or a logo generated from your handle (drawn locally) on every
  export. Settings › Watermark in the Mac app has live previews on a 9:16 and a 16:9 frame, a corner picker, size,
  opacity, per-platform switches and "Add to every video by default"; the Export card can turn it off for one video.
  The mark sits inside each platform's safe area and above the captions. Off until you set it up.
  Engine: `python -m vstudio.watermark`, `--watermark on|off` on `vstudio.export` and `output render`, and
  `watermark: false` per batch job; settings in `$VSTUDIO_HOME/watermark.json` or persona `watermark:`.

### Fixed

- Attached recordings and folders are kept as promo-recut b-roll instead of being dropped by the planner.
- Author checkpoints show their label, help and file instead of a bare "1 0"; Review lists waiting checkpoints.
- Large plans give Claude Code enough time; a nested `claude -p` no longer attaches to a host Claude Code session.
- Rendering picks a Node.js that runs; delivery creates its output folder; stage errors keep the real stderr;
  external-tool failures say which tool and how to fix it.
- The app reads the creator's persona; covers no longer warp faces; CJK quotes no longer render as tofu.
- `project touch` on a recipe project only writes live status (it no longer drops the project from the list).
- Delivered audio is exactly as long as the picture; montage length is verified; captions never overlap.
- Talking-head speed caps allow a persona's 1.5x body / 2x hooks.

## [0.2.1] - 2026-10-07

### Changed

- Talking-head jobs default to the notes look, with keywords you review before the render.
- The Mac App Store (Lite) build names no other download and links nowhere; its limits are explained neutrally.

### Added

- A draft post title and body for each clip, written from the final captions.

## [0.2.0] - 2026-10-07

The first public release: the macOS app for Apple silicon, signed with a Developer ID and notarized by Apple, plus
an unsigned Windows x64 preview installer. Nothing before it was published as a release; the earlier history lives
in the commit log (formerly `video-studio` and `Daycut`).

### Added

- **Mac app (Reelfold · 千剪)**, MIT, in `apps/desk`:
  - Home composer: describe the job in one sentence and drop the footage; AI proposes a plan card with an estimate,
    then runs a pilot before the full batch.
  - Projects of many clips running in parallel, an inbox that shows only what needs you, and an All work view of
    batches, projects and skill work folders.
  - Chat-first clip editor: big player, a chat column that proposes changes as cards, a timeline with a scrub bar,
    selective undo of one earlier step, before/after compare.
  - Project-level "edit with AI" across every clip at once.
  - Assisted publishing: the upload page is filled in per platform and you press publish (never auto-posts).
  - AI accounts: sign in with your Claude Code or Codex subscription, an API key, or a local model, and switch per task.
  - First-run wizard with queued model downloads; bundled Python runtime and LGPL ffmpeg; auto-update.
  - UI in English, 中文 and Français.
  - Create page (behind a setting): series studio with formats, bible, storyboard and a spend gate.
  - A week of posts in one step: drop this week's footage on Home or Publish; Reelfold plans and makes every clip,
    then lays them out over the week (your words, else each account's usual time, else the platform's rhythm) as a
    preview you confirm with one button.
  - Send feedback (Help menu, Settings, empty states) and Report this problem (failed jobs, crashes): a redacted
    report you read first, opened as a prefilled GitHub Discussion or Issue. Nothing is sent by the app; automatic
    crash reports are off by default.
  - First run in minutes: a built-in sample recording (CC0) and a path that works without any AI account.
  - Transcript editing: cut by words in the transcript, suggestions in the chat, space plays a selection.
  - Publish as a week board with a drawer, plain-language planning, reminders and fill-in of each upload page.
  - Plugins on the Create page: board importers (HyperFrames, CSV / JSON shot lists) and agent runners that make
    shots in parallel lanes, each in its own job folder, with takes and Inbox items for failures.
  - Optional anonymous usage counts, asked once and off until you agree.
- **Windows x64 preview** (unsigned NSIS installer `Reelfold-<v>-win-x64-setup.exe`, attached to the release): the app, its engine sidecar
  and the bundled runtime run on Windows (Media Foundation or OpenH264 for H.264, faster-whisper for speech).
- **Engine**:
  - `vstudio.intake`: one sentence plus the material becomes a validated plan (rule fallback when no model is set).
  - `vstudio.project`: every workflow is a recipe with checkpoints, series, inbox and publishing calendar.
  - Batch orchestration: segment planning, client workspaces, job edits with stale-stage reruns, delivery packages,
    metrics, caption proofreading with a cache.
  - Clip-level editing (`project output list|show|edit|render|undo|redo|ai|effects`) with a cached stage render.
  - `vstudio.llm`: one interface for Anthropic, OpenAI, OpenAI-compatible servers (DeepSeek, Qwen, Kimi, GLM,
    OpenRouter, Ollama…) and the Claude Code / Codex CLIs, with per-route fallback chains and timeouts.
  - ASR and TTS backend registries, including self-hosted Whisper servers.
  - `vstudio.formats` (defaults per recurring format) and `vstudio.firstpass` (a check before every handover:
    audio, resolution, speed, loudness, first frame, caption terms, cover).
  - Named-entity verification after ASR (place names and cities).
  - One design-theme system for every overlay (editorial default).
  - Recipes for teachers and interview / podcast creators: `lesson-clips` (a lesson cut by teaching point, with
    "Today's phrase" title cards, key-term cards, a recap and study notes in Markdown / PDF; a screen share and a
    camera synced by sound, with screen / picture-in-picture / band layouts) and `interview-qa` (question and answer
    clips that open on the question, tight answers, speakers by role, optional face masks).
  - Bilingual captions (`vstudio.bilingual`): the spoken line plus a translated second line in the theme's
    secondary ink, or the translation only; glossary enforced; per-language SRT / VTT with every export.
  - Launch kits (`vstudio.launch`, `launch-kit` recipe): product launch videos from screen recordings and a
    Playwright capture, with idle stretches speed-ramped, gallery stills, a music bed and per-platform post copy.
  - Studio sound (speech clean-up) and a license-free music library shared by every recipe.
  - Share for review: a page a client can comment on, and the feedback imported back as edits.
  - Plugin registry (`vstudio.plugins`): manifests, permissions, cost kinds; paid plugins only run through the
    spend gate.
- **Platforms**: 20 profiles, each with its own canvas, safe zones, caption box, length, loudness, cover and copy
  limits: YouTube, YouTube Shorts, TikTok, Instagram, X, Facebook, LinkedIn, Threads, Reddit, Pinterest, Snapchat
  Spotlight, Dailymotion, Kwai, 小红书, 抖音, 视频号, B站, 快手, 微博, 知乎.
- **Docs site** at [reelfold.com/docs](https://reelfold.com/docs/) in English, 中文, Français and Español; reference
  pages generated from the engine sources.
- **Website** at [reelfold.com](https://reelfold.com) in four languages.
- Repo: CONTRIBUTING, Code of Conduct, security policy, issue and pull-request templates, roadmap, this changelog.

### Changed

- Renamed to **Reelfold (千剪)**. The repo moved from `zyziyun/video-studio` and `zyziyun/daycut` (old URLs
  redirect). The Claude Code skill keeps the name `video-studio`, and existing installs keep working.
- Monorepo: the engine and skill at the root, the app, website and docs under `apps/`.
- SKILL.md rewritten as a five-step job flow with one routing table.
- Source recordings are never deleted automatically; delivery cleanup is off by default.
- One cache root, `~/.cache/video-studio` (the legacy `~/.cache/vstudio` is still read).
- English is the default language for the app and the website.
- Talking-head projects default to the creator's look: 记笔记 panels, progress-bar chapters and highlighted keywords
  drafted from the clip by the routed text model, strict filler cleanup, 1.25x body / 1.5x hooks from the
  `talking-head` format (one source for the recipe, intake, the desk and the compose scripts; persona
  `formats:` overrides it), a retouched cover, and the hook menu on the default engine too.

### Fixed

- The bundled macOS runtime ships every engine dependency: babel, pypinyin and jsonschema were missing, so in the
  app the named-entity check found nothing and plan / recipe validation fell back to key checks. The runtime build
  and the packaged-app tests now check every package of `requirements.txt`.
- Agent-runner lanes no longer shrink to one on machines with few cores.
- Create: Send to Publish finds an assembled episode also when its folder is reached through a symlink
  (`/var` and `/private/var` on macOS).
- Windows preview: the engine no longer stops answering right after it starts (numpy is loaded before the engine
  starts any thread).
- Projects resume after their last Inbox answer; a run waiting at a checkpoint is listed once; waiting and
  interrupted jobs show on the project board.
- The engine is restarted when it dies after start (never while the app quits), and engine errors are translated
  instead of shown raw.
- Media is served with byte ranges (seeking works), also through symlinked folders.
- English transcripts keep spaces after punctuation and between English words; English sub-word tokens are joined in
  Chinese transcripts; captions split on word boundaries with one shared line breaker.
- Proofreading needs ASR evidence before changing an English word and keeps the glossary off common words.
- Cover runs close their face landmarkers (no deadlock); captions stay clear of talking-head note cards.
- AI fallback works on every path (segment planning, proofreading, chat edit), Codex gets a strict JSON schema,
  and an all-attempts error says what was tried.
- Chat edits always answer; the capability probe no longer misses `--context`.
- Pilot and project failures are visible, with a retry; planning can be stopped.
- Filler cuts keep the word they trim in the captions; AABB reduplication (起起落落) is no longer cut as a stammer.
- A dropped word's tail cut in promo recuts no longer runs into the next word.
- Burned-in finished edits default to the band layout (old captions cropped, new ones below).
- A 9:16 小红书 export gets a 9:16 cover (the 3:4 cover is only for the 3:4 version); the feed's centre 3:4 is
  previewed.
- Post titles fit each platform's title limit when they are written (deterministic shortener, reported in the
  export warnings); exports draft a title when none is given, and the first-pass check no longer reads the hashtag
  line as the title.
- Talking-head posts are no longer empty when you write no copy: a title and a short body are drafted from the final
  captions (your AI account in your voice, else lines you say), fitted to every platform's title limit and shown in
  the review as a draft to edit. Your own title and body are kept.

### Security

- Electron fuses on the packaged app (no run-as-node, no `NODE_OPTIONS` / `--inspect`, asar integrity), hardened
  runtime and notarization.
- API keys in the OS keychain; every IPC call validated; the local engine needs a per-session token.
- No silent mock engine or demo mode in the product: a packaged app always runs the real engine.

[Unreleased]: https://github.com/zyziyun/reelfold/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/zyziyun/reelfold/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/zyziyun/reelfold/releases/tag/v0.2.0
