# call-clips craft notes

The reasons behind the pipeline, measured numbers, and the gotchas found the hard way.

## Timeline maths (build_clips.py)

- Everything in `clips.json` is in **source** seconds; `build_clips.py` is the only place that
  converts to final time, so a speed change never desyncs subtitles, panels or the face track.
- **Assemble before tracking, never after.** The face track, subtitles and panels then share
  one frame space and cannot drift.
- Offset of piece k in the dissolved output = `sum(durations[:k]) - sum(xfades[1..k])`, which is
  exactly the `offset` xfade wants for that join. One formula, both uses. Durations and fades are
  whole frames (`vstudio.cut.xfade_assemble`), so the maths matches the encoded file exactly.
- Fades: node-card seam / hook join / `"~"` = 0.5s (`XFADE`); silent trim (`null`) = 0.16s
  (`TRIM_FADE`, a redaction lands as a breath; three chained 0.5s dissolves through one paragraph
  sound broken); auto-trim join = 0.06s (`AUTO_FADE`, just hides the click).
- `render_timeline()` chunks timelines over 30 pieces (a long-form with auto-trim has 130+); the maths
  is linear, so the result is identical to one pass.
- Subtitles are suppressed ±1s around each node card; a silent trim only clears its dissolve.
  A segment straddling a cut keeps only the words whose midpoint is inside the piece, so a
  trimmed stutter also leaves the caption.
- A panel may stay up **across** silent trims but never across a node card, and is forced to end
  1.9s before one, or the frame carries two cards. Overlapping panels are trimmed to clear the
  next; a panel squeezed under 4s or opening <2.5s after a card prints a WARN.

## Windows, node cards, redaction

- Each seam between windows is cut material. A carded seam dims the footage to ~30% and a
  bordered card names the section being jumped into; without it the jump reads as a broken edit.
- Cut where the speaker is *between* thoughts: dump the transcript around a candidate seam and
  drop the connective rambling (对/嗯/我觉得这也是/我刚才想说什么). Do not cut mid-sentence to hit
  a duration.
- **Redacting means re-cutting, not rewording.** The phrase is in the audio, often also in a hook
  and a panel. Excise the windows (`null` seams), rebuild, re-transcribe the render and grep it.
  Also check clips the user already published and tell them.
- Redaction forces a rewrite of nearby edit points: dropping the phrase that introduces a "他"
  leaves the pronoun dangling, so drop the clause that uses it too and restart at a sentence
  that stands alone.

## Hooks and note panels

- Two 4–6s pulls from inside the same clip (≈7s after speed-up); pick the *payoff*, not setup.
- 记笔记 card: dark card, brand-accent header, highlight 记笔记 ↓ tag, dot bullets, `PW = 940`
  in the vertical frame. 3–4 bullets; renderers warn when a card is taller than its tile — a card
  spilling into a visible speaker's tile covers the wrong face.
- Cover: sample at `first_panel_anchor + 4s` so the cover shows a note card (the 干货 signal on
  小红书).

## Speaker attribution

`speaker_timeline.py`: inner-lip gap (landmarks 13/14) normalised by face height (10–152), std
over a 0.8s window per tile, sampled every 3rd frame; the loudest mouth wins if it beats the
runner-up by an 18% margin, else "both". If one tile wins ~100% of a long stretch, check frames
before believing it.

## Quote compilations (金句集锦)

One clip whose `windows` are the quotes, joined by `"~"` in `nodes`, `hooks: []`,
`"quote_cards": true`; each panel is `[anchor, dur, speaker, [text]]`, rendered (trio renderer)
as a big quote card sized to its text. Put `\n` to break by meaning. End every window on the
sentence's real whisper segment end and check the subs dump for truncated last words; stop a
quote before someone else chimes in.

## Auto-trim and the editor pass

- `vstudio.cut.find_cuts` (CLI report: `find_disfluencies.py`; rules in `lib/vstudio/cut.py`) removes ~3%: pauses > 0.6s
  (keeps ~0.36s), restarts, back-to-back repeats, filler-only segments. Silence comes from audio
  energy because whisper's word timestamps abut; every edge snaps to the quietest frame between
  word midpoints. One-word repeats across a sentence break are never cut; emphasis doublings are
  whitelisted.
- A demanding listener still hears restarts and broken-off phrases. What met that bar: dump each
  keep-window as `speaker: [t]word [t]word ...` (`transcript_tools.py editor`, ~7 min chunks),
  have parallel reviewers (human or LLM subagents) act as dialogue editors marking
  `[from_onset, next_kept_onset, why]` for false starts, restarts, back-to-back repeats, abandoned
  fragments and sentence-opening filler. Merge into `editor_cuts.json`, set `"extra_cuts"`,
  rebuild. Editor cuts snap to word boundaries. Together ≈10% removed.
- Review the merged list first: sort by length, read the longest and a random sample. Editors
  occasionally mark two parallel points as a restart («没有很 X 的学历 / 没有很 X 的公司的背书»
  are two points, not one).

## Masking: sticker sizing (derived, not guessed)

