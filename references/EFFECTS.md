# EFFECTS — every visual / audio effect in video-studio, and how to reuse it

Paths are relative to the repo root (`$VSTUDIO`). The **Engine** column says how the effect is drawn:

- **PIL**: a per-frame Python pass on numpy frames (PIL, OpenCV or numpy), piped to ffmpeg.
- **ffmpeg**: a filter graph only.
- **HF**: HyperFrames HTML + GSAP, rendered by `npx hyperframes render`.
- **audio**: numpy audio or an ffmpeg audio filter.

Most effects can only be reused inside the same engine family, so pick the engine first. A HyperFrames project
uses `vstudio.hf`. A per-frame Python compositor uses `vstudio.overlays` / `vstudio.draw` images or photo-story's
frame functions. An ffmpeg graph uses the filter strings. **Transitions are the exception**: `vstudio.xfade` gives
every transition name (the 11 HF types, the photo-story kinds, common ffmpeg xfade names) an implementation in all
three engines (`xfade.blend`, `xfade.ffmpeg_transition`, `xfade.hf_transitions`); see the coverage matrix in section 7.

Find effects from code: `effects.find(engine="ffmpeg", energy="low", text="zoom")`, `effects.get("light-leak")`,
or `python -m vstudio.effects --list --engine hyperframes` / `--show <id>`.

**HyperFrames rules** (`vstudio.hf` already follows them):

- Overlays start at `opacity: 0` in CSS.
- Never use `fromTo` twice on one target; later moves use `to()`, or `immediateRender: false` with an identity
  `tl.set` at t=0.
- The outgoing scene or clip must stay alive (longer `data-duration`) for the whole transition.
- Asset paths are project-root-relative (`assets/x.png`), never `../`.

Full list: `workflows/explainer/references/pitfalls.md`.

**The `vstudio.hf` API**. Every function returns `{"css", "html", "js"}`:

- Put the css in one `<style>`, the html in the root composition, and the js after `hf.prelude()`, which defines
  `tl` and `$`.
- Numbers and lists are inlined as JSON. Wrap a value in `hf.JS("D.X")` to reference your own data object
  instead.
- `hf.indent(s, n)` nests a snippet inside a block.

Worked users: `workflows/promo-recut/scripts/build_promo.py` (almost every generator) and
`workflows/explainer/scripts/make_index.py` (transitions).

---

The tables below are **generated** from the registry in `lib/vstudio/effects.py`. Do not edit them by hand:
change the registry, then run `PYTHONPATH=lib python3 -m vstudio.effects --write-md`. `tests/test_effects.py` fails
if the block is stale. To add an effect or port one to another engine, see [ADDING_EFFECTS.md](ADDING_EFFECTS.md).

<!-- BEGIN GENERATED: effects registry (python -m vstudio.effects --write-md) -->

## 1. Camera / zoom

