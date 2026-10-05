# PORT_NOTES — longform-to-short

## Source
`~/.claude/skills/longform-course-cut` (SKILL.md, config.example.py worksheet, 22 scripts). Read-only; nothing copied verbatim
that carried personal content.

What changed:
- **Per-video constants → one config file.** Every script now takes `work/config.py` (dict `CONFIG`) or `work/config.json` as
  argv[1], with argparse `--help`. The old worksheet-plus-paste-into-scripts workflow is gone. A synthetic
  `examples/config.example.py` documents every key.
- **Merged / renamed:** `parse_silence.py` + the ffmpeg extraction commands → `analyze.py`. `geometry.py` + `build_spans.py`
  → `geometry.py`. `build_subs.py` (v1, keep-list mapping) + `build_subs2.py` (v2, timeline mapping) → `build_subs.py`
  (timeline mapping only) + `subs_lib.py`. `render2.py` → `render.py`. `make_cover.py` + `make_cover_xhs.py` →
  `make_cover.py` (both layouts). `make_xhs.py` → `make_episodes.py` (N episodes, auto or explicit split).
- **New:** `transcribe.py` (mlx_whisper else faster_whisper, same flags), `qa.py` (decode, loudness, mosaics, f0 pitch
  check: the old "verify" section as code), and the `发布包.md` writer (the old make_xhs docstring mentioned it but never
  wrote one).
- **Fixes found during a synthetic end-to-end smoke test** (60 s lavfi video, every step run): segment audio is now uniform
  48 kHz stereo, because mixed card/clip layouts made loudnorm reinit mid-stream and measure −inf. Loudnorm is two-pass
  with linear mode (single-pass came out at −16.3 instead of −14) and the output is resampled to 48 kHz (loudnorm
  defaults to 96 kHz). The qa f0 estimator is unbiased, picks the first strong peak and uses parabolic refinement.
- **Dropped:** the v1 keep-list-only subtitle mapping (v2 superseded it). The hard-coded vLLM 勘误 text and all
  course-specific chapter, panel, cover and cut data. The `knflow.com` demo URL and its prompt (now `demo.*`). Speaker
  names (now `speakers.aliases`; unknown labels are auto-anonymised to "Speaker A/B"). The "<host>的屏幕共享" label
  comment (now `geometry.bottom_trim`). "2026 北美 SDE 求职" and other cover copy (now `cover.*`). The accent-specific
  TERM_FIXES list: about 10 generic tech-term fixes remain in `subs_lib.GENERIC_TERM_FIXES`; everything else goes to
  persona/config. The pointer to the creator's built example folder.
- The hook music bed is kept behind `make_audio_assets.py --hook-bed` (not recommended, never mixed automatically).
- The 1v1 coaching variant (resemblyzer diarization, Laplacian gallery-view detection, word-level filler tightening) had
  no scripts in the source. It is kept as prose in `references/coaching-variant.md`.

## Capabilities
cut (keep.ranges from transcript blocks + word-level `cuts`) · asr (whisper with anti-hallucination flags) · captions
(retime through timeline, term fixes, 勘误 notes, SRT + ASS burn) · speed (per-kind lecture/demo/hook) · loudness (two-pass
loudnorm) · sfx (synth card stinger) · music (optional synth hook bed, off by default) · zoom (code-block centroid
cut-ins) · overlays (hook overlay) · notes-panels (记笔记 panels in source time) · hook (cold-open clip) ·
freeze-frame (transient flash hold) · privacy-mask (browser chrome/bookmark-bar crop, gallery spans dropped, speaker
aliasing, pitch-shift voice anonymisation, mosaic QA) · cover (16:9 + 3:4) · publish-copy (发布包.md, xhs title/label
checks) · long-to-short · episodes (N-way split at chapter cards) · transitions (chapter cards) · screenshot-cards
(framed screenshot on covers) · other: screen-geometry detection, speaker timeline from caption track, transient scan,
Playwright demo re-record, f0 pitch verification.

