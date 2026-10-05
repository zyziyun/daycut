# Providers: what was used, what it cost, what went wrong

Recorded from two production sessions (October 2026) that made a ~60 s vertical English dialogue skit three
times: once with a MiniMax all-in-one agent, once shot-by-shot on Kling through its MCP server, once in
timecoded segments on Seedance (即梦 web UI). Prices are **credits as shown in-app on those days**; they change
often, and the in-app number before you press Generate always wins. Tags: **[S]** seen in the sessions,
**[U]** unverified (docs or general knowledge, check first).

## Summary

| Provider (model) | How it was driven | Strengths seen | Problems seen | Price seen |
|---|---|---|---|---|
| **Kling 3.0 Omni** (`kling-video-v3_0_omni`, `kling-image-v3_0_omni`) | Hosted MCP server `https://klingai.com/mcp` (OAuth), scripted with a small JSON-RPC client | subjects (主体/elements) keep a face across shots; first-frame -> video gives control; native dialogue audio | expression of the subject's cover photo leaks into every shot; extreme angles invent a new face; 401 when the token expires mid-batch; music generation produced only ambience | video 1080p 5 s = 60 (48-72 per clip); keyframe images ~2 each (4 for 8) [S] |
| **Seedance 2 / 2.5** (即梦 web) | Browser automation of the web UI (Chrome extension) | up to 12 refs (image/video/audio) per generation; up to 15 s with several shots via in-prompt timecodes; voice ref as audio | real cut points differ from the prompt timecodes; a newline typed into the prompt box submitted the form (one accidental paid submit); a small "AI生成" label is burned into outputs | draft (样片) 480p ~9/s (5 s = 45 discounted, 12 s ~108); upgrade draft -> 正片 ~64/s (~7x); 720p ~8/s, 1080p ~11/s; Seedream images 8 each [S] |
| **MiniMax** (Hailuo / agent app, image "Design") | Web app, uploaded a package (4 photos, voice sample, style reference video) and one long brief for the whole film | good look sheets from own photos; fine on shots without people | a 24-shot film in one pass lost the premise (key spatial relation never shown), swapped a shot for the reference photo, a fall became a bird, faces drifted between halves, burned text cropped/ghosted | not recorded [U] |
| Vidu, Wan (通义万相), Veo 3.1 | researched only | Vidu: reference-to-video, cheap; Wan: cheapest, fine for shots without people; Veo: best English dialogue | - | third-party price lists only [U] |

**Decision that held up:** one character = one model for the whole film (mixing models for the same face
reads as "this person changed"). Shots without faces (screens, props, aerials, establishing) can go to the
cheapest model or be reused from an earlier version.

## Kling via MCP (the path that worked end to end)

1. Add the server once (Claude Code): `claude mcp add --scope user --transport http kling https://klingai.com/mcp`,
   then authorise in `/mcp`. Tools load **at session start** - open a new session after adding it.
2. Call `who_am_i` first: it returns how to fill `model`, `arguments` and `inputs` for each tool. Then
   `query_membership_and_credits` (`availableRemainCredits`).
3. Generation tools take `{"model", "arguments": [{"name", "value": "<string>"}], "inputs": [{"name": "image_1",
   "inputType": "URL", "url"}], "rationale"}` and return `generationId` + `creditsConsumed`. Local files go
   through `file_upload` (ticket + multipart POST) first. Poll `query_tasks {"generationId"}`; download
   `works[].urlWithoutWatermark`.
4. Subjects: create from an approved look sheet (`element_create`), reference in prompts as `<<<element_id>>>`
   with `arguments.elements = [{"id", "bindName"}]`; reference images are called `图片1`, `图片2` in prompts.
5. Video arguments used: `duration` 4-6, `aspect_ratio` 9:16, `resolution` 1080p, `imageCount` 1,
   `enable_audio` true/false. Image arguments: `img_resolution` 2k, `aspect_ratio`, `imageCount` 3-4.
6. Inside Claude Code, prefer calling the `mcp__kling__*` tools directly; `scripts/providers.py KlingMCP`
   is for batch scripts and needs `KLING_MCP_TOKEN` in the environment. **Do not** pull the OAuth token out
   of another application's keychain entry to script it (the session did; it is not portable and not ours to read).
7. The MCP server's own rule matches ours: every job is charged, no trial jobs, ask before retrying or changing
   parameters after a failure or timeout.

## Seedance in the 即梦 web UI (manual provider)

- Settings per segment: 9:16, duration = segment length (4-15 s), draft mode (样片) first.
- Refs: look sheet A as `@图片1`, look sheet B as `@图片2`, a short voice sample as `@音频1` (timbre only).
  "@" chips are inserted from the mention menu, not typed as text.
- Write the whole prompt on **one line** with `【0-2.5秒】...【2.5-4.5秒】...` blocks. A newline can submit.
- After download, cut by **scene detection + word timestamps**, not by the prompt's timecodes
  (`split` positions moved by up to ~0.5 s per shot). Keep a map `segment -> [(shot, start, length)]`.
- Drafts were upscaled locally (`scripts/upscale.py`: 60 % Real-ESRGAN + 40 % bicubic + grain) instead of
  paying the ~7x upgrade; fine for phone viewing, softer than a true 1080p render.
- Free tier outputs are watermarked; publishing needs a paid plan (third-party guides) [U].

## MiniMax all-in-one agent (what not to do)

Asking one agent run for a complete multi-shot film produced a watchable but incoherent cut. If you use it,
keep its usable shots (cut the clean, caption-free version at scene changes), regenerate only the broken shots
elsewhere, and add all text in post. Prepare uploads: images <= 1024 px long edge (`generate.py prep-refs`;
"some image too large" otherwise), reference videos < 100 MB (re-encode to 720p), and say in the brief that a
style reference is for pacing only ("do not reuse its footage, characters, text or audio").

## Planning credits

- Count units, not shots: same set-up shots share one generation (`unit:` in the project file).
- Add a 30-50 % retry allowance for hard shots: two people in one frame, someone hanging/falling, collapses,
  objects that must stay in a specific hand.
- Generate the hardest shots first (`generate.py run --only`); if they fail, change the plan before spending on the rest.
- Keyframes (first frames) are ~25x cheaper than video on Kling: approve the first frame, then animate it.
- Observed totals: a 24-shot, ~60 s Kling film used ~1400 credits across two full passes; a 5-segment Seedance
  draft film ~800 credits of drafts plus two redos.
