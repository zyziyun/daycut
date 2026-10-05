# EFFECTS — every visual / audio effect in video-studio, and how to reuse it

Paths are relative to the repo root (`$VSTUDIO`). The **Engine** column says how the effect is drawn:

- **PIL**: a per-frame Python pass on numpy frames (PIL, OpenCV or numpy), piped to ffmpeg.
- **ffmpeg**: a filter graph only.
- **HF**: HyperFrames HTML + GSAP, rendered by `npx hyperframes render`.
- **audio**: numpy audio or an ffmpeg audio filter.

An effect can only be reused inside the same engine family, so pick the engine first. A HyperFrames project
uses `vstudio.hf`. A per-frame Python compositor uses `vstudio.overlays` / `vstudio.draw` images or photo-story's
frame functions. An ffmpeg graph uses the filter strings.

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

## 1. Camera / zoom

| Effect | What | Engine | Where | Params | Reuse from another workflow |
|---|---|---|---|---|---|
| Punch-in (eased) | Talking head scales up for a window, then back | HF | `lib/vstudio/hf.py:punch_in` | `windows [[s,e]]`, `target="#face-zoom"`, `scale=1.14`, `in_dur=.45`, `out_dur=.5` | `hf.punch_in([[12.0, 15.5]])` on an inner wrapper around your video. Keep the outer wrapper free for split / zoom-through. |
| Punch-and-stay | One punch that holds (e.g. on the punchline) | HF | `hf.py:punch_at` | `target`, `at`, `scale=1.16`, `dur=.5`, `origin="50% 38%"` | `hf.punch_at("#ow", 41.2)`, then `hf.stamp(..., at=42.1)` |
| Wrapper zoom entrance | Settles from 1.15× and transparent | HF | `hf.py:enter_zoom` | `target`, `at`, `from_scale=1.15`, `dur=.6` | Use it to bring in any section wrapper (promo's outro) |
| Per-sentence punch-in (hard cut) | Face-centred zoom per sentence: `EMPH` sids get `emph_zoom`, odd sids get `alt_zoom` | PIL | `workflows/talkinghead/scripts/vertical/compose.py:zoom` | `STYLE.zoom`, `emph_zoom=1.32`, `alt_zoom=1.16`; config `EMPH`, `FACE` (face_track.npy) | compose.py is not importable (it reads argv at module level). Copy `zoom()`: it is `cv2.warpAffine` about the tracked face. In HF use `hf.punch_in`. |
| Ken Burns (8 motions) | `in`, `out`, `panL`, `panR`, `up`, `down`, `still`, `flip` (a 3D turn) on one photo | PIL | `workflows/photo-story/scripts/photostory/shots.py:ImageShot` | shot motion (3rd tuple item); opts `c=(cx,cy)`, `z`, `fx=("sketch",)` | `ImageShot(C, sh, name).frame(lt)` needs a `Ctx` (`ctx.Ctx(ctx.load_spec(spec))`) and a shot dict (`src, start, end, tail, motion`). In HF, use the hyperframes-keyframes skill. |
| Code-zoom cut-in | Tighter crop on the code block, centred on the code-colour centroid, with a seamless join | ffmpeg | `workflows/longform-to-short/scripts/zoom_targets.py`, `build_timeline.py:zoom_crop` | `zoom.windows`, `zoom.code_rgb [247,246,243]`, `zoom.tol`, `zoom.min_px`, `zoom.centers`, `zoom.box [736,336]` | For any screen recording, `crop=w:h:x:y,scale=W:H` on the window. zoom_targets finds the centre of any flat-coloured panel (set `code_rgb`). |
| Zoom-through into a framed screen | The shot scales 1.35× and blurs out while the framed screen lands 1.25→`scale_in`, then drifts | HF | `hf.py:zoom_through` (+ `framed_screen`) | `at`, `until`, `scale_in=.84`, `y=-44`, `drift=.85`, `source="#face"`, `screen="#screen"` | Use it to go from a talk into a highlights reel or demo. Keep the source video playing about 0.5 s past `at`. |
| Stabilize | `deshake` + crop | ffmpeg | `workflows/vlog/scripts/build_vlog.py:stab_prefix` | `stabilize`, `stab_rx/ry=32`, `stab_zoom=.93` | Prepend `deshake=rx:ry:edge=clamp,crop=iw*k:ih*k` to any chain |
| Loupe | A magnifier travels a path over the photo | PIL | `photostory/overlays.py:overlays` (`loupe=`) | `loupe=[(x,y),...]`, `loupe_mag=2.3` | photo-story shot opt. Elsewhere, copy the block (needs `C.b`). |

## 2. Layout / split

| Effect | What | Engine | Where | Params | Reuse |
|---|---|---|---|---|---|
| Split screen | Full-frame face is clipped to an `inset()` and slid aside for each window; windows < 0.2 s apart are bridged | HF | `hf.py:split_screen`; geometry in `build_promo.py:GEO` (`split_inset`, `split_x/y`) | `windows`, `inset`, `x`, `y`, `target="#face"`, `dur=.7`, `lead=.15`, `tail=.3`, `bridge=.2` | Use it on any HF project with a talking-head wrapper. Fill the freed side with `screenshot_cards` or a screen-recording `<video>`. |
| Vertical face band + card | 9:16 promo: the face band on top, the card below | HF | `build_promo.py:GEO["vertical"]` | `split_inset "inset(200px 40px 1000px 40px round 28px)"`, `face_pos` | `--orientation vertical`, or pass the GEO values to `hf.split_screen` / `screenshot_cards` |
| Call layouts | 2 tiles stacked (vertical), trio (2 masked guests + host), landscape pair, landscape trio (6 s-smoothed reframe) | PIL | `workflows/call-clips/scripts/render_vertical.py`, `render_trio.py`, `render_landscape.py`, `render_landscape_trio.py` | `TILE_H=608`, `TOP_Y=330`; trio `G_H=500`, `HOST_H=540`; landscape `TILE 960×675`; `REFRAME_S=6` | `build_clips.py --renderer <file>`. For other gallery recordings, pass `--guest-region` / `--host-region` as `x,y,w,h`. |
| Fit: crop / pad / blur-pad / stretch | Fit any aspect into the canvas; `blur` = blurred cover background behind a fitted foreground | ffmpeg | `vlog/scripts/build_vlog.py:fit_chain` | `fit` = `crop`, `pad`, `blur` (gblur σ40, −0.08 brightness) or `stretch` | Copy the `fit_chain` string into any ffmpeg graph |
| Browser-chrome crop | Detects doc / browser headers per span and crops them plus the bookmark bar, then fits and pads | ffmpeg | `longform-to-short/scripts/geometry.py` → `crop_spans.json`; `render.py` | `geometry.*` (`browser_header_px=115`, `doc_header_px=45`, `bottom_trim=14`), `render.fit`, `render.pad_color` | Run geometry.py on any screen-share recording and use the crop spans |
| Photo layouts | `collage`, `film`, `split` (before/after wipe), `grid`, `rows`, `tilt`, `deck`, `quote`, `route`, `medal` | PIL | `photostory/shots.py` (`CollageShot` … `MedalShot`; factory `build(C, sh, k)`, `KINDS`) | `src="collage:a,b,c"`, `"split:a|b"` + `labels`, `"tilt:a"` + `yaw`, `"quote:a"` + `q=(en,zh,who)`, `"route:A>B"` + spec `ROUTE`, `"medal:a"` + `ring` | Through a photo-story spec. In code, `shots.build(C, sh, k).frame(lt)` returns a `(BOX_H, BOX_W, 3)` float32 frame. |
| Video in a photo story | Pre-cut, graded clip read frame by frame | PIL + ffmpeg | `photostory/shots.py:VideoShot`, `prep_video` | `src="v1234"`; opts `off`, `speed`, `c`, `z`, `grade`; spec `VCROP`, `VEQ`, `VEQ_FILTER` | photo-story spec |

## 3. Cards & overlays

| Effect | What | Engine | Where | Params | Reuse |
|---|---|---|---|---|---|
| 3D screenshot card | A card slides in with rotationY −28°→−6°, drifts, then leaves | HF | `hf.py:screenshot_cards` | `cards=[{id,img,w,h,s,e,scroll,hl,box}]`, `card_w=760`, `card_h=740`, `left`, `top`, `accent` | `hf.screenshot_cards([dict(id="c1", img="assets/img/x.png", w=1200, h=2400, s=3, e=9, scroll=[[3,0]])])` |
| Card scroll keyframes | The image scrolls to bring row y to the top at time t | HF | same, `scroll=[[t, y_img_px], ...]` | eased 0.6–1.2 s | Find rows with `workflows/promo-recut/scripts/find_rows.py` |
| Chips row | Pills pop in one by one; a star chip is gold; all fade at `end` | HF | `hf.py:chips` | `items [[t,text,star]]`, `end`, `left/top/width`, `ink`, `gold` | `hf.chips([[3,"Writing",0],[4,"Video ★",1]], end=9)` |
| Chip / badge / tag / stamp images | Themed RGBA images | PIL | `lib/vstudio/overlays.py:chip(style=outline\|filled\|star\|tag\|ghost)`, `badge`, `tag`, `stamp` | `theme`, `scale`, `size`, `color`, `angle` | They return PIL RGBA, so any PIL compositor can paste them with `vstudio.draw.alpha_paste`. ffmpeg can overlay them as `-loop 1` PNGs. |
| Badge (精选 / 高光预告) | Solid label that slides in | HF / PIL | `hf.py:badge`; `overlays.badge` | `text`, `start`, `duration`, `at`, `left/top`, `accent` | HF: `hf.badge("精选", s, d, at)`. PIL: `overlays.badge("精彩预告")`. |
| Outlined tag | Fading pill (e.g. "完整版 · 节选 · 1.1×") | HF | `hf.py:tag` | `text`, `start`, `duration`, `at`, `pos_css` | `hf.tag(...)` |
| Framed screen | Rounded, shadowed screen playing a video, on a grid backdrop; shrinks away at exit | HF | `hf.py:framed_screen`, `grid_backdrop_css` | `src`, `start`, `duration`, `exit_at`, `rate`, `left/top/width/height`, `grid` | Use it for any "video inside a monitor" beat. Enter with `zoom_through`. |
| Notes panel 记笔记 | Card with a header, bullets and a rotated tag. Themes: notes-red, notes-yellow, teal, navy | PIL | `overlays.py:notes_panel`; per-row reveal version in `talkinghead/.../compose.py` (`PANELS`) | `title`, `bullets`, `theme`, `width=620`, `scale`, `tag`, `keywords` | PIL image. Burn it with ffmpeg `overlay=...:enable='between(t,a,b)'` (`longform-to-short/scripts/burn_final.py`). For HF, save it as a PNG and use an `<img class="clip">` that starts at opacity 0. |
| Callout bubble | Speech bubble that slides up 24 px | PIL | `overlays.py:callout`; `compose.py` (`CALLOUTS`) | `text`, `theme`, `max_w=560`, `scale`, `keywords` | Same as the notes panel |
| Node card | "接下来 / NEXT" seam card | PIL | `overlays.py:node_card`; `call-clips/.../render_vertical.py:render_node_card` | `title`, `eyebrow`, `theme`, `min_w/max_w` | Paste it at a cut and fade it over 0.35 s |
| Quote card | Balanced quote lines with the speaker in teal | PIL | `call-clips/scripts/render_trio.py:render_quote` | `who`, `text`, `width=980` | Copy the function |
| Circle-face list scene | Blurred background, ringed circle crop of the face, title, popping tokens (1 or 2 columns) | PIL | `compose.py` (`blurbg`, `circle_inset`, `token_img`) | config `CIRCLES=[(t0,t1,title,[(t,token)],grid)]`, `R=290` | talkinghead only (not importable). Copy the 3 helpers. |
| Shrink-to-card scene | The frame shrinks to a 0.55× rounded card over a blurred copy, with a title and lines | PIL | `compose.py:card` | config `CARDS=[(t0,t1,title,[(t,line)])]`, `s=.55`, `r=36`, `y0=600` | talkinghead. Copy `card()` + `blurbg()`. |
| Privacy sticker | Face-tracked sticker covering a participant, with a coverage proof | PIL | `call-clips/scripts/track_face.py` → `apply_sticker.py`; `verify_coverage.py`; art via `render_sticker.py` | `--region`, `--scale 2.40`, `--y-offset -0.031`, `--bob`, `--smooth .25` | Works on any video. Run `track_face.py VIDEO --region ...`, then `apply_sticker.py VIDEO --track --sticker cat.png`. |
| Camera-off avatar | Full-tile cat avatar | PIL / HTML | `call-clips/assets/cat_avatar.html`, `verify_avatar.py` | `--tile` | Render with `render_sticker.py --size 960x540` |
| Photo overlays | `develop`, `shimmer`, `dust`, `prick` (pounce holes), `hl` (red-pen ellipse + dim), `tri` (composition triangle + tag), `loupe`, `tl` (timeline sweep), `count` (gold count-up), `label` (pill) | PIL | `photostory/overlays.py:overlays(C, sh, f, lt)`; `label` in `render.py` + `subtitles.make_label` | shot opts: `fx=(...)`, `hl=(cx,cy,rx,ry)`, `hl_t`, `tri`, `tri_label`, `loupe`, `loupe_mag`, `tl`, `count=(n,en,zh)`, `label`, `prick_n` | Use them in a photo-story spec. Every coordinate is a 0–1 fraction of the box. |
| Polaroid / taped card | Taped polaroid with a shadow and caption | PIL | `lib/vstudio/cover.py:polaroid`; `photostory/shots.py:make_card` | `size`, `rot`, `cap`, `seed` | `cover.polaroid(img, 600, rot=-4, cap="…")` |

## 4. Text & captions

| Effect | What | Engine | Where | Params | Reuse |
|---|---|---|---|---|---|
| Keyword subtitles (HF) | Cue pops up 14 px and fades; 【term】 is shown in the highlight colour | HF | `hf.py:subtitles` + `overlays.cue_html` + `overlays.hf_cue_css` | `cues [{s,e,t}]`, `container="#subs"`; cue CSS `geo` | `t = overlays.cue_html("用【关键词】")`, then `hf.subtitles(cues)`, and put `overlays.hf_cue_css("horizontal")` in the style |
| Burned subtitles (PIL) | Bold line with a stroke, `【】` / `KEYWORDS` in yellow, balanced CJK wrap | PIL | `lib/vstudio/draw.py:text_layer`; talkinghead `compose.py` (`split_sub`, `chunk_times`); call-clips `render_sub` | `stroke=6`, `max_w`, `keywords`, `line_gap`; talkinghead `sub_size=54`, `sub_y=1525` | `draw.text_layer("…【词】…", draw.load_font("cjk-bold", 54))` returns RGBA |
| ASS subtitles | libass burn-in with highlight and bilingual alt line, plus an errata style | ffmpeg | `lib/vstudio/subs.py:ass_write`; `longform-to-short/scripts/burn_final.py` | `size`, `highlight`, `alt_scale=.72`, `outline=2.4`, `margin_v` | `subs.ass_write(cues, "s.ass")`, then `-vf ass=s.ass:fontsdir=…` |
| Bilingual EN/中文 subtitles | EN above 中文; `**word**` in gold | PIL | `photostory/subtitles.py:make_sub` | `C`, `en`, `zh` | photo-story. Elsewhere use `draw.text_layer` twice. |
| Pop words | Big stroked word with a -4° bounce (Y = highlight colour, O = orange) | PIL | `compose.py:pop_img` + `ease_pop` | config `POPS=[(t,text,'Y'\|'O',x,y,size,hold)]` | talkinghead. In HF use `hf.stamp` with `angle=-4` and no border via CSS override, or a `title_card`. |
| Title card | Centred boxed title + gold sub line; back.out pop, lifts away | HF | `hf.py:title_card` | `title`, `start`, `at`, `sub`, `top=400`, `size=96`, `hold=1.9` | `hf.title_card("成片精选", s, at, sub="节选")` |
| Hook title (talkinghead) | 2-line hook title (line 2 has keywords) + badge | PIL | `compose.py` (`HOOK_TITLE`, `HOOK_BADGE_TEXT`) | `STYLE.hook_badge` | talkinghead config |
| Step labels | Numbered `01 …` labels swap in place over a reel | HF | `hf.py:step_labels` | `labels [{s,e,n,t}]`, `start`, `duration`, `left/top` | Use it on any reel or tutorial steps. `build_promo.py` shows how labels come from montage clips. |
| End card | Serif kicker, big line, dim CTA; staggered fade-ups | HF | `hf.py:end_card` | `start`, `duration`, `kicker`, `main`, `sub`, `size=80` | `hf.end_card(E, 3.2, "kicker", "main", "评论区告诉我 ↓")` |
| Chapter card | Full-frame "02 / 05 + title" card | PIL | `overlays.py:chapter_card`; `longform-to-short/scripts/make_assets.py`; photo-story `subtitles.make_chapter` | `index`, `total`, `title` (`"Main：sub"` → kicker + title), `size`, `theme`, `ground` | Render it as a PNG and insert it as a `-loop 1` still with the stinger (longform `cards.dur=1.6`) |
| Running header | Section names, per-section progress, titles | PIL | `photostory/subtitles.py:Header` | spec `TITLE_ZH/EN`, `SECTIONS` | photo-story |
| 3b1b scene techniques | Line draw-on (stroke-dashoffset), count-up (proxy `onUpdate`), per-char `<tspan>` type-in, clip-path wipe, `attr:` axis grow, stagger, `svgOrigin` rotation, ≤6 px ambient drift, colour-coded STIX math built term by term | HF | `workflows/explainer/references/design-truth.md`, `assets/reference-scene.html`, `example/compositions/f01…f18.html` | eases: `power2.out` entrances, `back.out(1.6)` pops, `sine.inOut` drift | Copy from the reference scene. Each scene is a sub-composition with its own paused timeline. |
| Slides | Square / vertical slide presets (`s-title`, `s-contrast`, `s-three`, `s-punch`, `s-bars`, `s-recap`, …) as PNG or animated clip | HTML → PNG / Playwright | `workflows/slides/templates/slides_vertical.template.html`, `scripts/render_slides.py`, `record_slides.py` | `--size`, `--accent`, `KEY:SECONDS` | Drop the PNGs or clips into any edit as B-roll |

## 5. Highlight / emphasis

| Effect | What | Engine | Where | Params | Reuse |
|---|---|---|---|---|---|
| Highlighter rows | A yellow multiply bar sweeps across a screenshot row | HF | `hf.py:screenshot_cards` (`hl=[[t,y0,y1,frac]]`) | y in image px, `frac` = width fraction | Rows from `find_rows.py` |
| Red box | Accent rounded box pops (back.out) around a region | HF | `hf.py:screenshot_cards` (`box=[t,y0,y1]`) | `accent` | Same |
| Stamp | Bordered word slams in from 2.2× | HF | `hf.py:stamp` | `text`, `start`, `duration`, `at`, `left/top`, `size=96`, `angle=-12` | `hf.stamp("好用", s, d, at)` |
| Stacking stamps | White plate + accent stamp slam-ins; same end time = stack | PIL | `overlays.py:stamp`; `compose.py` (`STAMPS`) | `angle=8`, `size=56`; config `STAMPS=[(t0,t1,text,x,y,ang)]` | `overlays.stamp("亲测", 8)` returns RGBA. Animate the scale with `ease_pop`. |
| Red-pen ellipse + dim | Double ellipse drawn on, outside dimmed 50% | PIL | `photostory/overlays.py` (`hl=`) | `hl=(cx,cy,rx,ry)`, `hl_t=.3` | photo-story. For covers use `photostory/cover.py:circled`. |
| Gold count-up | Big number counting up, with a caption | PIL | `photostory/overlays.py` (`count=`) | `count=(n,"EN","中")` | photo-story. For HF use the explainer count-up proxy pattern. |
| Shimmer / develop / sketch reveal | Gold light sweep; develop from a warm wash; pencil-to-colour | PIL | `photostory/overlays.py`, `shots.py:pencil` | `fx=("shimmer",)`, `("develop",)`, `("sketch",)` | photo-story spec |

## 6. Freeze / hold

| Effect | What | Engine | Where | Params | Reuse |
|---|---|---|---|---|---|
| Freeze-frame split | Video split into clip + still + clip; resumes with `data-media-start` | HF | `hf.py:freeze_clips` | `src`, `freeze_src`, `start`, `cut_at`, `hold`, `media_dur`, `rate` | Extract the still with `ffmpeg -ss cut_at -i src -frames:v 1 freeze.jpg`. Every later time shifts by `hold`. |
| Freeze hold + flying zoomed card | Dims the freeze; a zoomed card (e.g. the prompt) flies out of the screenshot, holds, flies back | HF | `hf.py:freeze_hold` | `at`, `hold=2.6`, `fly_from=(380,-150)`, `label`, `image`, `left/top/width`, `clip` | `hf.freeze_hold(T, 2.6, (380,-150), "我给 agent 的 prompt", "assets/img/prompt.png")` |
| Transient freeze | Holds the frame from 0.4 s before an accidental screen flash; live audio continues | ffmpeg | `longform-to-short/scripts/transient_scan.py` → `freezes [[a,b]]`, `build_timeline.py`, `render.py` | `transients.white_thresh=.55`, `luma=200` | `transient_scan.py` works on any screen recording. Render the freeze as a `-loop 1` still plus source audio. |

## 7. Transitions

| Effect | What | Engine | Where | Params | Reuse |
|---|---|---|---|---|---|
| 11 scene transitions | `blur` .8, `fade` .45, `push` .7, `vpush` .7, `iris` 1.1, `zoom` .8, `focus` .9, `blocks` 1.1 (8 panels), `chroma` .8, `flip` .9, `zoomout` 1.0 (s = suggested length) | HF | `hf.py:scene_transitions`, `hf.transition`, `hf.TRANSITIONS`; menu in `workflows/explainer/references/transitions.md` | `trans=[transition(type,out_id,in_id,at,d)]`, `W/H`, `wrap=".scene-wrap"`, `blocks=8`, `block_color` | Use them in any HF project with one wrapper div per scene: `tx = hf.scene_transitions([...])`. Put `tx["html"]` above the scenes and below the captions. Stretch each outgoing scene by `d`. |
| 12 photo transitions | `fade`, `push`, `whip`, `flash`, `zoom`, `iris`, `leak`, `ink`, `blinds`, `tear`, `slideup`, `cut` | PIL | `photostory/transitions.py:transition(C, P, N, p, kind)`; durations `TRD` | `p` in 0..1; shot opts `tr=`, `trd=` | Works on any two same-size float32 frames: build a `Ctx` with the right `W/H` (it supplies the `DIST`/`LEAK`/`INK`/`JAG` fields) and call `transition(C, P, N, p, "ink")` per frame of the overlap. |
| Dissolve joins (xfade) | Any ffmpeg xfade between pieces, with acrossfade and mute pads | ffmpeg | `lib/vstudio/cut.py:xfade_assemble`; vlog `build_vlog.py` (`transition`, `xfade=.8`); call-clips `XFADE=.5`, `TRIM_FADE=.16`, `AUTO_FADE=.06` | `pieces`, `xfade`, `speeds`, `transition="fade"` (`dissolve`, `smoothleft`, `fadeblack`…), `fit` | `cut.xfade_assemble(pieces, xfade=0.3, transition="fadeblack")` from any workflow |
| Hook montage | Sped-up hooks with crossfades into the body | ffmpeg | `workflows/talkinghead/scripts/montage.py:Montage` | `hooks`, `body`, `hook_speed=1.3`, `body_speed=1.1`, `xf`, `hook_gain_db` | `Montage(...)` is importable; use `.graph`, `.b2f`, `.join_starts`. The hook menu (12 tagged candidates) is a process step in talkinghead WORKFLOW.md. |
| Speed ramps | Per-segment `setpts` (+ atempo) | ffmpeg | `vlog/build_vlog.py:seg_speed`; `media.atempo_chain` | `speed`, `empty_speed=1.3`, `default_speed=1.2` | `setpts=PTS/s` + `media.atempo_chain(s)` |
| End fade (no fade-in) | `fade=t=out` + `afade`; never a black first frame | ffmpeg | `vlog/build_vlog.py` | `fade_out=1.5` | Use in any final pass |

## 8. Looks / grade

| Effect | What | Engine | Where | Params | Reuse |
|---|---|---|---|---|---|
| Vlog grade | `eq` + warm colorbalance + unsharp | ffmpeg | `vlog/build_vlog.py:grade_chain` | `DEFAULT_GRADE` (bright .05, contrast 1.12, sat 1.18, gamma 1.04), `warm`, `sharpen`, per-segment `bright`; persona `vlog.grade` | Paste the chain into any `-vf` |
| Talking-head grade | Denoise + eq + colorbalance + CAS sharpen | ffmpeg | talkinghead config `GRADE` (vertical default); horizontal `eq=brightness=-0.06:…` | filter string | Paste it. promo-recut `grade:` uses the same convention. |
| HDR → SDR | zscale/tonemap for iPhone HLG | ffmpeg | `lib/vstudio/media.py:hdr_to_sdr_args` | `transfer`, `force` | `media.hdr_to_sdr_args(src)` |
| Film look | Grain always; strong = warm desat, flicker, vignette, scratches, dust | PIL | `photostory/looks.py:film_look(C, box, gt, strong)` | spec `FILM_SECTIONS`, or any `film:` shot | Call it on any `(BOX_H, BOX_W, 3)` float32 frame with a `Ctx` |
| Texture generators | grain, light leak, ink field, torn edge, dark radial bg, paper | PIL | `photostory/looks.py:make_grain/make_leak/make_ink/make_jag/make_bg/paper_bg` | `C`, `seed` | Need a `Ctx` |
| Portrait retouch | Face slim, eyes, de-shine, skin/makeup, body slim | PIL (cv2 + MLS) | `lib/vstudio/retouch.py:retouch` | `slim .05`, `eye .04`, `shine .8`, `smooth .6`, `makeup .5`, `body 0` | `retouch.retouch(img)`; per frame in `talkinghead/scripts/vertical/retouch_video.py` |

## 9. Audio / SFX

| Effect | What | Engine | Where | Params | Reuse |
|---|---|---|---|---|---|
| SFX bank | Synthesised `pop`, `whoosh`, `stamp`/`thud`, `ding` | audio | `lib/vstudio/audio.py:sfx_bank`, `SFX_GAINS`, `write_sfx` | `sr`; gains pop .32, whoosh .4, thud .45, ding .35 | Use `audio.write_sfx("assets/sfx")` to get WAVs for HF `<audio>` clips. For numpy, see the next row. |
| SFX placement | Mix events into a voice track | audio | `audio.py:place_sfx`; talkinghead `compose.py:mix_audio` (pop at pops/tokens, thud at stamps, whoosh at scene changes and hook joins) | `events=[(t,name)]`, `gains`, `bank` | `audio.place_sfx(x, [(3.2,"pop"),(5.0,"whoosh")], sr)`, then `loudnorm_2pass` |
| Card stinger | 1.6 s noise whoosh + 110 Hz thump at −19 dBFS | audio | `longform-to-short/scripts/make_audio_assets.py` → `card_sting.wav` | | Copy the WAV under any chapter card |
| Music bed + ducking | Loops music, ducks it under the voice, optional carve EQ, fades | audio | `audio.py:mix_bed`; `vlog/scripts/add_music.py`; explainer `make_bgm_bed.py` + `carve.mjs` | `duck_db=-10`, `music_lufs=-30`, `carve`, `fade_in/out`, `ambient_db` | `audio.mix_bed(voice, music, out)` |
| Loudness | Two-pass loudnorm to −14 LUFS | audio | `audio.py:loudnorm_2pass`, `normalize_stem` | `lufs`, `tp=-1.5`, `lra=11` | Last step of every workflow |
| Voice anonymize | Pitch shift, duration preserved | audio | `audio.py:pitch_shift_filter`; longform `pitches.windows`, `pitches.semitones=-3` | `semitones`, `tempo` | `-af` with `audio.pitch_shift_filter(-3)` on the window |

## 10. Progress / chapter bars

| Effect | What | Engine | Where | Params | Reuse |
|---|---|---|---|---|---|
| HF chapter progress bar | Bar + ticks + chapter labels on a scrim; the active label lights up | HF | `lib/vstudio/overlays.py:hf_progress` | `chapters [(s,e,label)]`, `start`, `total`, `geo`, `track_index=8` | `p = overlays.hf_progress(chs, 0, total)`, then paste `p["css"]`, `p["html"]` and `p["js"]` |
| Refined / classic bar (per frame) | Refined: segmented gradient bar with knob and a "01 / 03 label" pill. Classic: notes-board bar. | PIL | `overlays.py:progress_bar(style="refined"\|"classic")`; talkinghead `PB_Y=250` | `chapters`, `t`, `total`, `width`, `x0/x1`, `theme` | Paste `progress_bar(...)` each frame |
| Static bar + ffmpeg fill | Dim bar PNG + active labels + drawbox fill / playhead expression | ffmpeg | `overlays.py:progress_static`, `progress_fill`; talkinghead `build_filter.py` | `y=1000`, `x0=80`, `bar_w`, `fps`, `head` | Use it for a pure-ffmpeg pass on landscape video |

## 11. Covers

| Effect | What | Engine | Where | Params | Reuse |
|---|---|---|---|---|---|
| Split cover | Retouched photo + quote + title with highlight + thumbnail + chips + stamp, at several sizes | PIL | `lib/vstudio/cover.py:split_cover`; `workflows/cover/scripts/split_cover.py`; promo `make_cover.py` | `quote`, `title`, `title_highlight`, `thumb`, `chips`, `tag`, `sizes` | `split_cover(cfg)` |
| Notes cover | Frame + sticky-note panels + kicker | PIL | `cover.py:notes_cover`, `sticky_note` | `panels`, `fun`, `kicker`, `mute_bottom` | talkinghead H cover |
| Framed cover | Tilted framed screenshot + eyebrow/big/sub + chips (16:9 and 3:4) | PIL | `cover.py:framed_cover`, `framed` | `copy={eyebrow,big1,big2,sub_lines,chips}`, `size`, `accent` | longform cover |
| Collage cover (pattern A) | 4-frame diagonal collage, teal X-slash, play diamond | HTML → PNG | `workflows/cover/templates/cover_collage.template.html`, `scripts/extract_frames.py collage` | `--cell-w/h`, boxes | `python -m vstudio.render` |
| Face on quadrants (pattern B) | Matted face over 4 slide quadrants | HTML → PNG | `cover/templates/cover_face_quadrants.template.html`, `scripts/matte.py` | `--engine mediapipe\|rvm` | Same |
| Torn-paper scrapbook | Torn-edge photo pieces (SVG turbulence displacement) with a taped title | HTML → PNG | `vlog/scripts/make_cover.py:build_html` | `--hero`, `--frames`, `--config` pieces `{img,left,top,w,h,rot,seed}`, `roughness=13` | Use it with any stills |
| Photo-story cover | Title zone + hero A/B split polaroid + taped polaroid row with red circles | PIL | `photostory/cover.py` | spec `COVER=dict(...)` | `polaroid()`, `circled()` |
| Frame scoring | Picks smiling, eyes-open, centred frames | PIL | `cover.py:score_frames`, `contact_sheet` | `top_n`, `step`, `min_gap` | Run on any talking video |

**Count**: 85 catalogue rows in 11 sections. Several rows bundle named variants: 8 Ken Burns motions, 10 photo
layouts, 10 photo overlays, 11 HF + 12 photo transitions, 9 3b1b techniques, 4 SFX, 4 fit modes and so on.
Counting every named variant gives about 155 effects.

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
   - Photo / image sequences: `photostory.transitions.transition(C, P, N, p, "ink")`.

9. **"Hide a guest's face"**
   - Run `track_face.py` → `apply_sticker.py` → `verify_coverage.py --min-coverage 1.0`.
   - For a camera-off tile, use `cat_avatar.html` + `verify_avatar.py`.
