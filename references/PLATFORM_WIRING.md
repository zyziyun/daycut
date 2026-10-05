# Wiring a workflow to platform profiles (wave B)

Goal: every workflow can say "for 小红书 vertical" / "for YouTube" / "for 抖音 + Shorts" and get the right canvas,
safe zones, caption placement, length checks, loudness, cover size and copy limits from ONE place
(`lib/vstudio/platform.py`), and every workflow can hand a clean master to `python -m vstudio.export`
to produce several platform versions at once.

## Rules
1. **Input**: accept `platform` in the workflow's config (and a `--platform` CLI flag where there is a CLI), value
   like `xiaohongshu:vertical`, `douyin`, `youtube`, `youtube-shorts`, `bilibili:horizontal`
   (`platform.parse_targets` parses lists). Default: `persona.platforms.default` + the workflow's natural orientation.
2. **Derive, don't hard-code**: canvas size from `profile.canvas`; overlay placement from `platform.safe_box` /
   `keepouts`; caption band, font size range and max chars from `platform.caption_box` / the profile's caption
   style; cover size from `platform.cover_size` (+ `cover_title_safe`, `feed_crop_box` for 小红书 16:9);
   loudness from the profile; length warnings via `platform.check_length`; title/description via
   `platform.check_text` / `publish`. Replace hard-coded 1080x1920 / safe-zone constants / caption y with these.
   Keep the old values reachable as a fallback (if a profile key is missing, use the previous constant).
3. **Clean master + cues**: where the workflow burns captions or overlays that depend on the canvas, also be able to
   write a caption-free master (`--clean-master`) plus `cues.json`/SRT so `vstudio.export` can re-burn per target.
   Document the multi-platform step: `python -m vstudio.export master.mp4 --platforms ... --cues ... --cover ...`.
4. **Reframe**: when the source aspect differs from the target (e.g. horizontal recording → vertical), use
   `vstudio.reframe` (face mode with pad-blur fallback; feed SDR — call `media.to_sdr` first for HLG/PQ).
5. **Docs**: add a "Platforms" section to the workflow's WORKFLOW.md (flags, defaults, what changes per platform,
   the export command). Update PORT_NOTES.md with a "## Wave B" section (changes, tests).
6. **Tests**: re-run the workflow's existing synthetic checks for the default platform (outputs must be unchanged or
   deliberately improved — compare with `git show HEAD:...`), then run at least one OTHER platform target and check
   canvas size, that overlays/captions sit inside the safe/caption boxes (pixel check or snapshot Read), and
   loudness. `python3 -m pytest tests -q` must stay green (note: tests/test_retouch.py may be mid-change by another
   agent — ignore failures that are only there).
7. Public-safe rules from `references/PORTING.md` still apply. Never edit lib/vstudio/* unless your dispatch says so;
   file "Lib requests" in PORT_NOTES.md instead.
