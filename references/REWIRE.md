# Phase 2b: rewire a workflow onto `lib/vstudio`

You own ONE workflow folder (named in your dispatch). Do NOT edit `lib/`, `tests/`, other workflows,
SKILL.md or persona.example.yaml. If the library is missing something or has a bug, keep the local code
for that piece and write it under "Lib requests" in PORT_NOTES.md.

1. Read `references/PORTING.md` (rules still apply), your folder's `PORT_NOTES.md` (its "Duplicates" list
   is your to-do list), and the library: `lib/vstudio/{config,face,retouch,media,audio,asr,cut,subs,tts,
   render,draw,overlays,cover,publish}.py` (read docstrings; `__init__.py` lists them).
2. Replace each duplicated local implementation with the library call when it is **behaviour-equivalent or
   better**. Typical swaps: ffprobe/run/duration/extract_wav → `media`; loudnorm (any) → `audio.loudnorm_2pass`
   / `normalize_stem`; whisper wrappers → `asr.transcribe`; term fixes → `asr.apply_term_fixes`; raw→final
   time maps → `cut.TimeMap`; pause squeeze → `cut.tighten`; stumble detection → `cut.find_cuts`; frame-exact
   cutting → `cut.cut_segments`; xfade montage → `cut.xfade_assemble`; SRT/ASS → `subs`; CJK wrapping →
   `subs.wrap_cjk` / `draw.wrap`; TTS → `tts.synth`; Chrome/HTML→PNG + font staging/subsetting → `render`;
   panels/callouts/chips/badges/stamps/progress bars → `overlays`; covers + cover-frame scoring → `cover`;
   title checks / chapter lines / post bodies → `publish`; delivery encode → `media.delivery_args` /
   `retag_bt709`.
3. Delete the now-unused local code (no dead copies). Keep thin wrappers only where a script's CLI depends
   on them.
4. Known semantic differences — decide deliberately and note your choice:
   - `cut.xfade_assemble(mute_pad=True)` pads BOTH sides of each join (extra ~xfade of silence per join);
     `mute_pad="head"` reproduces the old talkinghead behaviour.
   - persona `subtitles.term_fixes` are now LITERAL (not regex); regex fixes belong at the call site.
   - `cut.find_cuts` keeps call-clips constants; `cut.tighten` reads persona `audio.pause_*`.
   - `audio.mix_bed(carve=True)` is a fixed EQ dip; HyperFrames projects keep `carve.mjs`.
5. Prove nothing broke: re-run the synthetic smoke tests you (or the phase-1 porter) used — they are
   described in PORT_NOTES.md — plus `python3 -m pytest $REPO/tests -q`, `py_compile`, and `--help` for
   every CLI. Generate synthetic media with ffmpeg lavfi in /tmp. Compare key outputs before/after
   (duration, loudness, frame snapshot) where the old path still exists in git (`git show HEAD:path`).
6. Update WORKFLOW.md if commands/flags changed, and append to PORT_NOTES.md a "## Phase 2b rewire" section:
   swaps made (old → new), behaviour changes, test evidence, lib requests.
7. Reply with ≤12 lines: swaps, behaviour changes, tests run + results, lib requests.