## Duplicates to unify in phase 2 (lib/vstudio candidates)
- loudnorm: `scripts/render.py` (two-pass block at end), `scripts/qa.py` (loudness measure)
- whisper wrapper: `scripts/transcribe.py` (mlx/faster switch)
- subtitle time-mapping: `scripts/_lfc.py:map_src`, `scripts/build_subs.py` (segment → timeline retime)
- subtitle formatting: `scripts/subs_lib.py:wrap, srt_ts, ass_ts, ass_header, make_clean` (term-fix application)
- ffmpeg binary / libass detection: `scripts/_lfc.py:ffmpeg_bin, _has_filter, video_encoder`
- accurate frame grab with sparse keyframes: `scripts/_lfc.py:grab_frame`
- notes panels: `scripts/make_panels.py` (PIL 记笔记 panel), overlay with `-loop 1`/`shortest=1` in `scripts/burn_final.py`
- cover rendering: `scripts/make_cover.py:framed, chips_row, wide, tall`, `scripts/make_episodes.py:ep_cover`
- chapter cards: `scripts/make_assets.py`
- publish copy / chapter timestamp list: `scripts/make_episodes.py:chapter_lines` + 发布包 writer
- silence parsing: `scripts/analyze.py` (silencedetect → sounded spans)
- PIL font helper: `scripts/_lfc.py:font, font_family_name`; colour helper `_lfc.palette`
- pitch-shift filter string (asetrate + atempo): `scripts/render.py`

## New persona keys (read with safe defaults; not added to persona.example.yaml)
- `longform.accent` (default `#2DD4BF`, teal): card, panel and cover accent. Also overridable per video with `style.accent`.
- `longform.ground` (default `#0A0A0C`): card and cover background (`style.bg`).
- `longform.speed.lecture` / `.demo` / `.hook` (defaults 1.2 / 1.3 / 1.1). The existing `speed.body` / `speed.hook`
  mean something different (talking-head pacing), so they are not reused.

Existing keys used: `audio.loudness_lufs`, `export.crf` (burn fallback), `subtitles.term_fixes` (literal,
case-insensitive), `creator.language`, `platforms.xiaohongshu.title_max`, `publish.tags`, `publish.chapter_line`, and
`fonts.*` via `vstudio.config.font`.

## Platform-specific / unverified
- `burn.encoder: auto` picks `h264_videotoolbox` on macOS and libx264 elsewhere.
- libass: system ffmpeg is used if it has the `ass` filter, else `static_ffmpeg` (optional pip package). Verified on this
  machine: Homebrew ffmpeg lacks libass, and the fallback worked.
- `transcribe.py` faster_whisper branch is untested here (mlx path is the original). The `hallucination_silence_threshold`
  kwarg needs faster-whisper ≥ 1.0.
- `probe_app.py` / `record_demo.py` (Playwright) were compile- and `--help`-checked only, not run.
- Geometry / transient / zoom thresholds were tuned on one light-theme docs share at 1280x720 (the original recording).
  Other apps, dark mode or other resolutions need `geometry.*`, `transients.*` and `zoom.*` retuned. The smoke test only
  proved the code paths work.
- Assets: none copied. The stinger and hook bed are synthesized in code (no third-party audio). Fonts come from vstudio
  (OFL).

## Phase 2b rewire (onto lib/vstudio)

Swaps (old → new):
- `_lfc.ffmpeg_bin/_has_filter/run/probe_duration/grab_frame` → `media.ffmpeg_bin(need=["ass"])`, `media.run`,
  `media.duration`, `media.grab_frame` (deleted locally). Burn graph goes through `media.filter_complex_args`.
- `_lfc.map_src` → `cut.TimeMap` built by `_lfc.timemap(timeline)` (cards = holds, hook tagged "hook", body
  mapped with `tag="body"`); `map_src` / `total_duration` remain as one-line wrappers. Panel / 勘误 windows use
  `TimeMap.map_span`. `_lfc.mmss` → `publish.mmss`; `_lfc.rgb` → `draw.rgb`; `_lfc.font` → `draw.load_font`
  (2-line wrapper kept); `_lfc.font_family_name` → `subs.font_family`.
- `subs_lib.py` deleted: `make_clean/term_fixes/GENERIC_TERM_FIXES` → `asr.apply_term_fixes(text, config regex list)`;
  `wrap/srt_ts/ass_ts/ass_header` → `subs.srt_write` / `subs.ass_write(wrap=max_line)` / `subs.ass_ts`.
  `FILLER_ONLY` moved into build_subs.py.
