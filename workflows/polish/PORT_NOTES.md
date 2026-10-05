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
