# Gotchas (real failures hit building this pipeline)

## Render duration runs away (out_time keeps climbing past the expected total)
(H track, `build_filter.py`.) Cause: an ffmpeg image input added with `-loop 1` and **no `-t`** is infinite. When it feeds an
`overlay`/`alphamerge`, the graph never reaches EOF, so encoding never stops.
Fix: bound every looped image with `-t <duration>` (callouts/panels already do this since they're
`-loop 1 -t dur`), and if you ever overlay a full-length looped image (e.g. a mask), add
`overlay=shortest=1`. If a render's progress log shows `out_time_ms` going past the total, kill it
(`pkill -f run.sh`) and check for an unbounded loop input.

## Background blur turned the frame grayscale
`maskedmerge` negotiates a common pixel format and can collapse to gray8 when one input is a
grayscale mask. If you want masked compositing, use `alphamerge` (mask -> alpha on the sharp layer)
then `overlay` onto the blurred layer; that preserves color.
But note: the elliptical "focus blur" looked **ugly and fake** on a static talking head and was
dropped. Default is **brightness-grade-only** (`eq=brightness=-0.06:contrast=1.08:gamma=0.96`),
which is what fixes the "太亮/太乱" complaint without the cost or the bad look. Only do real
background blur if the user explicitly wants bokeh, and then use proper per-frame matting (RVM),
not a static ellipse.

## Callout/panel input index off-by-one after removing some callouts
When you skip callouts via `REMOVE`, the kept callouts have **sparse original indices** (0,1,4,5…)
but their ffmpeg inputs are added **sequentially**. So the filter must reference each by its
**enumerate position** (`call_base + n`), not by the original `c["i"]`. (The PNG *filename* still
uses the original `i`.) Getting this wrong gives `Invalid file index` errors.

## xfade offset math
For clips with sped, frame-quantised durations `d[0..n]` and crossfade `X`: `offset[k] = offset[k-1] + d[k-1] - X`
(`vstudio.cut.xfade_assemble` does this; `scripts/montage.py` wraps it for the hook montage). With muted pads each
`d[k]` includes the pads, so body second 0 plays at `BODY_START = body dissolve start + X`; use
`Montage.b2f(o) = BODY_START + o/BODY_SPEED` for all overlay timing (both tracks write it to `timeline.json`).
Each xfade and each acrossfade shortens the combined stream by exactly `X`, so video and audio
stay in sync as long as both chains use the same `X`.

## drawbox cannot animate
`drawbox` evaluates x/y/w/h once, and its `t` is the box THICKNESS, not time: a progress fill written as
`drawbox=w='(t-T0)/D*W'` is drawn full (or not at all) on every frame. The H track builds the fill and playhead
from `color` sources overlaid with per-frame `x` expressions (`overlay` evaluates per frame).

## Audio/video sync with crossfades
Use `xfade` for video AND `acrossfade` for audio at the SAME `X`. Don't hard-concat video while
crossfading audio — the audio overlap shortens the track and you desync by `X` per cut.

## macOS: Voice Memos / screen recordings are TCC-protected
`Operation not permitted` even with the sandbox disabled: the OS blocks reading the Voice Memos app
container. Ask the user to drag the file into the project folder first; you cannot bypass it.

## Whisper hallucinates over trailing silence
Whisper emits repeated junk ("请不吝点赞订阅转发…") for silent tails. Find the real content end
and set `MAIN_DUR` to trim it (the main input uses `-t MAIN_DUR`).

## TTS acronyms (if you also make a practice audio with a TTS)
Spell initialisms phonetically or with periods so they aren't read as words: AI→"A.I.",
SDE→"S.D.E.", MCP→"M.C.P.", Vue→"View", jQuery→"Jay-Query", leetcode→"leet code". And the Kokoro
path needs `misaki[en]`; a pydantic/pydantic-core version mismatch may need `pip install
pydantic-core==<matching>`.

## Cover must be checked on the 4:3 crop, not the full frame
小红书 crops 16:9 covers to 4:3 (visible x[240,1680]). `make_cover.py` writes `cover43.png` — judge
that. Keep all cards inside x[240,1680] and off the face (detect head x-range first).

## Shell cwd / cd
The sandbox resets cwd between calls and `cd` can trigger a permission prompt. Always use absolute
paths in commands (the scripts and run.sh already do).

# V track gotchas (vertical iPhone pipeline)