Bundled cat: opaque head ellipse `rx = 0.344`, `ry = 0.309` of the PNG, centred at `y = 0.531`.
A tracked face is about `h/w = 1.26`. To cover a face oval grown 10%:
`sticker_h >= 0.55 * face_h / 0.309 = 1.78 * face_h = 2.25 * face_w` → `--scale 2.40` clears it;
`--y-offset -0.031` puts the head centre on the face centre (more negative exposes the chin).
The dog shares the ellipse, so the same numbers pass 100%. New sticker → sweep:
```bash
for s in 2.0 2.2 2.4 2.6; do for y in -0.10 -0.03 0.0; do
  python3 $S/verify_coverage.py --track t.json --sticker new.png --scale $s --y-offset $y
done; done
```
`verify_coverage.py` samples the grown face **oval** (not its bbox, which would never reach 100%)
against the sticker's alpha>200 footprint on every frame.

## Tracking

- `track_face.py`: MediaPipe face landmarker, VIDEO mode, gaps linearly filled, EMA smoothing
  (`--smooth 0.25` for position, half that for size), size floored at 90% of the run median
  (a shrinking sticker is the risky direction).
- A ~55px face in a 640×360 tile gets lost; for a tiny face (e.g. a portrait phone video
  pillarboxed in a wide tile) give the guest a `search` rect inside the region and `upscale: 2`.
- Each sticker is pasted into a copy of its own tile, so it can never bleed into a neighbour.
- `--reuse` re-renders without re-tracking; any timeline change (one hook end, one trim)
  invalidates every track — batch fixes before a long tracking pass. For subtitle text without
  cutting, do a dry `--subs-only --reuse` pass under a temporary id.

## Name badges

Call apps stamp the real name at each tile's bottom-left, and it survives the crop. The label
chip is square-ish (small radius, not a pill) and **flush** to `x = ox` and the tile bottom, so it
fully covers the badge; an inset or pill chip leaves the badge's edge visible.

## Platform safe zone (vertical)

On 小红书 / Douyin / Reels on a phone, the top ~230px of 1080×1920 sit under the status bar and
nav, the bottom ~270px under title/caption/buttons, plus a right-side button column.
`render_trio.py` keeps everything in y 240..1660: title at 240, guest row 440..940, host
952..1492 (tile cropped 640×320), subtitles from 1500, hook badge on the guest row. Covers put
the headline at y≈300 and the still inside the 3:4 feed crop (`cover_title_y`,
`cover_strip_y`, `cover_band`). `render_vertical.py` still uses the older full-bleed layout
(title at 150, tiles 330..1560, subs at 1654) — move it to the trio geometry before relying on it
for those platforms.

Final files are Apple-friendly: high@4.2 (trio renderers), bt709 written into the h264 VUI via
`h264_metadata` (container flags alone leave iOS guessing), `avc1` tag, 48k AAC, faststart.

## Landscape long-form

- Two-person: two 960-wide tiles, each a centred `--crop-w` (default 512 of 640) scaled to
  960×675 — fills the frame instead of leaving a dead band under the subtitles. Measure first:
  track the guest, sample-detect the host, keep ~80px beyond both speakers' extremes.
- Three-person: three 640×720 tiles, each a 320×360 window following a 6s-smoothed face track
  (`"track_host": true`; the host track only steers the crop).
- Bilingual subs: Chinese 50px over English 38px dimmer, one cached strip per cue. Burn in *and*
  ship `.srt`s (viewers can turn them off; YouTube indexes the text). Translate for spoken
  readability, dropping false starts; leave code-switched English terms alone.
- Long-form gets 4 hooks at 1.25× (≈15s) and ~1 panel per minute. Chapter timestamps for the
  description come from `node_cards` in the title json, offset ~1s so the link lands after the
  card.
- Head-only sticker vs full-tile avatar: the avatar (`cat_avatar.*`, verified pixel-wise by
  `verify_avatar.py`) is a harder guarantee but loses every gesture. Ask before using it.

## Thumbnails (1280×720)

- Headline owns the top ~44%, set far larger than feels right (read at ~210px wide in a feed);
  white setup line + accent punch line, heavy black stroke; yellow out-reads teal.
- Both/all speakers large along the bottom, tightly cropped, one per side.
- Nothing under ~60px; no eyebrow, no small print.
- Pick the frame by geometry: the sticker's top edge must clear the tile top
  (`cy + y_offset*h - h/2 - tile_y >= 0`), or the ears are already clipped. Anchor crops on the
  top of the head. `make_thumb_trio.py` auto-picks a moment with no card/panel on screen.
- Variants are a config edit (`thumb` block); render several and let the user pick.

## Text rendering

- Many ffmpeg builds lack `drawtext` and `subtitles`/`ass`; all text is PIL in the frame loop.
- Fonts come only from vstudio roles (`cjk`, `cjk-bold`; Noto Sans SC by default).
- Balance two-line subtitles around the middle; never split inside a latin/number run.
- Keep extending term fixes rather than hand-editing subtitle JSON.