- render.py: two-pass loudnorm block → `audio.loudnorm_2pass`; pitch chain → `audio.pitch_shift_filter`;
  plain `atempo=` → `media.atempo_chain` (now valid for any speed).
- transcribe.py: mlx/faster switch → `asr.transcribe(..., fix_terms=False)` (cached, adds openai backend,
  `--backend`, `--prompt` / config `asr_prompt`). audio16k.json shape unchanged.
- analyze.py: wav extraction + silencedetect parsing → `media.extract_wav`, `audio.silence_spans` +
  `audio.sounded_spans` (silencedetect.txt is no longer written).
- qa.py: loudness → `audio.measure_loudness` (also prints true peak); mosaics → `media.contact_sheet`
  (time-labelled, 30 per sheet).
- make_panels → `overlays.notes_panel` (teal theme via `_lfc.theme`, honours `style.accent`); chapter cards →
  `overlays.chapter_card`; covers → `cover.framed_cover` (16:9 + 3:4); episode cover frame → `cover.framed`;
  chapter lines / tags / title check → `publish.chapter_lines` / `hashtags` / `check_title`.
- Kept local (no lib equivalent): `video_encoder` (VideoToolbox q:v vs x264), hook overlay box, episode cover
  layout, f0 pitch QA, geometry / transient / zoom detection, card stinger synth, timeline building.

Behaviour changes (deliberate):
- SRT timestamps no longer print `,000` for x.9996 s (old `srt_ts` bug: a cue ended at 22,000 instead of 23,000).
- Term fixes: lib generic list is a superset with CJK-safe lookarounds; persona fixes stay literal; config
  `subtitles.term_fixes` stays regex. Whitespace runs collapse to one space.
- ASS: `WrapStyle 2` + lib balanced CJK wrap (latin words never split; may use 3 lines for very long chunks
  instead of always 2); side margins 60 px instead of 80. The 勘误 `Note` style is appended after `ass_write`.
- Panels: bullets wrap inside the card, round accent dots instead of "·", body 30 px instead of 27.
- Cards: "02 / 02" instead of "02 / 2"; long titles wrap. Tall cover: text auto-fits, chips no longer overlap the
  screenshot. Covers grab the frame accurately (`media.grab_frame`) instead of a fast seek.
- Full-video chapter list no longer duplicates "00:00" when the first card is at 0 s; YouTube chapter-rule warning.
- Hashtag order: per-video tags first, then persona tags, de-duplicated.
- faster-whisper default model is now `large-v3-turbo` (lib default) instead of `large-v3`.

Test evidence (synthetic 60 s 1280x720 lavfi "meeting" video with macOS `say` Chinese speech, every step
run old (HEAD via `git archive`) vs new, same config: hook, 2 chapters, cut, freeze, pitch window, zoom,
panel, 勘误, 2 auto episodes):
- final.mp4 36.372 s / final_subbed 36.375 s / ep1 18.667 s / ep2 17.708 s — identical old vs new.
- Integrated loudness (ebur128): final −14.1, final_subbed −14.1, ep1 −14.0, ep2 −14.5 LUFS — identical; qa.py
  reports −14.2 LUFS, TP −1.4 dBTP, decode clean; pitch window −2.2 st (old −1.9 st).
- timeline.json, sounded.json, whisper segments identical; subs.ass timings identical; subs.srt differs only
  by the rounding fix above; 发布包.md byte-identical; episodes + covers produced. Visual side-by-side of
  card / panel / covers / burned frame checked.
- ASR cache: second transcribe.py run 1.4 s. `python3 -m pytest tests -q` 34 passed; every script
  py_compiles and `--help` runs.

Lib requests:
- `subs.ass_write`: accept extra named styles / events (e.g. a top-boxed "Note" style for 勘误), so callers
  don't patch the header text.
- `media.delivery_args`: optional `encoder="videotoolbox"` (q:v quality mode) so `_lfc.video_encoder` can go.
- `overlays.chapter_card` / `get_theme`: an `accent=` override (today `_lfc.theme` copies the teal theme dict
  and rewrites five keys to honour a per-video accent).
