# PORT_NOTES - ai-video

## Sources (read-only)
- Two Claude Code sessions "视频投稿管道" (+ fork, same start): building a multi-platform publish pipeline for an
  AI two-character series, then producing a ~60 s mock-ad skit three ways (MiniMax agent, Kling via MCP shot by
  shot, Seedance in the 即梦 web UI via browser automation). Only user requests and assistant summaries were
  read; decisions, prices, failures and fixes were extracted.
- A local `dialogue-short-video` skill (SKILL.md / SKILL.cn.md / meta.yaml): production contract, natural-speech
  rewrite, continuity anchors, segment plan, per-clip review, minimal repairs, captions from final audio.
- A local publish folder (README, pipeline.py, publishers.py, series.yaml) and the project's generation /
  edit scripts (Kling MCP client, per-shot producer, judge rubric + sheet script, Seedance split/upscale,
  timeline-driven assembler).

## What was ported -> where
| Source | Here |
|---|---|
| dialogue-short-video steps 0-8 | WORKFLOW.md pipeline + references/PROMPTING.md |
| Kling MCP client + producer (keyframe -> video, state file, collect) | scripts/providers.py `KlingMCP`, scripts/generate.py |
| shots.yaml style/units/elements pattern | templates/project.yaml + scripts/plan.py (prompt rendering, units, snapping) |
| Seedance plan (timecoded segments, @refs) + split map | plan.py seedance template, PROVIDERS.md, WORKFLOW gotchas |
| judge_rubric.md + judge_clip.py | references/JUDGE_RUBRIC.md, scripts/judge.py (sheet, dense mode, scorecard, verdict) |
| upscale_seedance.py (ESRGAN 0.6 mix + grain) | scripts/upscale.py (+ ffmpeg-only fallback, any input size) |
| edit/assemble.py timeline | scripts/assemble.py (EDL -> master + cues; text overlays left to lib/HyperFrames) |
| publish pipeline.py / publishers.py / series.yaml | scripts/package.py + templates/series.yaml + references/PUBLISHING.md |

## Dropped / not ported (and why)
- All personal content: series name and episodes, scripts and dialogue lines, character descriptions of the
  creator, photos, voice sample, account names, project paths, music files. Examples are synthetic.
- The Kling client's token handling: it read and rewrote **another application's OAuth credentials in the macOS
  keychain** to reuse the MCP login. Not portable and not acceptable in a public tool; replaced by
  `KLING_MCP_TOKEN` from the environment or by calling the MCP tools inside Claude Code.
- `secrets/` (never opened), cookies, tokens, `publish/out`, `log.json`.
- `vendor/social-auto-upload` (MIT, 2023 dreammis): not vendored; `package.py` calls it as an external CLI via `$SAU_DIR`.
- Browser-automation recipes for 即梦 (coordinates, hidden file-input workaround, mention chips): too UI-version
  specific; the `manual` provider + prompt sheets replace them. Notes kept in PROVIDERS.md.
- The assembler's PIL text system (asterisk labels, phone pop-up cards, scrolling disclaimer) used macOS system
  fonts and project-specific layout; text overlays should come from `vstudio.draw/overlays` or HyperFrames.
- Local music synthesis script (project-specific score); use `vstudio.audio` beds with licensed music.
- macOS `pbcopy` / `open` in the manual publisher: replaced with printed instructions (cross-platform).

## Capabilities
tts (voice sample/clone handed to generators; lib `tts` for post VO), captions, bilingual, loudness, music,
cover (via workflows/cover), publish-copy, grade, upscale (other), ai-generation (other: provider adapters,
cost plan, spend gate), review rubric (other), series publishing / scheduling / confirm gate (other).

## Duplicates for phase 2
- `package.py:fit_cover` (blur-fill cover at a ratio) ~ `vstudio.export` cover fitting (`--cover` of another aspect).
- `package.py:youtube_uploader` / `sau_command` - first uploaders in the repo; candidates for `vstudio.publish` (upload adapters).
- `package.py:build_post` series line / previous-episode link / per-platform title format ~ `vstudio.publish.post_body`
  (could take `series=` and `prev_url=`).
- `judge.py:sheet` frame strip ~ `vstudio.media.contact_sheet` (needs a "N frames over the clip" + "big frames" mode).
- `assemble.py:segment_cmd` (fill-crop to canvas + silent-audio pad + concat) ~ vlog/photo-story assemblers,
  `cut.xfade_assemble`.

## Persona keys
None added. Possible later: `publish.series` defaults, `ai_video.default_provider`, `ai_video.budget_default`.

## Unverified / platform-specific
- `SeedanceArk` and `MiniMax` API adapters were written from public API shapes, **not exercised** in the
  sessions (both used web UIs). Endpoints, model ids and field names must be checked; tests use mocks only.
- Kling MCP: tool/argument names as observed on 2026-10-01 (mcp protocol 2025-06-18); max video duration and
  prompt length limits are conservative guesses (`CAPS` notes).
- Prices in `providers.RATES` are in-app credits seen on those days.
- YouTube `containsSyntheticMedia`, social-auto-upload flags (`--declaration`, `--tid`, `--collection`,
  `--schedule`) as used by the source scripts; not re-run here.
- `upscale.py --weights` needs torch; tested path is the ffmpeg fallback only.
