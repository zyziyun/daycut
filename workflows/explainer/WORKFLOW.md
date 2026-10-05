# explainer — 3Blue1Brown-style concept videos

**Use when:** someone wants a math/ML/concept explainer "in 3b1b style", or a concept explained step by step for a
beginner, with AI narration and bilingual subtitles. **Inputs:** a topic (plus optional notes). **Outputs:** a 5–12 min
16:9 MP4 with colour-coded animated math, EN narration, burned EN/中文 subtitles, transitions, music bed, `.srt` files.

Built on **HyperFrames** (HTML → video). Worked example in `example/` (model quantization, 10:33, 18 scenes).

## Prerequisites

- HyperFrames skills installed (`/hyperframes`, `/hyperframes-core`, `/hyperframes-animation`, `/hyperframes-audio`, `/media-use`) and `npx hyperframes` working. Route fresh creation through `/hyperframes` first (it writes `BRIEF.md`); this skill is the `general-video` playbook for this genre.
- `ffmpeg`, Python 3 with `fonttools brotli`.
- `OPENAI_API_KEY` (narration ≈ $0.015/min with `gpt-4o-mini-tts`).
- Optional: HeyGen CLI logged in (`heygen auth login --oauth`) for the music catalog.
- A CJK font you may redistribute (Noto Sans SC / Source Han Sans, OFL) and STIX Two Text (OFL, Google Fonts) in `assets/fonts/`.

Scripts live in `$VSTUDIO/workflows/explainer/scripts/` — call them from the **project root**. Below, `scripts/` means that folder.

## The pipeline

Each numbered stage ends at a user checkpoint unless the user said "just build it".

### 1. Brief (ask once, recommend defaults)
Length (default 5–7 min; "everything" topics run 10), destination → 16:9, sketches first (yes), subtitle layout (burned EN top / 中文 below + .srt). Voice: pick for the user, send a 10–15 s sample before the full run.

### 2. Script → `SCRIPT.md`
Format: `## Line N — <label> (Frame N)`, optional `**Delivery:**`, the spoken English as a 4-space indented block, then `ZH: <中文>`. One line = one scene.
- Spell numbers the way they should be **spoken** ("zero point five one", "F P thirty-two"); subtitles convert them back to digits later.
- Teaching shape that works: hook (a concrete number) → everyday intuition → what is stored → the core picture (one image) → **one worked example carried through 3–5 scenes with the same numbers** → why it doesn't hurt → types/variants → real tools → trade-offs → recap.
- Verify every number in the worked example yourself before writing it; write them at the top of SCRIPT.md as the example's ground truth.
- ≈ 175 spoken words/min for OpenAI `cedar` at speed 1.0 — measure from the sample, don't guess.

### 3. Sketches → `storyboard.html` (+ `storyboard/sketches/fNN.svg`)
One static 1920×1080 SVG per scene at its most complete moment, drawn with the real fonts/colours/copy, plus the subtitle band as a stand-in. Generate the sheet from a Python script (see `example/make_storyboard.py`), rasterize with `rsvg-convert`, and **look at every frame at full size** before showing the user (overlaps, clipped text, emoji that don't render). Present a frame table in chat; revise only frames the user names.

### 4. Voice
```bash
python3 scripts/tts.py --voice cedar            # → audio/vo/lineNN.wav
python3 scripts/concat_vo.py --gap 0.7          # → audio/narration.wav (-16 LUFS) + audio/vo/offsets.json
npx hyperframes transcribe audio/narration.wav -l en -m small.en   # → audio/transcript.json
```
QA: diff the transcript against SCRIPT.md per line (difflib ratio < 0.9 → inspect). Number formatting diffs are fine; missing words are not.

### 5. Bilingual subtitles
Hand-write `subtitles/cues.txt` — EN chunks (≤ ~90 chars) paired with their 中文 (≤ ~38 chars). Machine sentence-splitting does **not** pair EN↔ZH. Add project acronyms/formulas to `subtitles/display_rules.json` (see example).
```bash
python3 scripts/align_cues.py          # → subtitles/cues.json, en.srt, zh.srt
python3 scripts/scene_windows.py       # → audio/scenes.json, audio/scene_cues.json
python3 scripts/subset_cjk_font.py ~/.cache/video-studio/fonts/NotoSansSC-Regular.otf --out assets/fonts/subtitle-cjk-w3.woff2
python3 scripts/subset_cjk_font.py ~/.cache/video-studio/fonts/NotoSansSC-Bold.otf --out assets/fonts/subtitle-cjk-w6.woff2
python3 scripts/make_captions.py       # → compositions/captions.html
```

### 6. Build scenes
1. `npx hyperframes init <dir> --non-interactive --example=blank --skill=general-video`; copy `references/design-truth.md` → `frame.md`.
2. Write `scenes.config.json` (ids, transitions, **time-coded shot sequences using the real cue times** from `audio/scene_cues.json`), then `python3 scripts/make_packets.py`.
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

## Hard-won rules
Read `references/pitfalls.md` before building — every item there cost a failed check or a blank render once.
Transition menu and how they are wired: `references/transitions.md`.
