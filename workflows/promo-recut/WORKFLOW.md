# promo-recut

**Use when** someone has a talking-head recording about something they made or found and wants a premium
16:9 short (and optionally a 9:16 version) for 小红书 / YouTube / B站. The talk is tight-cut, and the
talking head slides into a split-screen next to 3D screenshot cards that scroll to whatever is being
discussed. The edit adds highlighter sweeps, chips, keyword subtitles, punch-ins, a freeze-frame with a
prompt card zooming out of a screenshot, and a zoom-through into a framed highlights montage. It finishes
with an outro stamp, an end card, a chapter progress bar, a cover and the post copy.

**Inputs → Outputs.** `input/talk.mp4` (talking head) + screenshots (PNG/JPG) + optional `input/highlights.mp4`
+ links → `work/` (graded raw, `body.mp4`, `outro.mp4`, `montage.mp4`, `layout.json`), `promo/` (HyperFrames
project, `index.html`, subset fonts), `promo-vertical/` (optional), `my-promo.mp4` (-14 LUFS, BT.709,
faststart), `cover-4x3.jpg` / `cover-16x9.jpg` / `cover-3x4.jpg`, `post.md`.

Everything content-specific lives in ONE project config: `promo.config.yaml` (or `.json`). It holds the KEEP
spans, DROP/PATCH times, subtitles, cards and their highlight rows, chips, hold point, montage clips and
labels, chapters, stamp and end card, the cover and the post. Start from
`$VSTUDIO/workflows/promo-recut/examples/promo.config.example.yaml`, which documents every key. Taste
(rates, loudness, brand colours, title length, tags) comes from the persona (`persona.local.yaml`).

## Pipeline (run from the project dir; `$VSTUDIO` = repo root)

```
my-promo/
  promo.config.yaml      input/talk.mp4  input/highlights.mp4  input/*.png
```

1. **Transcribe + find what to cut**
   ```bash
   cp $VSTUDIO/workflows/promo-recut/examples/promo.config.example.yaml promo.config.yaml   # then edit
   python3 $VSTUDIO/workflows/promo-recut/scripts/tight_cut.py promo.config.yaml --suggest
   ```
   The first run writes `work/audio.json`, using whisper with word timestamps (`mlx_whisper` on Apple
   Silicon, otherwise `faster_whisper`). `--suggest` prints three kinds of candidates: fillers
   (然后/就是/那个/嗯/um/uh, including fillers split across tokens or glued to the next word), immediate
   repeats (A A, A B A B), and **long words with an energy dip inside**, where whisper merged a filler into
   the word. For the last kind it proposes a PATCH start read off the RMS envelope. Listen to each one
   (`ffplay -ss <t-0.5> -t 2 work/audio.wav`) and copy what's right into `cut.drop` / `cut.patch`. Set
   `cut.body` / `cut.outro` KEEP spans by sentence.
2. **Tight cut + montage + layout**
   ```bash
   python3 $VSTUDIO/workflows/promo-recut/scripts/tight_cut.py promo.config.yaml
   python3 $VSTUDIO/workflows/promo-recut/scripts/tight_cut.py promo.config.yaml --verify
   ```
   This grades the raw once (`grade`, optional `hdr_tonemap`) and cuts the KEEP spans minus DROP words.
   Pauses longer than `pause_threshold` (0.35 s) are squeezed to about 0.14 s. Each join gets a 15–20 ms
   audio fade, and the voice is normalised to persona `audio.voice_lufs`. The step builds the highlights
   montage with baked 0.3 s internal crossfades and writes `work/layout.json` with raw→cut maps and word
   times. **`--verify` runs ASR on the cut files** and flags leftover fillers and repeats. Also listen to
   every join before going on.
3. **Subtitles + cards**
   ```bash
   python3 $VSTUDIO/workflows/promo-recut/scripts/tight_cut.py promo.config.yaml --draft-subs   # paste, then edit
   python3 $VSTUDIO/workflows/promo-recut/scripts/find_rows.py input/shot-post.png --preview work/rows.png
   ```
   Write subtitles in raw seconds and wrap the key term in 【】. `find_rows.py` measures text-row bands with
   numpy. Use those y0/y1 rows for `cards[].highlights`, `box` and `scroll`. Its `width_frac` column is a
   good starting highlight width.
4. **Build the HyperFrames project**
   ```bash
   python3 $VSTUDIO/workflows/promo-recut/scripts/build_promo.py promo.config.yaml
   python3 $VSTUDIO/workflows/promo-recut/scripts/build_promo.py promo.config.yaml --orientation vertical   # optional
   cd promo && npx hyperframes lint && npx hyperframes snapshot --at <split-in>,<hold>,<zoom-through>,<outro> --no-end
   ```
   This writes `index.html` and `timeline.json`, copies media into `assets/`, and extracts the freeze frame.
   It also copies **Noto Sans SC + STIX Two Text** from `vstudio.config.FONT_DIR` and subsets them with
   fontTools to just the characters in the config (≈60 KB per CJK weight). Look at snapshots taken
   **mid-transition**, not only mid-scene. Expect 0 lint errors. The `nested_structure_needs_subcomposition`
   warnings are advisory.
