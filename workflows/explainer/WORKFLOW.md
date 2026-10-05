# explainer — 3Blue1Brown-style concept videos

**Use when:** someone wants a math/ML/concept explainer "in 3b1b style", or a concept explained step by step for a
beginner, with AI narration and bilingual subtitles. **Inputs:** a topic (plus optional notes). **Outputs:** a 5–12 min
16:9 MP4 with colour-coded animated math, EN narration, burned EN/中文 subtitles, transitions, music bed, `.srt` files —
or a **60–120 s vertical short** (9:16 1080×1920 or 3:4 1080×1440, laid out per platform; see "Vertical short").

Built on **HyperFrames** (HTML → video). Worked example in `example/` (model quantization, 10:33, 18 scenes).

## Prerequisites

- HyperFrames skills installed (`/hyperframes`, `/hyperframes-core`, `/hyperframes-animation`, `/hyperframes-audio`, `/media-use`) and `npx hyperframes` working. Route fresh creation through `/hyperframes` first (it writes `BRIEF.md`); this skill is the `general-video` playbook for this genre.
- `ffmpeg`, Python 3 with `fonttools brotli`.
- `OPENAI_API_KEY` (narration ≈ $0.015/min with `gpt-4o-mini-tts`).
- Optional: HeyGen CLI logged in (`heygen auth login --oauth`) for the music catalog.
- A CJK font you may redistribute (Noto Sans SC / Source Han Sans, OFL) and STIX Two Text (OFL, Google Fonts) in `assets/fonts/`.

Scripts live in `$VSTUDIO/workflows/explainer/scripts/`. Every path they read/write is relative to the project dir: run them from the **project root**, or pass `--project <dir>` (`-C`) from anywhere. Below, `scripts/` means that folder. They use the shared library in `$VSTUDIO/lib/vstudio` (TTS cache, two-pass loudnorm, ASR, SRT writer, font subsetting).

## The pipeline

Each numbered stage ends at a user checkpoint unless the user said "just build it".

### 1. Brief (ask once, recommend defaults)
Length (default 5–7 min; "everything" topics run 10), destination → 16:9 (YouTube / B站) or a vertical short (小红书 / 抖音 / Shorts → "Vertical short" below), sketches first (yes), subtitle layout (burned EN top / 中文 below + .srt). Voice: pick for the user, send a 10–15 s sample before the full run.

### 2. Script → `SCRIPT.md` (+ drafts of the storyboard and cue pairs)
Format: `## Line N — <label> (Frame N)`, optional `**Delivery:**`, the spoken English as a 4-space indented block, then `ZH: <中文>`. One line = one scene.
- Spell numbers the way they should be **spoken** ("zero point five one", "F P thirty-two"); subtitles convert them back to digits later.
- Teaching shape that works: hook (a concrete number) → everyday intuition → what is stored → the core picture (one image) → **one worked example carried through 3–5 scenes with the same numbers** → why it doesn't hurt → types/variants → real tools → trade-offs → recap.
- Verify every number in the worked example yourself before writing it; write them at the top of SCRIPT.md as the example's ground truth.
- ≈ 175 spoken words/min for OpenAI `cedar` at speed 1.0 — measure from the sample, don't guess.

Then draft instead of writing from scratch (both only propose; you edit and verify):
```bash
python3 scripts/storyboard_from_script.py        # → STORYBOARD.md + scenes.config.json (or *.draft.* if they exist)
python3 scripts/pair_cues.py                     # → subtitles/cues.draft.txt (EN chunk || 中文, "# check:" flags)
```
`storyboard_from_script.py`: one scene per line (`fNN-<slug>` ids, a varied transition cycle), a shot sequence
with one beat per cue (scene-local time + trigger words + a hint: numbers to reveal, equation to build, question,
contrast, step; every hint ends in TODO), STORYBOARD.md frames with durations and suggested motion tags. Before
the voice exists, times are estimated at `--wpm`; after step 5 re-run `--force --keep-shots` to refresh ids /
timing without losing your edited shots, or `--force` to re-draft the beats on the **real cue times**.
`pair_cues.py`: splits EN into clauses and 中文 into clauses, then a monotone DP groups them by length ratio +
punctuation agreement + caption limits (canvas-aware). On `example/` it reproduces 78 % of the hand-made cue
boundaries; flagged pairs (`# check: ratio / punct / long`) and every pair's meaning still need a look
(e.g. a "Four bits gives sixteen." that lands one cue early). align_cues.py ignores the `# check:` comments.

