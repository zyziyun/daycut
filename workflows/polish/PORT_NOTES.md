# PORT_NOTES — polish

## Source
- `content-skills/skills/descript-export-flow` (SKILL.md + `scripts/polish.sh`).

Renamed `polish`: nothing in the recipe is Descript-specific. `polish.sh` → `scripts/polish.py` (argparse).

Changes vs. source:
- Hard-coded 1080×1920 @ 30 fps / 28 Mbps → probed from the source (`--bitrate match`, or `--bitrate 28M`, or `--crf`).
- Single-pass dynamic loudnorm → **two-pass linear** loudnorm; target from `persona.audio.loudness_lufs`.
- Order changed to cover → speed → loudnorm (loudness measured on the final timing; speed step keeps PCM audio).
- Added bt709 tagging (encode-time and bsf for stream copy), `--keep` intermediates, `--check` first-frame dump,
  `--cover-fit`, `--skip-if-close`, atempo chaining outside 0.5–2.0, persona speed keys.
- Dropped: `qlmanage` preview (macOS-only); replaced by `--check` PNG. Default speed was 1.2; now 1.0 unless asked.
- Smoke-tested on a synthetic 4 s clip (cover + speed 1.2 + loudnorm → -14.04 LUFS, bt709 tags present).

## Capabilities
cover, speed, loudness, other (colour tags / faststart / bitrate matching).

## Duplicates for phase 2 (`lib/vstudio`)
- `scripts/polish.py:measure` + `step_loudness` — two-pass loudnorm (every workflow that delivers audio has one).
- `scripts/polish.py:atempo_chain` / `step_speed` — speed-up with atempo chaining.
- `scripts/polish.py:probe` — ffprobe wrapper (w/h/fps/bitrate/audio).
- `scripts/polish.py:step_cover` — "cover replaces first N seconds" (cover workflow and talking-head/vlog workflows likely do the same).
- `BT709` args + `step_finalize` bsf re-tag.

## Persona keys used
- existing: `audio.loudness_lufs`, `speed.*`, `speed.cjk_max_intelligible`, `export.crf`, `export.audio_bitrate`.
- new: none.

## Platform notes
- Pure ffmpeg/ffprobe; cross-platform. HDR sources are not tone-mapped here (see WORKFLOW.md).

## Phase 2b rewire
Swaps (old → new): `probe` → `media.probe` (thin adapter adds `fps`=fps_q, `vbr`=vbitrate); `atempo_chain` →
`media.atempo_chain`; `measure` + `step_loudness` → `audio.loudnorm_2pass` (and `audio.measure_loudness` for
`--skip-if-close` and the final report); `step_finalize` → `media.retag_bt709`; `BT709` → `media.BT709`;
`run` → `media.run` (keeps the `$ cmd` echo); `--check` frame → `media.grab_frame`; tool check → `media.ffmpeg_bin/ffprobe_bin`.
Kept local: `venc_args` (source-bitrate matching; `media.delivery_args` is CRF-only and always adds audio args),
`step_cover`, `step_speed`, `resolve_speed`.
Behaviour changes: loudnormed audio is now 48 kHz **stereo** (mono up-mixed before measuring; was source layout);
LRA target is raised to the measured LRA so loudnorm stays in linear mode; the final retag also writes `color_range tv`.
Tests: synthetic 4 s 1080×1920 clip, `--cover --speed 1.2 --check` → before −14.05 LUFS / after −14.05 LUFS,
3.40 s both, h264 bt709 primaries/trc/space, AAC 48 kHz stereo; `--skip-if-close` on the output (no gain change);
`--speed 3 --no-loudnorm` (atempo chain, PCM→AAC in retag, bt709); `--help`; `pytest tests` 34 passed.
Lib requests: `media.delivery_args(vbitrate=..., maxrate_factor=1.15)` bitrate-target mode and `audio=None` (= leave
audio args out / copy) so `venc_args` can go.

## Wave B
Changes (`scripts/polish.py`, `WORKFLOW.md`):
- `--platform SPEC` (parsed with `platform.parse_targets`). **No `--platform`: unchanged** (same ffmpeg commands;
  `venc_args(..., prof=None)` returns identical args to HEAD for match / `28M` / `28` / `--crf`).
- One target: LUFS/TP from `profile.loudness` (explicit `--lufs`/`--tp` win; `--tp` default moved from -1.5 to
  None → -1.5 when no profile); encode capped by `profile.encode` (bitrate mode `-b:v min(src, maxrate)`, maxrate
  ≤ cap; CRF mode `--crf` else profile `crf` + profile maxrate/bufsize as VBV cap); `platform.check_length` on the
  final duration; `<out stem>.cover.jpg` via `export.make_cover` (from `--cover`, else a frame; `.feed.jpg` preview
  where the feed crops); aspect-mismatch and fps>max warnings; no silent reframe.
- Several targets: master polished once at the default target, then `export.export(master, targets, --out-dir,
  covers=[--cover], cues=--cues, mode=--reframe-mode, preset=--preset)` → per-platform files + `manifest.json`.
  New flags: `--out-dir` (exports/), `--cues`, `--reframe-mode`.
- WORKFLOW.md: new pipeline step 2 — propose 1.2× (or persona `speed.body`) for shorts and ask; mentions the
  `speed.cjk_max_intelligible` warning (parity with the source skill's 1.2× default, kept as a suggestion).
  New "## Platforms" section (flags, per-platform table, single/multi commands, `python -m vstudio.export`).
Tests (synthetic 1080x1920 6 s testsrc2 + sine/anoise, /tmp only): default run HEAD vs new — identical ffmpeg
commands, 6.00 s both, -14.12 LUFS both, 9.1 vs 9.0 Mbps (HEAD itself varies ~1% run to run: x264 threading);
`--platform youtube` on a -21.9 LUFS clip → -14.04 LUFS, cover 1280x720, aspect warning + length warning printed;
`venc_args` with douyin: `28M` → 12M capped, `--crf 23` → + maxrate 12M; `--platform douyin,xiaohongshu:vertical`
→ manifest 1080x1920 / 1080x1440, both -14.04 LUFS, covers 1080x1920 / 1080x1440 (+ douyin feed preview).
Lib requests: none blocking. Nice-to-have: `media.delivery_args` now has `vbitrate`/`audio=None`, but `venc_args`
stays local because it emits no `-profile:v high`/bsf (switching would change the no-platform output); a
`profile=None` toggle in `delivery_args` would let it go. `export.export` could accept `loudness_from_master=True`
to skip the second loudnorm when the master is already at the profile target (currently loudnorm runs twice in the
multi-target path; linear, so harmless but slower).
Persona keys: none new (reads `platforms.*` via `vstudio.platform`, `speed.body` documented as the shorts proposal).
