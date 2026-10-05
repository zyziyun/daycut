# PORT_NOTES — explainer

## Source
- The `3b1b-math-explainer` HyperFrames skill (repo commit c29bb56) and its worked example (model
  quantization, 18 scenes): `WORKFLOW.md`, `scripts/`, `references/`, `assets/reference-scene.html`, `example/`.
- No phase-1 notes existed for this folder; this file was created in phase 2b.

## Capabilities
tts, loudness, asr, bilingual, captions, transitions (11 types in `make_index.py`), music, screenshot-cards
(HyperFrames scenes), other (spoken-number → digit display text, frame-worker packets, CJK font subsetting).

## Unique pieces (keep local)
- `display_en.py` — spoken English → on-screen English (digits, decimals, negatives, billions, project rules
  from `subtitles/display_rules.json`). Nothing in `lib/vstudio` does this.
- `align_cues.py` alignment core — hand-paired EN‖ZH chunks mapped onto whisper words with difflib anchors and
  linear interpolation per SCRIPT.md line (first cue pinned to the line's audio offset).
- `make_index.py` — HyperFrames assembly with 11 GSAP transition types and `--patch-scenes`.
- `scene_windows.py`, `make_packets.py`, `make_captions.py` — HyperFrames-specific, no lib equivalent.

## Duplicates (phase 2 to-do, now done — see below)
- `tts.py` (urllib OpenAI call) → `vstudio.tts.synth`
- `concat_vo.py` ffprobe + single-pass loudnorm → `vstudio.media` + `vstudio.audio.normalize_stem`
- `make_bgm_bed.py` ffprobe + single-pass loudnorm → `vstudio.media` + `vstudio.audio.loudnorm_2pass`
- `align_cues.py:ts` + SRT writer → `vstudio.subs.srt_write`
- `subset_cjk_font.py` → `vstudio.render.subset_font`
- `npx hyperframes transcribe` → optional `vstudio.asr.transcribe` (`scripts/transcribe.py`)

## Persona keys
None new. Narration/bed loudness and voice come from CLI flags (defaults -16 / -30 LUFS, `cedar`), so
persona `audio.*` / `tts.*` are not consulted.

## Platform-specific / unverified
- Real OpenAI TTS not called during the port (stubbed; see tests). HyperFrames render/carve not re-run.

## Phase 2b rewire

### Swaps (old → new)
- `tts.py`: urllib POST + ffprobe → `tts.synth(engine="openai", voice, speed, instructions=direction + per-line
  **Delivery:**, model, out=...)` + `media.duration`. New `--fresh` flag (bypass cache).
- `concat_vo.py`: ffprobe/anullsrc/fixed `/tmp/_*.wav` → `media.probe`/`media.duration`, `audio.silence`
  (same rate/channels as the takes), a TemporaryDirectory concat list, `media.run`; single-pass
  `loudnorm=I=-16:LRA=11:TP=-1.5` → `audio.normalize_stem(..., lufs=--lufs)` (two-pass, linear).
- `make_bgm_bed.py`: ffprobe → `media.duration`; inline loudnorm → `audio.loudnorm_2pass(lufs=-30, tp=-6, lra=7)`.
  The acrossfade loop chain stays local (lib has no crossfaded loop; `mix_bed` hard-tiles), run via
  `media.run` + `media.filter_complex_args`.
- `align_cues.py`: local `ts()` + SRT loop → `subs.srt_write([subs.Cue(start, end, text)])`, plus one appended
  `\n` so files stay byte-identical with the shipped `example/subtitles/*.srt` (lib writes no trailing blank line).
- `subset_cjk_font.py`: fontTools code → `render.subset_font` (CLI kept; `--out` now relative to the project).
- New `scripts/transcribe.py`: `asr.transcribe` → `audio/transcript.json` in the HyperFrames shape
  (`[{text,start,end,id}]`), documented in WORKFLOW.md as the no-node alternative. Term fixes off by default.
- All scripts: PORTING.md bootstrap import, `--project/-C DIR` (default `.`); every project path is resolved
  against it. User-supplied inputs (music SOURCE, FONT) stay relative to the current dir. `make_index.py` now
  uses argparse (`--patch-scenes` unchanged). `display_en.display(en, line, rules=None)` + `load_rules(project)`
  replace the import-time read of `subtitles/display_rules.json` from the cwd.

### Behaviour changes
- `audio/narration.wav` is now 48 kHz **stereo** (was mono) and two-pass linear: synthetic test hit -15.9 LUFS
  (old single-pass: -16.5). Offsets and duration unchanged.
- TTS takes are 48 kHz mono (OpenAI's raw wav was 24 kHz) and cached in `$VSTUDIO_CACHE/tts`.
- BGM bed: two-pass linear loudnorm; 120 s synthetic bed -30.0 LUFS (old -29.9). On a very short (14 s) bed
  with 3 s/5 s fades it lands -29.4 (old -29.9) — irrelevant at film lengths.
- Font subset also keeps all name IDs, a .notdef outline and a slightly wider punctuation set (543 vs 531
  glyphs, +1 %); without `brotli` it writes .otf instead of failing.

### Test evidence
- Quantization example (inputs reconstructed read-only from the source project: transcript.json,
  offsets.json, cues.txt; display_rules.json + SCRIPT.md from `example/`): old scripts reproduce the source
  `cues.json`/`en.srt`/`zh.srt`/`scenes.json`/`scene_cues.json`; the new scripts reproduce the old outputs
  **byte-identically**: cues.json, en.srt, zh.srt (= `example/subtitles/*.srt` too), scenes.json,
  scene_cues.json, captions.html, all 18 frame packets, `index.html` and the 18 `--patch-scenes`-patched
  compositions. `index.html` equals the source project's except the carve attributes `carve.mjs` adds.
  `display_en.py` CLI output identical.
- Synthetic 3-line project (macOS `say` takes at 24 kHz mono): old vs new `concat_vo` offsets identical;
  `transcribe.py` (mlx whisper-small.en) → transcript; old vs new `align_cues` + `scene_windows` byte-identical.
- `tts.py` with `tts._openai` stubbed: 3 calls with the right text/voice/direction/model; re-run of line 2
  served from cache (0 calls).
- `py_compile` + `--help` for all 11 scripts; `python3 -m pytest tests -q` green at the time (current count: run it; see tests/).

### Lib requests
- `audio.loop_bed(src, total, xfade, fade_in, fade_out, lufs)` — crossfaded looping (mix_bed only hard-tiles);
  would let `make_bgm_bed.py` drop its local acrossfade graph.
- `subs.srt_write`: option to end with a blank line (conventional SRT ending) to drop the append in `align_cues.py`.
- `asr`: an exporter for the HyperFrames `transcript.json` word shape (`[{text,start,end,id}]`).

## Phase 3: transitions moved to `vstudio.hf`

`make_index.py` takes the transition CSS (`.scene-wrap`, `#tx-blocks`), the 8-block overlay and the GSAP switch
for all 11 types from `vstudio.hf.scene_transitions`, and builds each spec with `hf.transition` (which rejects
unknown types). `index.html` is **byte-identical** to the pre-refactor script on the example's 18 scenes
(synthetic `audio/scenes.json`) and on a variant using all 11 types + a bgm track; `hyperframes lint` 0 errors,
0 warnings on both.


## Wave B: platform profiles + vertical short + drafting tools

**Canvas** (`scripts/canvas.py`, from `vstudio.platform`): `--platform` on every canvas-dependent script, or
`"platform"` (+ `"mode": "short"`) in `scenes.config.json`. No platform / a horizontal profile = legacy 16:9 (all
strings unchanged). Vertical: canvas W×H, `safe_box`, `caption_box`, `keepouts`, a math area (safe box minus a
title strip, above the caption band), caption sizes from the band height (EN 38 / 中文 48 on a 220 px band) and
2-line char limits.
- `make_captions.py`: vertical cue block bottom-anchored in the caption box (+10 px), balanced wraps, scrim from
  60 px above the band; warns on cues over 2 lines per language. Legacy branch keeps the exact old CSS.
- `make_index.py`: W/H everywhere (viewport, root, scene hosts, captions host, `hf.scene_transitions(W, H)`).
- `make_packets.py`: canvas line from `canvas.describe` (+ a `canvas json` line with safe/caption/keepouts/math/title
  and the portrait reference + design truth); legacy line unchanged.
- `scene_windows.py`: `--tail` default 1.2 s for vertical / short (2.5 legacy); `scenes.json` gets a `canvas` key only
  when vertical; prints platform length warnings and, in short mode, scenes > 14 s / totals > 120 s.
- `align_cues.py`: ignores `# check:` comments left by pair_cues.py (no effect on existing cues.txt).
- New `references/design-truth-portrait.md` (frame.md variant: zones, portable 9:16 area x 150–930 / y 280–1190,
  stacked layout, bigger type, hook-in-2 s motion, 3:4 numbers), `assets/reference-scene-portrait.html` (f07 re-laid
  out at 1080×1920: ruler 700 px, equation broken at "=", mono labels 36), dispatch note for vertical workers,
  WORKFLOW.md "Vertical short" (SHORT pipeline, pacing table) + "Platforms (16:9)" + drafting steps.

**Less manual work**
- `scripts/storyboard_from_script.py`: SCRIPT.md → STORYBOARD.md + scenes.config.json (writes `*.draft.*` if they
  exist; `--force`, `--keep-shots` keeps ids/transitions/shots). One beat per cue with hints; timing from
  `audio/scene_cues.json` when present (the example's real beat times come out as 0.3/4.0/6.9/11.2 s on f07 — the
  hand-written shot list used 0.4/4.0/6.9/11.2), else estimated at `--wpm` (example: ~617 s estimated vs 633.65 real).
  Short mode: hook beat, fast transitions, warnings (scene count, first sentence > 2.2 s, > 120 s, scenes > 14 s).
- `scripts/pair_cues.py`: EN/中文 clause split + monotone DP (length ratio, punctuation agreement, caption limits) →
  `subtitles/cues.draft.txt` with `# check:` flags; `--compare` scores against a hand file. On `example/`: 153 cues,
  12 flagged, **111/142 (78 %) of the hand cue boundaries reproduced**; the draft passes align_cues (EN chunks = spoken).
  Weights tuned on the example (W_CUE 0.1, W_MID 0.3, W_STRADDLE 0.8). It cannot judge meaning: review every pair.
- `scripts/script_md.py`: shared SCRIPT.md parser.

**Tests**
- 16:9 regression (quantization inputs from /tmp/expl_baseline, rebuilt from scratch): cues.json, en.srt, zh.srt
  (= `example/subtitles/*.srt`), scenes.json, scene_cues.json, captions.html, 18 packets, index.html and the
  `--patch-scenes` compositions **byte-identical** to the pre-change outputs.
- Synthetic 3-line portrait project (macOS `say` takes, `xiaohongshu:full`): storyboard_from_script → pair_cues →
  align_cues → scene_windows → make_captions → make_packets → 3 scenes from the portrait reference → make_index
  `--patch-scenes`: `hyperframes lint` 0 errors / 0 warnings; snapshots at 1.0/3.5/6.5/11.5 s: caption text bbox
  inside the caption box (160,1420,920,1640) on all four (pixel check), nothing in the button column.
- Reference portrait scene alone (31.95 s): lint 0/0; snapshots at 12 s and 27 s read: everything inside the
  portable 9:16 area, nothing in the button column or caption band.
- storyboard_from_script + pair_cues on `example/SCRIPT.md` (estimated and real timing): sensible drafts (above).
- py_compile + `--help` for all scripts; `python3 -m pytest tests -q` green at the time (current count: run it; see tests/).

**Not done / unverified**: no full render; sketches (`make_storyboard.py`) are still example-specific 16:9 — draw
vertical sketches at canvas size by hand; 3:4 built only via the canvas numbers (not snapshotted for the explainer).

**Lib requests**: none required. Nice to have: `platform.caption_box` variant for two-language blocks (size pairs).

## Demo round fixes (2026-10-05)

Vertical CUDA short demo (9:16, 7 scenes). Tests: `tests/test_lfs_explainer_fixes.py`.
- `make_captions.py` creates `compositions/` (a blank `hyperframes init` has none; it crashed).
- `display_en.py`: a comma inside a cardinal ("sixteen thousand, eight hundred and ninety-six" → 16,896, while
  "one thousand, two thousand" stays a list); "a hundred / thousand / million" → "one ..." (was "a 1 million");
  "one point five million" → "1.5 million"; "1 million" already in digits is left alone. Example en.srt unchanged.
- New `scripts/vo_check.py`: numbers normalised on both sides, the take's ASR aligned to the script word by word,
  coverage per script sentence; `tts.py` runs it on every take, re-generates a take that dropped a sentence
  (`--retries 2`) and exits non-zero naming the sentence if it still drops it (`--no-check`; skipped with a warning
  when no ASR backend is available). Replaces the 0.9 difflib-ratio QA (clean takes scored 0.68–0.74).
- `render_cover.py` (cover workflow) with `--platform` always writes `<stem>.<platform>-<orientation>.<ext>`
  (a single platform used to overwrite `-o`, the 9:16 cover). WORKFLOW says to render 小红书's 3:4 cover this way.
- Vertical scenes sat small in the top half of the math area (a big empty band above the captions). The portrait
  design truth now requires the scene to fill the math area (≥ 70 % of its height, result line just above the
  caption band, main graphic ≥ 80 % of the width); the reference portrait scene was re-laid out to fill the
  portable 9:16 area (bigger dots / labels / equation, result at y 1170); packets carry the rule; new
  `scripts/layout_check.py` measures each snapshot (warns < 60 % height or > 30 % empty bottom). On the demo's
  snapshots it flags 8/15 frames; the new reference scene passes on 小红书 full, 抖音, Shorts and TikTok.