### 3. Sketches → `storyboard.html` (+ `storyboard/sketches/fNN.svg`)
One static 1920×1080 SVG per scene at its most complete moment, drawn with the real fonts/colours/copy, plus the subtitle band as a stand-in. Generate the sheet from a Python script (see `example/make_storyboard.py`), rasterize with `rsvg-convert`, and **look at every frame at full size** before showing the user (overlaps, clipped text, emoji that don't render). Present a frame table in chat; revise only frames the user names.

### 4. Voice
```bash
python3 scripts/tts.py --voice cedar            # → audio/vo/lineNN.wav (cached per line; --fresh = new take)
python3 scripts/concat_vo.py --gap 0.7          # → audio/narration.wav (-16 LUFS, two-pass, 48 kHz stereo) + audio/vo/offsets.json
npx hyperframes transcribe audio/narration.wav -l en -m small.en   # → audio/transcript.json
#   or, without node: python3 scripts/transcribe.py --model mlx-community/whisper-small.en-mlx
#   (vstudio.asr: mlx_whisper → faster_whisper → OpenAI whisper-1; same transcript.json shape)
```
QA: diff the transcript against SCRIPT.md per line (difflib ratio < 0.9 → inspect). Number formatting diffs are fine; missing words are not.

### 5. Bilingual subtitles
Start from `subtitles/cues.draft.txt` (pair_cues.py), fix it, save as `subtitles/cues.txt` — EN chunks (≤ ~90 chars) paired with their 中文 (≤ ~38 chars). Machine sentence-splitting does **not** pair EN↔ZH. Add project acronyms/formulas to `subtitles/display_rules.json` (see example).
```bash
python3 scripts/align_cues.py          # → subtitles/cues.json, en.srt, zh.srt
python3 scripts/scene_windows.py       # → audio/scenes.json, audio/scene_cues.json
python3 scripts/subset_cjk_font.py ~/.cache/video-studio/fonts/NotoSansSC-Regular.otf --out assets/fonts/subtitle-cjk-w3.woff2
python3 scripts/subset_cjk_font.py ~/.cache/video-studio/fonts/NotoSansSC-Bold.otf --out assets/fonts/subtitle-cjk-w6.woff2
python3 scripts/make_captions.py       # → compositions/captions.html
```

### 6. Build scenes
1. `npx hyperframes init <dir> --non-interactive --example=blank --skill=general-video`; copy `references/design-truth.md` → `frame.md`.
2. Edit `scenes.config.json` (ids, transitions, **time-coded shot sequences using the real cue times** from `audio/scene_cues.json`; the storyboard draft gives you the skeleton), then `python3 scripts/make_packets.py`.
3. Build ONE scene yourself from `assets/reference-scene.html`, assemble, `npx hyperframes lint` + `snapshot`, fix — then hand the rest to parallel workers (2–3 scenes each, one wave) with `_role.md` (HyperFrames frame-worker core + general-video delta), `references/frame-worker-dispatch.md`, their packets and sketches.
4. `python3 scripts/make_index.py --patch-scenes`, `npx hyperframes check`, snapshot every scene at ~85 % of its window and **mid-transition**, read the images.

### 7. Music + mix
```bash
npx hyperframes media-use resolve --type bgm --intent "calm minimal ambient, whiteboard explainer" --project .
python3 scripts/make_bgm_bed.py .media/audio/bgm/bgm_00N.wav     # loop + level → audio/bgm.wav (-30 LUFS)
python3 scripts/make_index.py
node <hyperframes-audio>/scripts/carve.mjs --comp index.html --bed bgm --voice narration --strength 0.8
```
Choose the steadiest candidate (lowest LRA, "no percussion"). Carve needs `npm i -D @hyperframes/core@<pinned version>`.

### 8. Preview → render
`npx hyperframes preview --background`, hand over the Studio URL, render only on approval:
`npx hyperframes render -o renders/<name>.mp4 -q looks`. Verify the file: duration, streams, integrated loudness (≈ −14 to −16 LUFS), a few extracted frames.

## Vertical short (9:16 / 3:4, 60–120 s)

Set the canvas once in `scenes.config.json` — `"platform": "xiaohongshu:full"` (9:16), `"douyin"`, `"youtube-shorts"`,
`"tiktok"` or `"xiaohongshu:vertical"` (3:4, 1080×1440) — plus `"mode": "short"`; or pass `--platform` to
`storyboard_from_script.py`, which writes both keys. Every script reads it (`scripts/canvas.py`, from
`vstudio.platform`); no key or a horizontal profile = the 16:9 layout above, byte-identical to before.

| | 16:9 explainer | vertical short |
|---|---|---|
| length / scenes | 5–12 min, 12–18 scenes | 60–120 s, **5–8 scenes**, each ≤ ~14 s |
| shape | hook → intuition → … → recap | **hook in the first 2 s** (a number or a question, first visual on screen by 0.3 s) → one core picture → **ONE worked example** (2–3 scenes, same numbers) → one-line payoff |
| script | ~175 wpm, full sentences | same voice, ~10 % faster (`tts.py --speed 1.1`, `concat_vo.py --lead 0.1 --gap 0.4`), first sentence ≤ 6 words, cut every aside |
| pacing | reveal per cue, 6 px drift | reveal every 2–4 s, entrances 0.35–0.6 s, fast transitions (push / fade / vpush / zoom ≤ 0.4 s), tail 1.2 s |
| design truth | `references/design-truth.md` | `references/design-truth-portrait.md` → `frame.md`: math in the upper safe area, stacked not side by side, bigger type (title 56, math 72–120, mono 34–64) |
| reference scene | `assets/reference-scene.html` | `assets/reference-scene-portrait.html` (f07 re-laid out for 1080×1920, inside the portable 9:16 area) |
| captions | EN 38 / 中文 34 band y > 840 | the profile's caption box, bottom-anchored, EN 38 / 中文 48 (from the band height), balanced wraps; cues over 2 lines per language are reported → keep EN ≤ ~60, 中文 ≤ ~24 |
| sketches | 1920×1080 SVG | canvas-size SVG; the caption-band stand-in sits in the profile's band |

SHORT pipeline (same scripts, run from the project root):
```bash
python3 scripts/storyboard_from_script.py --platform xiaohongshu:full --mode short   # warns: scene count, hook > 2 s, total > 120 s
python3 scripts/pair_cues.py                       # caption limits of the vertical box
python3 scripts/tts.py --voice cedar --speed 1.1 && python3 scripts/concat_vo.py --lead 0.1 --gap 0.4   # voice starts at 0.1 s
python3 scripts/transcribe.py                      # or npx hyperframes transcribe
python3 scripts/align_cues.py && python3 scripts/scene_windows.py                     # tail 1.2 s; warns > 14 s scenes, length vs platform
python3 scripts/storyboard_from_script.py --force --keep-shots                       # refresh STORYBOARD timing
python3 scripts/make_captions.py && python3 scripts/make_packets.py                 # packets carry the canvas json + safe/caption/math boxes
#   build scenes from assets/reference-scene-portrait.html, then:
python3 scripts/make_index.py --patch-scenes && npx hyperframes lint && npx hyperframes snapshot --at <85 % of each scene>
```
Check every snapshot against the boxes printed in the packets (captions inside the caption box, nothing in the
lower-right button column, nothing above the safe top). One build per canvas: a 9:16 build ships to 小红书 full /
抖音 / Shorts / TikTok if the scenes stay inside the **portable 9:16 area** (design-truth-portrait.md); 3:4 needs its
own build (different height). Deliver with `python3 -m vstudio.export renders/short.mp4 --platforms
xiaohongshu:full,douyin,youtube-shorts --out exports/ --cover cover.png` (same aspect → plain scale + per-platform
loudness, encode, cover and post stub). Never reframe the 16:9 film into 9:16 — the math and captions would be cut.

## Platforms (16:9)

`"platform": "youtube"` / `"bilibili"` keeps the 16:9 layout; scene_windows.py then also prints the platform's
length guidance. Multi-platform delivery of the 16:9 render:
`python3 -m vstudio.export renders/<name>.mp4 --platforms youtube,bilibili --out exports/ --cover cover-16x9.png`
(captions are part of the HyperFrames design, so pass no `--cues`; the .srt files go to the platform's subtitle upload).

## Hard-won rules
Read `references/pitfalls.md` before building — every item there cost a failed check or a blank render once.
Transition menu and how they are wired: `references/transitions.md`. The 11 transitions are generated by
`vstudio.hf.scene_transitions` (any HyperFrames project can use them on its own wrapper ids); all effects:
`$VSTUDIO/references/EFFECTS.md`.