| Effect | What | Engine | Where | Params | When to use | Energy | Hold / duration | Max uses | Reuse | Tested |
|---|---|---|---|---|---|---|---|---|---|---|
| Punch-in (eased) <sub>`punch-in`</sub> | Talking head scales up for a window, then back | HF | `lib/vstudio/hf.py:punch_in` | `scale=1.14`, `in_dur=0.45`, `out_dur=0.5` | Stress a sentence in a talking head without cutting | med | 0.45 s in, window 2-5 s, 0.5 s out | ~1 per 20 s of talk; vary windows | `hf.punch_in([[12.0, 15.5]])` on an inner wrapper around your video | `test_hf.py` |
| Punch-and-stay <sub>`punch-and-stay`</sub> | One punch that holds (e.g. on the punchline) | HF | `hf.py:punch_at` | `scale=1.16`, `dur=0.5`, `origin=50% 38%` | Land a punchline or a reveal and stay there | high | 0.5 s move, holds to the next cut | 1-2 per video (A7) | `hf.punch_at("#ow", 41.2)`, then `hf.stamp(..., at=42.1)` | `test_hf.py` |
| Wrapper zoom entrance <sub>`wrapper-zoom-entrance`</sub> | Settles from 1.15x and transparent | HF | `hf.py:enter_zoom` | `from_scale=1.15`, `dur=0.6` | Bring in any section wrapper (outro, new section) | med | 0.6 s | 1 per section | Use it to bring in any section wrapper (promo's outro) | `test_hf.py` |
| Per-sentence punch-in (hard cut) <sub>`per-sentence-punch`</sub> | Face-centred zoom per sentence: EMPH sids get emph_zoom, odd sids get alt_zoom | PIL | `workflows/talkinghead/scripts/vertical/compose.py:zoom` | `emph_zoom=1.32`, `alt_zoom=1.16` | Vertical talking head with jump cuts between sentences | med | one sentence (2-6 s) | every other sentence; EMPH <= 1 in 4 | Copy `zoom()`; in HF use `hf.punch_in` | - |
| Ken Burns (8 motions) <sub>`ken-burns`</sub> | Slow pan / zoom / 3D turn on one photo (`in`, `out`, `panL`, `panR`, `up`, `down`, `still`, `flip`) | PIL | `workflows/photo-story/scripts/photostory/shots.py:ImageShot` | `motion=in`, `z=1.12`, `c=(0.5, 0.5)` | Any still photo held >= 2 s | low | 3-6 s per photo | unlimited, but alternate directions | `ImageShot(C, sh, name).frame(lt)` with a `Ctx`; in HF use the hyperframes-keyframes skill | - |
| Code-zoom cut-in <sub>`code-zoom`</sub> | Tighter crop on the code block, centred on the code-colour centroid, with a seamless join | ffmpeg | `workflows/longform-to-short/scripts/zoom_targets.py`, `build_timeline.py:zoom_crop` | `zoom.box=[736, 336]`, `zoom.tol=colour tolerance` | Screen recordings where the code / panel is unreadable at full frame | low | the whole window being read | as needed (it is legibility, not a flourish) | `crop=w:h:x:y,scale=W:H` on the window; zoom_targets finds any flat-coloured panel | - |
| Zoom-through into a framed screen <sub>`zoom-through`</sub> | The shot scales 1.35x and blurs out while the framed screen lands, then drifts | HF | `hf.py:zoom_through` (+ `framed_screen`) | `scale_in=0.84`, `drift=0.85` | Go from a talk into a highlights reel or demo | high | ~1 s move, then the reel | 1 per video (A7) | `hf.zoom_through(at, until)` + `hf.framed_screen(...)` | `test_hf.py` |
| Stabilize <sub>`stabilize`</sub> | deshake + crop | ffmpeg | `workflows/vlog/scripts/build_vlog.py:stab_prefix` | `stab_rx/ry=32`, `stab_zoom=0.93` | Handheld phone / walking clips | n/a | whole clip | unlimited | Prepend `deshake=rx:ry:edge=clamp,crop=iw*k:ih*k` to any chain | - |
| Loupe <sub>`loupe`</sub> | A magnifier travels a path over the photo | PIL | `photostory/overlays.py:overlays` (`loupe=`) | `loupe=[(x, y), ...]`, `loupe_mag=2.3` | Show a detail inside a photo (inscription, brushwork) | low | 3-5 s | 1-2 per video | photo-story shot opt; elsewhere copy the block (needs `C.b`) | - |

## 2. Layout / split

| Effect | What | Engine | Where | Params | When to use | Energy | Hold / duration | Max uses | Reuse | Tested |
|---|---|---|---|---|---|---|---|---|---|---|
| Split screen <sub>`split-screen`</sub> | Full-frame face clipped to an inset() and slid aside per window; windows < 0.2 s apart are bridged | HF | `hf.py:split_screen`; geometry in `build_promo.py:GEO` | `dur=0.7`, `bridge=0.2` | Talking head + something to show (screenshot, recording) | med | 0.7 s in, window >= 3 s | the main device of a promo; 1 star use + repeats | Any HF project with a talking-head wrapper; fill the freed side with `screenshot_cards` or a `<video>` | `test_hf.py` |
| Vertical face band + card <sub>`vertical-face-band`</sub> | 9:16 promo: face band on top, card below | HF | `build_promo.py:GEO["vertical"]` | `split_inset=inset(200px 40px 1000px 40px round 28px)` | Vertical promo with screenshots | med | same as split windows | as split screen | `--orientation vertical`, or pass GEO values to `hf.split_screen` | - |
| Call layouts <sub>`call-layouts`</sub> | 2 tiles stacked, trio (2 masked guests + host), landscape pair, landscape trio (6 s-smoothed reframe) (`vertical`, `trio`, `landscape`, `landscape-trio`) | PIL | `workflows/call-clips/scripts/render_vertical.py`, `render_trio.py`, `render_landscape.py`, `render_landscape_trio.py` | `TILE_H=608`, `REFRAME_S=6` | Zoom / Meet / Teams recordings | low | whole clip | one layout per clip | `build_clips.py --renderer <file>`; `--guest-region` / `--host-region` | - |
| Fit: crop / pad / blur-pad / stretch <sub>`fit-modes`</sub> | Fit any aspect into the canvas (`crop`, `pad`, `blur`, `stretch`) | ffmpeg | `lib/vstudio/cut.py:fit_chain`; `vlog/scripts/build_vlog.py:fit_chain` | `fit=crop` | Mixed-aspect sources in one timeline | n/a | whole clip | unlimited | `cut.fit_chain(size, mode)` or `xfade_assemble(fit=...)` | `test_core.py` |
| Browser-chrome crop <sub>`browser-chrome-crop`</sub> | Detects doc / browser headers per span and crops them plus the bookmark bar, then fits and pads | ffmpeg | `longform-to-short/scripts/geometry.py`; `render.py` | `browser_header_px=115` | Screen-share recordings | n/a | per span | unlimited | Run geometry.py on any screen recording and use the crop spans | - |
| Photo layouts <sub>`photo-layouts`</sub> | Multi-photo compositions in the picture box (`collage`, `film`, `split`, `grid`, `rows`, `tilt`, `deck`, `quote`, `route`, `medal`) | PIL | `photostory/shots.py` (`CollageShot` ... `MedalShot`; factory `build(C, sh, k)`) | `src="collage:a,b,c"`, `yaw=tilt angle` | Comparisons, sets, routes, quotes inside a photo story | med | 3-6 s | vary kinds; each kind 1-2 per video | `shots.build(C, sh, k).frame(lt)` | - |
| Video in a photo story <sub>`video-in-photo-story`</sub> | Pre-cut, graded clip read frame by frame | PIL + ffmpeg | `photostory/shots.py:VideoShot`, `prep_video` | `speed=1.0`, `grade=VEQ` | Short live moments between photos | med | 2-5 s | unlimited | photo-story spec `src="v1234"` | - |

## 3. Cards & overlays

| Effect | What | Engine | Where | Params | When to use | Energy | Hold / duration | Max uses | Reuse | Tested |
|---|---|---|---|---|---|---|---|---|---|---|
| 3D screenshot card <sub>`screenshot-card-3d`</sub> | A card slides in with rotationY -28 to -6 deg, drifts, then leaves | HF | `hf.py:screenshot_cards` | `card_w=760`, `accent=theme` | Show a screenshot while the speaker talks about it | med | card on screen >= 3 s | 1 card per claim; the 3D entry stars once, later cards can enter flatter | `hf.screenshot_cards([dict(id="c1", img=..., w, h, s, e, scroll=[[3, 0]])])` | `test_hf.py` |
| Card scroll keyframes <sub>`card-scroll`</sub> | The image scrolls to bring row y to the top at time t | HF | `hf.py:screenshot_cards` (`scroll=[[t, y], ...]`) | `scroll=[[t, y_img_px]]` | Long screenshots where the line being discussed is below the fold | low | 0.6-1.2 s per move | as needed | Find rows with `promo-recut/scripts/find_rows.py` | `test_hf.py` |
| Chips row <sub>`chips-row`</sub> | Pills pop in one by one; a star chip is gold; all fade at end | HF | `hf.py:chips` | `items=[[t, text, star]]`, `gold=#F4D35E` | List of features / tags | med | pop 0.3 s each, hold >= 1 s full | 1 row per section | `hf.chips([[3, "Writing", 0], [4, "Video", 1]], end=9)` | `test_hf.py` |
| Chip / badge / tag / stamp images <sub>`overlay-images`</sub> | Themed RGBA images for PIL / ffmpeg compositors (`outline`, `filled`, `star`, `tag`, `ghost`) | PIL + ffmpeg | `lib/vstudio/overlays.py:chip`, `badge`, `tag`, `stamp` | `style=outline`, `scale=1.0` | Any per-frame or ffmpeg compositor | low | hold >= 1 s | unlimited (each style stars once) | Paste with `draw.alpha_paste`; ffmpeg can overlay as `-loop 1` PNGs | `test_visual.py` |
| Badge (jingxuan / preview) <sub>`badge`</sub> | Solid label that slides in | HF + PIL | `hf.py:badge`; `overlays.badge` | `accent=theme` | Mark a section as highlights / preview | low | whole section | 1 per section | HF: `hf.badge("...", s, d, at)`; PIL: `overlays.badge("...")` | `test_hf.py` |
| Outlined tag <sub>`outlined-tag`</sub> | Fading pill (e.g. 'full version / excerpt / 1.1x') | HF | `hf.py:tag` | `pos_css=right:160px; top:956px;` | Context labels | low | section | 1-2 per video | `hf.tag(...)` | `test_hf.py` |
| Framed screen <sub>`framed-screen`</sub> | Rounded, shadowed screen playing a video on a grid backdrop; shrinks away at exit | HF | `hf.py:framed_screen`, `grid_backdrop_css` | `rate=1.0` | Any 'video inside a monitor' beat | med | length of the reel | 1 per video | `hf.framed_screen(src, start, dur, exit_at)` | `test_hf.py` |
| Notes panel <sub>`notes-panel`</sub> | Light theme card: small label, title, hairline rule, bullets (legacy: coloured header) (`paper`, `notes-red`, `notes-yellow`, `teal`, `navy`) | PIL + ffmpeg | `overlays.py:notes_panel`; per-row reveal in talkinghead `compose.py` (`PANELS`) | `width=620`, `theme=paper` | Summarise 2-4 points the speaker is listing | low | reveal 0.3 s per row; hold >= 2 s after the last row | 1 per topic | PIL image; burn with ffmpeg `overlay=...:enable='between(t,a,b)'`; for HF save a PNG | `test_visual.py` |
| Callout bubble <sub>`callout-bubble`</sub> | Speech bubble that slides up 24 px | PIL | `overlays.py:callout`; `compose.py` (`CALLOUTS`) | `max_w=560` | Side comments, asides | low | 2-4 s | ~1 per 30 s | Same as the notes panel | `test_visual.py` |
| Node card <sub>`node-card`</sub> | 'NEXT' seam card | PIL | `overlays.py:node_card`; `call-clips/.../render_vertical.py:render_node_card` | `eyebrow` | Topic change inside a clip | low | fade 0.35 s, hold ~1.5 s | 1 per topic change | Paste at a cut and fade over 0.35 s | `test_visual.py` |
| Quote card <sub>`quote-card`</sub> | Typographic quote: weight contrast, hanging opening mark, short accent rule | PIL | `overlays.py:quote_block`; call-clips `render_trio.py:render_quote` | `width=980`, `size=80` | Pull a strong line from a call | low | hold >= 2 s | 1-2 per clip | `overlays.quote_block([(main, 'main'), (sub, 'sub')], width)` | `test_theme.py` |
| Chapter rule <sub>`chapter-rule`</sub> | A hairline draws across with a small tracked label (02 · name) and optional title | PIL | `overlays.py:chapter_rule` (progress 0-1) | `progress=1.0`, `title` | A quiet section change instead of a full-frame chapter card | low | 2-3 s | 1 per section | `overlays.chapter_rule("第二部分", "先跑通，再优化", index=2, progress=p)` | `test_theme.py` |
| Lower third <sub>`lower-third`</sub> | Theme card with name and role, short accent rule | PIL | `overlays.py:lower_third` | `scale=1.0` | Introduce a speaker | low | 3 s | 1 per speaker | `overlays.lower_third("Name", "Role")` | `test_theme.py` |
| Circle-face list scene <sub>`circle-face-list`</sub> | Blurred bg, ringed circle crop of the face, title, popping tokens | PIL | `compose.py` (`blurbg`, `circle_inset`, `token_img`) | `R=290` | Listing items while still seeing the speaker | med | the list span (4-10 s) | 1-2 per video | Copy the 3 helpers | - |
| Shrink-to-card scene <sub>`shrink-to-card`</sub> | Frame shrinks to a 0.55x rounded card over a blurred copy, with title and lines | PIL | `compose.py:card` | `s=0.55`, `r=36` | A section summary over the speaker | med | 4-8 s | 1-2 per video | Copy `card()` + `blurbg()` | - |
| Privacy sticker <sub>`privacy-sticker`</sub> | Face-tracked sticker covering a participant, with a coverage proof | PIL | `call-clips/scripts/track_face.py` -> `apply_sticker.py`; `verify_coverage.py` | `scale=2.4`, `smooth=0.25` | Hide a participant's face | n/a | whole clip | unlimited | `track_face.py VIDEO --region ...`, then `apply_sticker.py VIDEO --track --sticker cat.png` | - |
| Camera-off avatar <sub>`camera-off-avatar`</sub> | Full-tile cat avatar | PIL + HTML | `call-clips/assets/cat_avatar.html`, `verify_avatar.py` | `--tile=960x540` | A participant with camera off | n/a | whole clip | unlimited | Render with `render_sticker.py --size 960x540` | - |
| Photo overlays <sub>`photo-overlays`</sub> | Develop, shimmer, dust, pounce holes, red pen, triangle, loupe, timeline, count-up, label (`develop`, `shimmer`, `dust`, `prick`, `hl`, `tri`, `loupe`, `tl`, `count`, `label`) | PIL | `photostory/overlays.py:overlays(C, sh, f, lt)`; `label` in `render.py` + `subtitles.make_label` | `fx=()`, `hl_t=0.3` | Point at something inside a photo story shot | med | per shot | each overlay stars once (A7) | Use them in a photo-story spec | - |
| Polaroid / taped card <sub>`polaroid`</sub> | Taped polaroid with a shadow and caption | PIL | `lib/vstudio/cover.py:polaroid`; `photostory/shots.py:make_card` | `rot=0` | Scrapbook / travel looks, covers | low | hold >= 1 s | unlimited in a scrapbook section | `cover.polaroid(img, 600, rot=-4, cap="...")` | `test_visual.py` |

## 4. Text & captions

| Effect | What | Engine | Where | Params | When to use | Energy | Hold / duration | Max uses | Reuse | Tested |
|---|---|---|---|---|---|---|---|---|---|---|
| Number counter <sub>`number-counter`</sub> | A figure counts up with ease-out, small label under it | PIL | `overlays.py:counter(value, t)` | `count=0.9`, `suffix` | A number the speaker says that matters (fans, years, money) | low | 0.9 s count, hold >= 1 s | 1-2 per video | `overlays.counter(7, t, label="粉丝", suffix="万")` | `test_theme.py` |
| Keyword subtitles (HF) <sub>`keyword-subtitles-hf`</sub> | Cue pops up 14 px and fades; highlighted term in the highlight colour | HF | `hf.py:subtitles` + `overlays.cue_html` + `overlays.hf_cue_css` | `geo=horizontal` | Every narrated HF video | low | per cue | always on | `overlays.cue_html(...)`, then `hf.subtitles(cues)` | `test_hf.py` |
| Burned subtitles (PIL) <sub>`burned-subtitles-pil`</sub> | Bold line with stroke, keywords in yellow, balanced CJK wrap | PIL | `lib/vstudio/draw.py:text_layer`; talkinghead `compose.py` | `stroke=6`, `sub_size=54` | Per-frame compositors | low | per cue | always on | `draw.text_layer("...", draw.load_font("cjk-bold", 54))` | `test_visual.py` |
| ASS subtitles <sub>`ass-subtitles`</sub> | libass burn-in with highlight and bilingual alt line | ffmpeg | `lib/vstudio/subs.py:ass_write`; `longform-to-short/scripts/burn_final.py` | `alt_scale=0.72`, `outline=2.4` | Pure ffmpeg pipelines | low | per cue | always on | `subs.ass_write(cues, "s.ass")`, then `-vf ass=s.ass` | `test_core.py` |
| Bilingual EN/ZH subtitles <sub>`bilingual-subtitles`</sub> | EN above ZH; **word** in gold | PIL | `photostory/subtitles.py:make_sub` | `f2 size=0.72x` | Bilingual stories | low | per cue | always on | photo-story; elsewhere `draw.bilingual_layer` | `test_lib_requests.py` |
| Pop words <sub>`pop-words`</sub> | Big stroked word with a -4 deg bounce | PIL | `compose.py:pop_img` + `ease_pop` | `size=per pop`, `hold=per pop` | Punctuate a key word | high | pop 0.25 s, hold >= 1 s | <= 1 per 15 s | talkinghead; in HF use `hf.stamp` with `angle=-4` | - |
| Title card <sub>`title-card`</sub> | Centred boxed title + gold sub line; back.out pop, lifts away | HF | `hf.py:title_card` | `hold=1.9`, `size=96` | Section openers | med | pop 0.4 s + hold 1.9 s | 1 per section | `hf.title_card("...", s, at, sub="...")` | `test_hf.py` |
| Hook title (talkinghead) <sub>`hook-title`</sub> | 2-line hook title (line 2 has keywords) + badge | PIL | `compose.py` (`HOOK_TITLE`, `HOOK_BADGE_TEXT`) | `hook_badge=STYLE` | Opening seconds of a short | high | first 2-4 s | 1 per video | talkinghead config | - |
| Step labels <sub>`step-labels`</sub> | Numbered '01 ...' labels swap in place over a reel | HF | `hf.py:step_labels` | `labels=[{s, e, n, t}]` | Tutorial steps, reels | low | >= 1.5 s per label | 1 set per reel | `hf.step_labels(labels, start, dur)` | `test_hf.py` |
| End card <sub>`end-card`</sub> | Serif kicker, big line, dim CTA; staggered fade-ups | HF | `hf.py:end_card` | `size=80` | Outro / CTA | low | 3-4 s | 1 per video | `hf.end_card(E, 3.2, "kicker", "main", "CTA")` | `test_hf.py` |
| Chapter card <sub>`chapter-card`</sub> | Full-frame '02 / 05 + title' card | PIL | `overlays.py:chapter_card`; `longform-to-short/scripts/make_assets.py`; photo-story `subtitles.make_chapter` | `cards.dur=1.6` | Chapter boundaries in long videos | med | 1.6 s | 1 per chapter | Render as a PNG and insert as a `-loop 1` still | `test_visual.py` |
| Running header <sub>`running-header`</sub> | Section names, per-section progress, titles | PIL | `photostory/subtitles.py:Header` | `SECTIONS=spec` | Photo stories with sections | low | whole video | always on | photo-story | - |
| 3b1b scene techniques <sub>`3b1b-techniques`</sub> | Draw-on lines, count-ups, type-in, clip wipes, axis grow, math built term by term (`draw-on`, `count-up`, `type-in`, `clip-wipe`, `axis-grow`, `stagger`, `svgOrigin`, `drift`, `math-terms`) | HF | `workflows/explainer/references/design-truth.md`, `assets/reference-scene.html` | `ease=power2.out`, `drift=<= 6 px` | Explainer scenes | med | per scene | each technique stars once per scene | Copy from the reference scene | - |
| Slides <sub>`slides`</sub> | Square / vertical slide presets as PNG or animated clip (`s-title`, `s-contrast`, `s-three`, `s-punch`, `s-bars`, `s-recap`) | HTML | `workflows/slides/templates/slides_vertical.template.html`, `scripts/render_slides.py`, `record_slides.py` | `--accent=persona` | B-roll for vertical videos | low | 3-6 s per slide | unlimited | Drop PNGs or clips into any edit | - |

## 5. Highlight / emphasis

| Effect | What | Engine | Where | Params | When to use | Energy | Hold / duration | Max uses | Reuse | Tested |
|---|---|---|---|---|---|---|---|---|---|---|
| Marker sweep <sub>`marker-sweep`</sub> | A soft highlighter band sweeps in behind the keyword of one line | PIL | `overlays.py:marker_line` (sweep 0-1) | `sweep=0.45`, `size=0.06` | Land the one keyword of a sentence quietly | low | 0.45 s sweep, hold >= 1.5 s | 1 per 20 s (S2) | `overlays.marker_line("先做【减法】", 64, sweep=p)` | `test_theme.py` |
| Highlighter rows <sub>`highlighter-rows`</sub> | A yellow multiply bar sweeps across a screenshot row | HF | `hf.py:screenshot_cards` (`hl=[[t, y0, y1, frac]]`) | `frac=0.6` | Point at one line in a screenshot | low | sweep 0.5 s, hold >= 1 s | 1-2 per card | Rows from `find_rows.py` | `test_hf.py` |
| Red box <sub>`red-box`</sub> | Accent rounded box pops (back.out) around a region | HF | `hf.py:screenshot_cards` (`box=[t, y0, y1]`) | `accent=theme` | Frame a block in a screenshot | med | pop 0.4 s, hold >= 1 s | 1 per card | Same as highlighter rows | `test_hf.py` |
| Stamp <sub>`stamp-hf`</sub> | Bordered word slams in from 2.2x | HF | `hf.py:stamp` | `angle=-12`, `size=96` | Verdict words ('works', 'tested') | high | slam 0.3 s, hold >= 1 s | 1-2 per video (A7) | `hf.stamp("...", s, d, at)` | `test_hf.py` |
| Stacking stamps <sub>`stacking-stamps`</sub> | White plate + accent stamp slam-ins; same end time = stack | PIL | `overlays.py:stamp`; `compose.py` (`STAMPS`) | `angle=8`, `size=56` | Per-frame verdicts | high | slam 0.25 s each | 1 stack per video | `overlays.stamp("...", 8)` | `test_visual.py` |
| Red-pen ellipse + dim <sub>`red-pen-ellipse`</sub> | Double ellipse drawn on, outside dimmed 50 % | PIL | `photostory/overlays.py` (`hl=`) | `hl_t=0.3` | Point at a region of a photo | med | draw 0.3 s, hold >= 1.5 s | 1-2 per video | photo-story; for covers `cover.redpen_ellipse` | `test_lib_requests.py` |
| Gold count-up <sub>`gold-count-up`</sub> | Big number counting up, with a caption | PIL | `photostory/overlays.py` (`count=`) | `count=(n, "EN", "ZH")` | Numbers worth remembering | med | count 1 s, hold >= 1 s | 1-2 per video | photo-story; in HF use the explainer count-up proxy pattern | - |
| Shimmer / develop / sketch reveal <sub>`reveal-fx`</sub> | Gold light sweep; develop from a warm wash; pencil-to-colour (`shimmer`, `develop`, `sketch`) | PIL | `photostory/overlays.py`, `shots.py:pencil` | `fx=("shimmer",)` | A hero photo's first appearance | med | 1-2 s | light effects <= 2 per video | photo-story spec | - |

## 6. Freeze / hold

| Effect | What | Engine | Where | Params | When to use | Energy | Hold / duration | Max uses | Reuse | Tested |
|---|---|---|---|---|---|---|---|---|---|---|
| Freeze-frame split <sub>`freeze-split`</sub> | Video split into clip + still + clip; resumes with data-media-start | HF | `hf.py:freeze_clips` | `hold=2.6` | Pause on a moment to explain it | med | hold 2-3 s | 1-2 per video | `hf.freeze_clips(src, freeze, start, cut_at, hold, media_dur, rate)` | `test_hf.py` |
| Freeze hold + flying zoomed card <sub>`freeze-hold-card`</sub> | Dims the freeze; a zoomed card flies out, holds, flies back | HF | `hf.py:freeze_hold` | `hold=2.6`, `fly_from=(380, -150)` | Enlarge a prompt / a line from a screen | high | fly 0.6 s, hold 2-3 s | 1 per video (A7) | `hf.freeze_hold(T, 2.6, (380, -150), "label", "assets/img/prompt.png")` | `test_hf.py` |
| Transient freeze <sub>`transient-freeze`</sub> | Holds the frame from 0.4 s before an accidental screen flash; live audio continues | ffmpeg | `longform-to-short/scripts/transient_scan.py` -> `freezes`, `build_timeline.py`, `render.py` | `white_thresh=0.55` | Screen recordings with flashes | n/a | length of the flash | as needed | transient_scan works on any screen recording | - |

## 7. Transitions

| Effect | What | Engine | Where | Params | When to use | Energy | Hold / duration | Max uses | Reuse | Tested |
|---|---|---|---|---|---|---|---|---|---|---|
| 11 scene transitions <sub>`hf-scene-transitions`</sub> | GSAP scene-to-scene transitions on wrapper divs (`blur`, `fade`, `push`, `vpush`, `iris`, `zoom`, `focus`, `blocks`, `chroma`, `flip`, `zoomout`) | HF | `hf.py:scene_transitions`, `hf.transition`, `hf.TRANSITIONS`; menu in `workflows/explainer/references/transitions.md` | `d=per type (0.45-1.1 s)`, `blocks=8` | Scene changes in HF projects; one calm family + iris for the core reveal + blocks for chapters | med | blur .8, fade .45, push .7, vpush .7, iris 1.1, zoom .8, focus .9, blocks 1.1, chroma .8, flip .9, zoomout 1.0 | hard cut is the default; styled ones only where place / day / mood changes (A5) | `hf.scene_transitions([...])`, or `xfade.hf_transitions` for any bridge name | `test_hf.py` |
| 12 photo transitions <sub>`photo-transitions`</sub> | Per-frame transitions inside the photo-story picture box (`fade`, `push`, `whip`, `flash`, `zoom`, `iris`, `leak`, `ink`, `blinds`, `tear`, `slideup`, `cut`) | PIL | `photostory/transitions.py:transition(C, P, N, p, kind)`; durations `TRD` | `trd=TRD[kind] (0.32-0.7 s)` | Photo stories | med | 0.32-0.7 s | vary; <= 2 styled per minute | `xfade.blend(name, P, N, p)` (no Ctx) or the photo-story function | - |
| Cross-engine transitions (bridge) <sub>`xfade-bridge`</sub> | One transition name in all three engines: HF GSAP, ffmpeg xfade (built-in or custom expr), PIL per-frame (`blur`, `fade`, `push`, `vpush`, `iris`, `zoom`, `focus`, `blocks`, `chroma`, `flip`, `zoomout`, `whip`, `flash`, `fadeblack`, `light-leak`, `ink`, `blinds`, `tear`, `slideup`, `cut`, `wipe`, `dissolve`, `pixelize`, `radial`) | HF + ffmpeg + PIL | `lib/vstudio/xfade.py` (`blend`, `ffmpeg_transition`, `ffmpeg_expr`, `hf_transitions`, `coverage`) | `name=fade`, `duration=xfade.default_duration(name)` | Any time the same look must exist in two engines (a HF explainer and its ffmpeg cut-down) | med | per name (0-1.1 s) | same as the source effect | `cut.xfade_assemble(pieces, transition=xfade.ffmpeg_transition("iris"))` | `test_effects.py` |
| Light-leak transition <sub>`light-leak`</sub> | Cross-dissolve under a warm film light leak | HF + ffmpeg + PIL | `xfade.blend("light-leak", ...)`, `xfade.ffmpeg_transition("light-leak")`, `xfade.hf_transitions([("light-leak", ...)])` | `strength=0.9`, `duration=0.7` | Travel / memory pieces, a change of day or place | med | 0.7 s | <= 2 per video (light effects cheapen fast) | `xfade.blend("light-leak", A, B, p)` per frame of the overlap | `test_effects.py` |
| Dissolve joins (xfade) <sub>`xfade-joins`</sub> | Any ffmpeg xfade between pieces, with acrossfade and mute pads | ffmpeg | `lib/vstudio/cut.py:xfade_assemble`; vlog `build_vlog.py` (`transition`, `xfade=.8`) | `xfade=0.3`, `transition=fade` | Joining pieces in any ffmpeg workflow | low | 0.15-0.8 s | unlimited for plain fades | `cut.xfade_assemble(pieces, xfade=0.3, transition="fadeblack")` | `test_core.py` |
| Hook montage <sub>`hook-montage`</sub> | Sped-up hooks with crossfades into the body | ffmpeg | `workflows/talkinghead/scripts/montage.py:Montage` | `hook_speed=1.3`, `body_speed=1.1` | Cold open of a short | high | 3-8 s | 1 per video | `Montage(...)` is importable; use `.graph` | - |
| Speed ramps <sub>`speed-ramps`</sub> | Per-segment setpts (+ atempo) | ffmpeg | `vlog/build_vlog.py:seg_speed`; `media.atempo_chain` | `speed=1.2` | Tightening or energy ramps | med | per segment | ramps as an effect: 1 star use | `setpts=PTS/s` + `media.atempo_chain(s)` | `test_core.py` |
| End fade (no fade-in) <sub>`end-fade`</sub> | fade=t=out + afade; never a black first frame | ffmpeg | `vlog/build_vlog.py` | `fade_out=1.5` | Last pass of any video | low | 1.5 s | 1 per video | Use in any final pass | - |

### Transition coverage across engines (`vstudio.xfade`)

exact = same look; near = same idea, small visual difference; approx = closest stand-in.

| Transition | Default s | HyperFrames | ffmpeg xfade | PIL `blend` | Gaps |
|---|---|---|---|---|---|
| `blur` | 0.8 | `blur` (exact) | `hblur` (approx) | exact | ffmpeg: xfade hblur smears horizontally only; no 2-D defocus |
| `fade` (crossfade, xfade) | 0.45 | `fade` (exact) | `fade` (exact) | exact | - |
| `push` (slideleft) | 0.7 | `push` (exact) | `slideleft` (near) | exact | ffmpeg: no 4 px motion blur |
| `vpush` | 0.7 | `vpush` (exact) | `slideup` (near) | exact | ffmpeg: outgoing is not dimmed to 40 % |
| `iris` (circleopen) | 1.1 | `iris` (exact) | `circleopen` (near) | exact | ffmpeg: centre is 50 %/50 % (HF 50 %/45 %); outgoing does not shrink to 0.94 |
| `zoom` (zoomin) | 0.8 | `zoom` (exact) | `zoomin` (approx) | near | ffmpeg: only the outgoing zooms; no blur, incoming static; pil-frame: incoming settles from 1.18x (photo-story) instead of 0.7x |
| `focus` | 0.9 | `focus` (exact) | `fade` (approx) | exact | ffmpeg: xfade cannot defocus; pre-blur the tail/head with gblur or render in HF |
| `blocks` (panels) | 1.1 | `blocks` (exact) | custom expr (near) | exact | ffmpeg: no 1 px panel edge line |
| `chroma` | 0.8 | `chroma` (exact) | `pixelize` (approx) | near | ffmpeg: no RGB split; for the real look pre-render with rgbashift; pil-frame: split is a channel roll, not a drop-shadow |
| `flip` | 0.9 | `flip` (exact) | `squeezeh` (approx) | near | ffmpeg: squeeze, no perspective or dimming; pil-frame: horizontal squeeze, no perspective foreshortening |
| `zoomout` | 1 | `zoomout` (exact) | custom expr (near) | exact | ffmpeg: no blur on the outgoing |
| `whip` (whip-pan, whippan) | 0.32 | bridge GSAP (near) | custom expr (near) | exact | hyperframes: CSS blur is 2-D, not directional; ffmpeg: 5-tap blur, slight ghosting at 1080p; slow (per-pixel expr) |
| `flash` (fadewhite, white-flash) | 0.5 | bridge GSAP (exact) | `fadewhite` (near) | exact | ffmpeg: pure white, not warm white |
| `fadeblack` (dip, dip-to-black) | 0.6 | bridge GSAP (exact) | `fadeblack` (exact) | exact | - |
| `light-leak` (leak, lightleak) | 0.7 | bridge GSAP (near) | custom expr (near) | exact | hyperframes: CSS radial gradients with screen blend; ffmpeg: leak added in YUV (luma + warm chroma shift) |
| `ink` | 0.6 | `blur` (approx) | custom expr (near) | exact | hyperframes: no organic mask; needs an SVG feTurbulence mask; ffmpeg: sine-field blotches instead of noise |
| `blinds` | 0.55 | `blocks` (approx) | custom expr (exact) | exact | hyperframes: blocks covers with colour instead of revealing B |
| `tear` | 0.55 | `push` (approx) | `wipeleft` (approx) | exact | hyperframes: no torn edge; ffmpeg: straight edge, no paper band or shadow |
| `slideup` (coverup) | 0.45 | bridge GSAP (exact) | `coverup` (near) | exact | ffmpeg: outgoing is not dimmed |
| `cut` (hard, none) | 0 | bridge GSAP (exact) | `fade` (near) | exact | ffmpeg: use xfade=0 in xfade_assemble for a true cut (concat) |
| `wipe` (wipeleft) | 0.5 | bridge GSAP (exact) | `wipeleft` (exact) | exact | - |
| `dissolve` | 0.6 | `fade` (approx) | `dissolve` (exact) | exact | hyperframes: no per-pixel noise |
| `pixelize` | 0.6 | `chroma` (approx) | `pixelize` (exact) | exact | hyperframes: stepped glitch instead of pixel blocks |
| `radial` (clock, clock-wipe) | 0.8 | `iris` (approx) | `radial` (exact) | exact | hyperframes: circle grows; no conic sweep |

## 8. Looks / grade

| Effect | What | Engine | Where | Params | When to use | Energy | Hold / duration | Max uses | Reuse | Tested |
|---|---|---|---|---|---|---|---|---|---|---|
| Vlog grade <sub>`vlog-grade`</sub> | eq + warm colorbalance + unsharp | ffmpeg | `vlog/build_vlog.py:grade_chain` | `sat=1.18`, `contrast=1.12`, `warm=on` | Travel / lifestyle footage | n/a | whole video | one grade per video | Paste the chain into any `-vf` | - |
| Talking-head grade <sub>`talkinghead-grade`</sub> | Denoise + eq + colorbalance + CAS sharpen | ffmpeg | talkinghead config `GRADE` | `eq brightness=-0.06` | Talking heads | n/a | whole video | one grade | Paste it | - |
| HDR to SDR <sub>`hdr-to-sdr`</sub> | zscale/tonemap for iPhone HLG | ffmpeg | `lib/vstudio/media.py:hdr_to_sdr_args` | `force=False` | iPhone HDR sources | n/a | whole clip | always for HDR sources | `media.hdr_to_sdr_args(src)` | `test_core.py` |
| Film look <sub>`film-look`</sub> | Grain always; strong = warm desat, flicker, vignette, scratches, dust | PIL | `photostory/looks.py:film_look(C, box, gt, strong)` | `strong=False` | Archive / memory sections | low | section | strong look 1 section | Call it on any `(BOX_H, BOX_W, 3)` float32 frame with a Ctx | - |
| Texture generators <sub>`texture-generators`</sub> | grain, light leak, ink field, torn edge, dark radial bg, paper (`grain`, `leak`, `ink`, `jag`, `bg`, `paper`) | PIL | `photostory/looks.py:make_grain/make_leak/make_ink/make_jag/make_bg/paper_bg` | `seed=fixed` | Building blocks for other effects | n/a | - | - | Need a Ctx | - |
| Portrait retouch <sub>`portrait-retouch`</sub> | Face slim, eyes, de-shine, skin/makeup, body slim; video skin smoothing / beauty (tracked) | PIL | `lib/vstudio/retouch.py:retouch` | `slim=0.05`, `smooth=0.6`, `makeup=0.5`, `strength=0.5` | Covers and talking heads (creator decides); 磨皮 / 美颜 in the output editor | n/a | whole clip | always subtle | `retouch.retouch(img)`; video: `retouch.VideoRetoucher(retouch.video_knobs(0.5))(frame, t)` | `test_retouch.py` |

## 9. Audio / SFX

| Effect | What | Engine | Where | Params | When to use | Energy | Hold / duration | Max uses | Reuse | Tested |
|---|---|---|---|---|---|---|---|---|---|---|
| SFX bank <sub>`sfx-bank`</sub> | Synthesised pop, whoosh, stamp/thud, ding, ... | audio | `lib/vstudio/audio.py:sfx_bank`, `SFX_GAINS`, `write_sfx` | `gains=pop .32, whoosh .4, thud .45, ding .35` | Any on-screen action that needs a sound (A11) | n/a | 0.1-1.6 s | repeats must alternate and step down (A12) | `audio.write_sfx("assets/sfx")` | `test_beats.py` |
| SFX placement <sub>`sfx-placement`</sub> | Mix events into a voice track | audio | `audio.py:place_sfx`; talkinghead `compose.py:mix_audio` | `events=[(t, name)]` | After picture lock (A12) | n/a | - | <= 2 per 2 s | `audio.place_sfx(x, [(3.2, "pop")], sr)` | `test_beats.py` |
| Card stinger <sub>`card-stinger`</sub> | 1.6 s noise whoosh + 110 Hz thump at -19 dBFS | audio | `longform-to-short/scripts/make_audio_assets.py` -> `card_sting.wav` | `level=-19 dBFS` | Under a chapter card | med | 1.6 s | 1 per chapter | Copy the WAV under any chapter card | - |
| Music bed + ducking <sub>`music-bed`</sub> | Loops music, ducks it under the voice, optional carve EQ, fades | audio | `audio.py:mix_bed`; `vlog/scripts/add_music.py`; explainer `make_bgm_bed.py` + `carve.mjs` | `duck_db=-10`, `music_lufs=-30` | Every narrated video | n/a | whole video | 1 bed (+ a no-music version, A13) | `audio.mix_bed(voice, music, out)` | `test_core.py` |
| Loudness <sub>`loudness`</sub> | Two-pass loudnorm to -14 LUFS | audio | `audio.py:loudnorm_2pass`, `normalize_stem` | `lufs=-14`, `tp=-1.5` | Last step of every workflow | n/a | - | always | `audio.loudnorm_2pass(src, dst)` | `test_core.py` |
| Studio sound (voice enhance) <sub>`studio-sound`</sub> | Denoise, dereverb, voice EQ, de-ess, gentle compression (local) | audio | `lib/vstudio/studiosound.py` | `strength=standard` | Phone / laptop / room recordings, 降噪, 人声增强 | n/a | whole video | 1 | `studiosound.enhance(src, dst, strength="standard")` | `test_studiosound.py` |
| Voice anonymize <sub>`voice-anonymize`</sub> | Pitch shift, duration preserved | audio + ffmpeg | `audio.py:pitch_shift_filter`; longform `pitches.windows` | `semitones=-3` | Privacy for a voice | n/a | window | as needed | `-af` with `audio.pitch_shift_filter(-3)` on the window | `test_core.py` |

## 10. Progress / chapter bars

| Effect | What | Engine | Where | Params | When to use | Energy | Hold / duration | Max uses | Reuse | Tested |
|---|---|---|---|---|---|---|---|---|---|---|
| HF chapter progress bar <sub>`hf-progress`</sub> | Bar + ticks + chapter labels on a scrim; the active label lights up | HF | `lib/vstudio/overlays.py:hf_progress` | `geo=horizontal` | Long videos with chapters | low | whole video | always on | `p = overlays.hf_progress(chs, 0, total)`; paste css/html/js | `test_visual.py` |
| Line / refined / classic bar (per frame) <sub>`progress-bar-pil`</sub> | Hairline theme bar (default), or segmented gradient bar with knob and pill, or notes-board bar (`line`, `refined`, `classic`) | PIL | `overlays.py:progress_bar(style=None\|"line"\|"refined"\|"classic")` | `style=line` | Per-frame compositors | low | whole video | always on | Paste `progress_bar(...)` each frame | `test_visual.py` |
| Static bar + ffmpeg fill <sub>`progress-ffmpeg`</sub> | Dim bar PNG + labels + drawbox fill / playhead expression | ffmpeg | `overlays.py:progress_static`, `progress_fill`; talkinghead `build_filter.py` | `y=1000` | Pure-ffmpeg landscape passes | low | whole video | always on | Use it for a pure-ffmpeg pass | `test_visual.py` |

## 11. Covers

| Effect | What | Engine | Where | Params | When to use | Energy | Hold / duration | Max uses | Reuse | Tested |
|---|---|---|---|---|---|---|---|---|---|---|
| Split cover <sub>`split-cover`</sub> | Retouched photo + quote + title + thumbnail + chips + stamp, several sizes | PIL | `lib/vstudio/cover.py:split_cover` | `title_highlight` | Talking-head covers | n/a | still | 1 per video | `split_cover(cfg)` | `test_visual.py` |
| Notes cover <sub>`notes-cover`</sub> | Frame + sticky-note panels + kicker | PIL | `cover.py:notes_cover`, `sticky_note` | `mute_bottom=150` | Talkinghead horizontal cover | n/a | still | 1 | talkinghead H cover | `test_visual.py` |
| Framed cover <sub>`framed-cover`</sub> | Tilted framed screenshot + eyebrow/big/sub + chips | PIL | `cover.py:framed_cover`, `framed` | `tilt=-3` | Longform / course covers | n/a | still | 1 | longform cover | `test_visual.py` |
| Collage cover (pattern A) <sub>`collage-cover`</sub> | 4-frame diagonal collage, X-slash, play diamond | HTML | `workflows/cover/templates/cover_collage.template.html` | `--cell-w/h=boxes` | Short-video covers | n/a | still | 1 | `python -m vstudio.render` | - |
| Face on quadrants (pattern B) <sub>`face-quadrants-cover`</sub> | Matted face over 4 slide quadrants | HTML | `cover/templates/cover_face_quadrants.template.html`, `scripts/matte.py` | `--engine=mediapipe` | Talk with slides | n/a | still | 1 | Same | - |
| Torn-paper scrapbook <sub>`torn-paper-cover`</sub> | Torn-edge photo pieces with a taped title | HTML | `vlog/scripts/make_cover.py:build_html` | `roughness=13` | Vlog covers | n/a | still | 1 | Use it with any stills | - |
| Photo-story cover <sub>`photo-story-cover`</sub> | Title zone + hero split polaroid + taped polaroid row with red circles | PIL | `photostory/cover.py` | `COVER=spec` | Photo stories | n/a | still | 1 | `polaroid()`, `circled()` | - |
| Frame scoring <sub>`frame-scoring`</sub> | Picks smiling, eyes-open, centred frames | PIL | `cover.py:score_frames`, `contact_sheet` | `top_n=6`, `min_gap=2.0` | Choosing a cover frame | n/a | - | - | Run on any talking video | `test_visual.py` |

**Count**: 92 registry entries in 11 sections (197 counting named variants). By engine: PIL 44, ffmpeg 20, HF 26, HTML 5, audio 7. Parameter feel, pitfalls and entry points: `python -m vstudio.effects --show <id>`.

<!-- END GENERATED: effects registry -->

---

## Recipes

1. **"Zoom in on what I'm pointing at"** (talking head + screen)
   - HF: `hf.punch_in([[s, e]])` on `#face-zoom`. To also show the thing, add `hf.split_screen([[s, e]], inset, x)`
     + `hf.screenshot_cards([...])` with `scroll` to the row.
   - Screen recording in ffmpeg: a code-zoom cut-in (`zoom_targets.py` finds the centre; `crop` + `scale` on the window).
   - Per-frame vertical: talkinghead `EMPH` + `emph_zoom`.

2. **"Show a screenshot and highlight a line"**
   - Run `find_rows.py shot.png` to get the row y's.
   - Call `hf.screenshot_cards([dict(id="c1", img=…, w, h, s, e, scroll=[[s,0],[t,y-120]], hl=[[t+0.3, y0, y1, 0.6]], box=[t2, y0, y1])])`.
   - Add `hf.split_screen` over the same window so the face moves aside.

3. **"Freeze and enlarge a prompt"**
   - Extract the frame at the pause: `ffmpeg -ss T -frames:v 1`.
   - Lay out the clips with `hf.freeze_clips(src, "assets/img/freeze.jpg", start, T, 2.6, media_dur, rate)`.
   - Add the card with `hf.freeze_hold(at, 2.6, fly_from=(dx, dy), label="我给 agent 的 prompt", image="assets/img/prompt.png")`.
   - Shift every later time by the hold. promo-recut config `hold:` does all of this.

4. **"Split screen: me + screen recording"**
   - HF: `hf.split_screen(windows, "inset(40px 520px 120px 500px round 28px)", x=-440)`, plus a `<video class="clip">` in
     the freed right half. Give it its own track, start it at opacity 0, and fade it with the windows.
   - 9:16: use GEO `vertical` (face band on top).
   - Calls: call-clips `render_vertical` / `render_landscape` layouts.

5. **"Insert a highlights reel"**
   - In a talk: `hf.zoom_through(at=M, until=O)` + `hf.framed_screen("assets/video/montage.mp4", M, dur + 0.5, exit_at=O, rate=1.1)`
     + `hf.step_labels(...)` + `hf.badge("精选", …)` + `hf.title_card("成片精选", …)`. Cut the montage with
     `cut.xfade_assemble`.
   - At the start (cold open): talkinghead `Montage(hooks=…)`, or call-clips `hooks` with the 高光预告 badge.

6. **"Chapter progress bar"**
   - HF: `overlays.hf_progress(chapters, start, total, geo)`.
   - Per-frame: `overlays.progress_bar(chs, t, total, style="refined")`.
   - Pure ffmpeg: `overlays.progress_static` + `progress_fill`.
   - Add a chapter card at each boundary: `overlays.chapter_card(i, n, title)` + `card_sting.wav`. In HF, use the
     `blocks` transition.

7. **"Stamp a punchline"**
   - HF: `hf.punch_at("#ow", t)` then `hf.stamp("好用", start, dur, at=t + 0.9)`. Add the SFX with
     `audio.write_sfx()` → `stamp.wav` as an `<audio>` at the same time.
   - Per-frame: `overlays.stamp(text, angle)` with an `ease_pop` scale-in, and `place_sfx([(t, "thud")])`.

8. **"Explainer-style scene change"**
   - `hf.scene_transitions([hf.transition("blur", "w-a", "w-b", T, 0.8), …])`. Use one calm family (blur/push), with
     `iris` for the core reveal and `blocks` for a new chapter.
   - Stretch each outgoing scene's `data-duration` by `d` (`make_index.py --patch-scenes`).
   - Photo / image sequences: `photostory.transitions.transition(C, P, N, p, "ink")`, or Ctx-free
     `xfade.blend("ink", P, N, p)`.
   - The same transition in an ffmpeg cut-down: `cut.xfade_assemble(pieces, transition=xfade.ffmpeg_transition("iris"))`.

9. **"Hide a guest's face"**
   - Run `track_face.py` → `apply_sticker.py` → `verify_coverage.py --min-coverage 1.0`.
   - For a camera-off tile, use `cat_avatar.html` + `verify_avatar.py`.

10. **"Picture-in-picture: screen recording full-screen, me as a tile"**
   - HF: `hf.pip_windows(windows, clip, scale, x, y, tile, frame)`; windows `[{id, s, e, video, media_start, tag}]` or
     `images: [...]` (cross-fade). Put `html` (the framed screen layers) BEFORE the face wrapper and `overlay` (tag
     pills + the tile ring) AFTER it. The face wrapper (`#face`, transform-origin 0 0) is clipped to `clip` and scaled +
     moved onto the tile; windows <= 0.8 s apart form one run (the face stays a tile, screens cross-fade).
   - Only the `<video>` is timed; its wrapper is a plain container whose opacity is tweened (data-start on both =
     HyperFrames `video_nested_in_timed_element`). The same source may be used by several windows.
   - Geometry: promo-recut `pip_layout(GEO)` (horizontal table; vertical computed: tile above the caption band, clear
     of the platform's button column). Hide browser chrome first: promo-recut `screen_crop.py` (`crop: auto`).

11. **"Animated scene in a card slot (chart, ranking, flow...)"**
   - HF: `hf.scene_card(id, {kind, title, items, foot}, s, e, card_w, card_h)` + `hf.scene_css(hf.scene_palette())`
     once; kinds `hf.SCENE_KINDS`: tiles, flow, bars, stat, toast, ranking, columns, checklist, swatch. Colours come from
     the theme / persona brand. Pass the html as a card's `inner` in `hf.screenshot_cards`.
   - A playing clip in the slot: `hf.card_video(id, src, s, dur, media_start, label, card_w, card_h)`; then the card
     container must NOT be timed (lint `video_nested_in_timed_element`).
   - Content inside a card needs an explicit width/height: the card's scroller is transformed and has no height,
     so `inset: 0` collapses to nothing.

12. **"Hook montage in front, flash into the talk"**
   - Cut: `cut.xfade_assemble(pieces, xfade=0, seek=True)` with every piece at the hook speed and 20/30 ms edge fades
     (promo-recut `tight_cut.build_hooks`, word-safe edges via `cleanup.snap_range`).
   - HF: the hooks clip on the body's track from 0, everything else shifted by its length; two-line captions are
     subtitles cues with `c: "hook"`; alternate framing with `tl.set("#hook-zoom", {scale})` per hook;
     `hf.flash(H)` over the cut into the body.