## xfades swallow the first syllable of every hook (and the last one, and the body's first word)
A 0.3s `xfade` + `acrossfade` fades the incoming clip in over its first 0.3s of output, which at
1.65x is about 0.5s of speech. A half-sentence hook starting on an English word lost its first
syllable, and the first word of every hook after the first was soft.
Fix, built into `scripts/montage.py` (both tracks) on `vstudio.cut.xfade_assemble(mute_pad="both")`:
- at every dissolve the incoming clip starts XF*speed earlier and the outgoing clip runs XF*speed longer,
  both muted, so the dissolve plays over silence (an outgoing hook's last syllable was faded too before)
- the body gets `tpad` (cloned first frame) and `adelay` of XF, since nothing precedes body second 0
Check with an RMS envelope: full level right up to each dissolve, silence (or the whoosh SFX) inside it,
full level right after it.

## Concat-joined bodies carry ~1 ms timestamp jitter
Parts joined with the concat demuxer get timestamps a millisecond off the 1/30 grid. `cut.cut_segments` seeks
with an accurate `-ss`, so a frame sitting 1 ms early is dropped and the whole range shifts one frame (and the
last frame goes missing). `bodycut.mux` snaps timestamps back to the grid while stream-copying
(`setts=pts=round(PTS*TB*30)/(TB*30)`); every V-track cut and compose's base input go through it.

## Never trust ASR on a 1-2s sped-up clip
Whisper returns unrelated words, 「如何如何如何…」 loops and similar garbage. Slow the clip back with
`atempo=1/HOOK_SPEED` and give it a term prompt, or use the RMS envelope. The prompt can also make
whisper *drop* the prompted word, so test with and without it.

## iPhone HDR clips
HLG 10-bit HEVC with a -90 rotation, sometimes 120fps. A plain ffmpeg re-encode (no tone-map) looks
washed out. `prep_sources.sh` uses macOS `avconvert -p Preset1920x1080` when present (correct SDR H.264),
else ffmpeg `zscale` + `tonemap=hable` (needs ffmpeg built with libzimg; Homebrew's default formula
lacks it), else `libplacebo`, else it warns. Force a backend with `TONEMAP=ffmpeg|avconvert`.
Compare one frame from each backend before committing to a long retouch.

## Newer ffmpeg removed `-filter_complex_script`
`-/filter_complex file.txt` only exists on 7.1+. The scripts pass the graph text inline with
`-filter_complex "<contents>"`, which works on every version, and keep the file on disk for debugging.

## bt709 tags don't stick on a rawvideo pipe
Output flags like `-color_trc` are ignored when the input is rawvideo. Use
`-bsf:v h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1`.

## Frame-exact cutting
Per-segment `ffmpeg -ss A -t D` drifted 0.57s of A/V offset over 163 segments, because each segment
can carry one extra frame. Cut video with `trim=start_frame:end_frame` on frame-quantized times and
splice audio with numpy at the same quantized boundaries (`vstudio.cut.cut_segments` does both). The concat
demuxer with `-c copy` and `-video_track_timescale 30000` keeps frame COUNTS exact, but see the timestamp jitter
note below before cutting such a file again.

## Whisper word timestamps
- A word's *start* swallows the pause before it, and a word's *end* runs early (the sound continues). The
  shared cleanup (`vstudio.cleanup`) therefore cuts a word edit from the silence after the previous kept word to the
  silence before the next one (quiet-run edges ± pad, measured on the audio), never inside a kept word.
- A whisper pass over a silent tail emits bursts like 「feed feed feed」 with zero length. `vstudio.asr` drops them,
  and `cleanup.analyze` lists hallucinated segments as `asr-noise` CONFIRM rows instead of silently keeping them.

## Pass-1 edges pull in neighbour syllables
The old pass-1 snap searched voiced audio 0.08 s before / 0.10 s after each hand-written range and merged runs across
gaps up to MAXGAP (0.2 s), so the tail of the previous word or the onset of the next one (a stray 就是 / 然后 /
「情况」) used to ride along. `cut_pass1` now snaps with `cleanup.snap_range`: the start backs off to before its first
word's onset, the end runs over the last word's real tail, and neither passes the neighbouring whisper words of
`a<N>.json` (`cleanup.word_limits`). Still read the review sheet / the strict-pass word list for leftovers.

## Pause squeeze cannot shorten a drawn-out vowel
The cleanup's pause edits only shorten silence between voiced runs. A held syllable (a 2-3 s 「比…」) is one continuous
voiced run, so it stays at full length. Options: cut the range in two around the hold in `edit_list.py`
(a jump in the vowel is usually inaudible at 1.1x), or leave it and flag it to the creator.

## Re-applying a pass to an already-cut body
Before the demo-round fix, `strict_pass apply` and `drop_pass` rewrote `segs.json` in place, so re-applying strict
after a drop cut the full body with the dropped timeline. Passes now derive from immutable `segs.<stage>.json` files
and refuse a body whose length does not match the parent (see vertical_pipeline.md step 6).

## Re-cuts must not re-run the retouch
The retouch takes about 1s/frame. `strict_pass.py` and `drop_pass.py` cut the already-retouched body.
Effects are anchored by sid, so a re-cut needs no manual remapping. Effects keyed in raw seconds had
to be remapped by hand three times in one session.

## MLS face warp leaves streaks at the ROI edge
Feather-blend the warped ROI back into the frame. `vstudio.retouch.retouch()` does this with a feathered
face-region ellipse (`region=True`, the default); don't call `warp_face` alone on video frames.

## Landmark jitter makes the slimmed jaw wobble
Per-frame landmarks jitter by a few px. `retouch_video.py` EMA-smooths them (a=0.55) and resets the
filter on a jump > 25 px mean (a cut), so it never lags across a cut.

## Overlays on a punch-in shot
At 1.32x zoom the chin drops to about y 1100. Pop words go at y ≥ 1260 and stamps between y 1050 and
1340. With a face track, compose moves a pop word below the chin and a stamp STACK (stamps sharing t1) as one
block below the chin or beside the face when it would cover the face core (printed as "moved"); still check. Stamps must stay at x_left ≤ 480, because 小红书 buttons sit on the right in the lower half, and
the bottom stamp must clear the subtitle at 1525.

## Don't sed-patch output paths in a test copy
A test run of a cover template overwrote the real cover because a sed on `OUT` didn't match. The cover
now reads `COVER["OUT"]` from the config; for a test, copy the config and change `OUT` by hand.

## Cover frame seek
`ffmpeg -ss T` on a concatenated body can land on a different frame than `cv2` frame index `T*30`.
Choose with `pick_cover_frame.py`, read the frame by index, then always look at the result.