5. **Render + deliver**
   ```bash
   bash $VSTUDIO/workflows/promo-recut/scripts/export.sh promo my-promo.mp4 delivery
   ```
   This renders with HyperFrames, runs a two-pass loudnorm to persona `audio.loudness_lufs` (-14), writes
   BT.709 colour tags into the H.264 stream without re-encoding, and adds `+faststart`. It then prints the
   streams and the measured loudness. Use `--skip-render <raw.mp4> <out.mp4>` to redo only the delivery
   step.
6. **Cover + post**
   ```bash
   python3 $VSTUDIO/workflows/promo-recut/scripts/make_cover.py promo.config.yaml
   python3 $VSTUDIO/workflows/promo-recut/scripts/post_copy.py promo.config.yaml
   ```
   The cover takes a frame from the talk (or a given image) and retouches it through `vstudio.retouch` (slim,
   eye, de-shine, skin, light makeup, optional body slim). It crops around the detected face. Landscape
   sizes get a split cover: photo on one side, and on the other a dark panel with quote, title + highlighted
   term, a framed highlights thumbnail, chips, a red tag and a 记笔记 tag. Portrait sizes stack the photo on
   top. The post gets the title (length checked with `xhs_len`), body, links, a chapter timeline from
   `promo/timeline.json` and tags.

## Timeline model (what build_promo computes)

`body` plays at `rates.body` and is split at `hold.at` into `body` + freeze image + `body2`
(`data-media-start`). These share track 2 back to back. The montage starts `zoom_through` s (0.5) before
the body ends and runs on its own track 3 at `rates.montage`. The outro starts where the montage's nominal
length ends, while the montage clip keeps running another `zoom_through` s underneath. The end card follows.
Raw second → final second is `BT(raw) = raw2cut(raw)/rate (+ hold if raw ≥ hold.at)`, so you never type a
final-timeline time. Chapter anchors are raw body seconds or `start` / `montage` / `outro`.

## Hard-won lessons

- **Overlapping clips need separate tracks and a known audio owner.** Body and montage overlap during the
  zoom-through, so they sit on different `data-track-index` values. Only overlap where the outgoing clip is
  silent (the cut adds about 0.1 s of tail after the last word). If an overlap would play two voices, set
  `data-volume="0"` on one, or use a muted copy, rather than relying on a fade.
- **The outgoing scene must stay alive during a transition.** `body2` runs until `M + TZ`, and the montage
  runs `TZ` past the outro start. If a clip ends exactly when its exit animation starts, the transition shows
  the plate (a black flash).
- **Overlay start states must be `opacity: 0` in CSS** (`gsap_fullscreen_overlay_starts_visible`). This
  covers the dim layer, prompt box, screen, outro wrap, badges, stamp and end-card lines. Otherwise
  seek-based rendering shows them on frame 0 or before their `fromTo` runs.
- **Chapter labels need a scrim.** Small labels over bright footage are unreadable. The bar sits on a
  bottom gradient (`#bar-scrim`), and labels get a text shadow.
- **Whisper merges fillers into neighbouring words.** A "word" that is too long for its characters usually
  starts with a hidden 然后/嗯. DROP alone won't fix it, because the drop test uses word START. Check the RMS
  envelope (`--suggest`) and PATCH the start to where energy rises after the dip.
- **ASR the cut to verify it** (`--verify`). Joins that look right on the word list can still swallow a
  syllable or keep half a filler.
- **Captions must clear before a zoom-through.** build_promo clips any cue that crosses `M + TZ` so it ends
  at `M - 0.08`. A caption flying into the montage frame looks broken.
- **Measure screenshot rows, don't guess.** Highlight bands and red boxes use image-pixel rows from
  `find_rows.py` (row-band detection on the grey-level difference from the background). Card scale is
  `card_width / image_width`, and build_promo applies it.
- Adjacent card windows closer than 0.8 s are merged into one split, so the face doesn't bounce back to
  full frame between cards.
- Montage clips with label `null` are transitional fragments. The previous step label continues over them.
- Fonts: only Noto Sans SC / STIX Two Text (OFL), subset per video. A system CJK font that exists only on
  your machine silently falls back in the headless renderer.

## Geometry / vertical

`build_promo.py` has a `GEO` table per orientation (card box, split inset, subtitle line, bar, screen frame,
label positions). Override any value with `layout.horizontal.*` / `layout.vertical.*` in the config.
Vertical stacks the face band (top) above the card (bottom). It crops the 16:9 talk with `object-fit: cover`,
so set `layout.vertical.face_pos` if the speaker is off-centre.
