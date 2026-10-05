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
- `py_compile` + `--help` for all 11 scripts; `python3 -m pytest tests -q` → 34 passed.

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

