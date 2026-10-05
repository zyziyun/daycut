# cover — cover images for short and mid-length videos

**Use when:** a video is cut and needs a cover / thumbnail that replaces a dead first frame and doubles as the
platform thumbnail (小红书, Shorts, TikTok, Reels, B站, YouTube). Three patterns: **A** 4-frame diagonal collage of
stills, **B** the speaker's matted face over a 2×2 grid of slides, **C** premium split cover (retouched face photo
left, dark panel right with quote / title / thumbnail / chips) for 4:3 and 16:9 posts.
**Inputs:** the cut video (and/or a face photo, slide PNGs). **Outputs:** `cover.png` (1080×1920, A/B) or
`cover-4x3.jpg` + `cover-16x9.jpg` (C), plus one file per platform on request (see Platforms). Feed the cover to
`workflows/polish` (`--cover`) or `python -m vstudio.export --cover`.

Run from the project folder; `$VSTUDIO` = repo root. Working files go in `work/`.

## Prerequisites
- `./install.sh` done (fonts in the cache, `selfie_segmenter` + `face_landmarker` models).
- Chrome / Chromium / Edge for HTML renders (found via `$CHROME`, PATH, or standard install paths; a broken binary is
  skipped) — or `pip install playwright && playwright install chromium` as fallback.
- Optional, Pattern B only: `torch` if you want the RVM matting engine (GPL-3.0, downloaded at runtime; see below).

## Pick a pattern
| Pattern | Use when | Bias |
|---|---|---|
| A collage | preview content variety; face not needed on the thumbnail | info density |
| B face on quadrants | personal brand; the face drives CTR | personal connection |
| C split cover | horizontal post (小红书 4:3 / YouTube 16:9), quote or "亲测" angle, one hero thumbnail | premium, editorial |

## Pattern A — collage
1. Find 4 moments (1 hook, 2–3 content, optionally 1 face):
   `python3 $VSTUDIO/workflows/cover/scripts/extract_frames.py sheet my-talk.mp4 work/cover_src --every 5`
   → `work/cover_src/contact_sheet.jpg` with timestamps (`--save-frames` also writes full-size `cand_<t>.png`).
   Talking-head source? `extract_frames.py pick my-talk.mp4 work/cover_src --top 6` ranks frames by smile /
   eyes open / centred face (`vstudio.cover.score_frames`) → `pick<N>_<t>.png` + `picks_sheet.jpg`.
2. Pre-crop the cells (crop boxes are fractions of the *decoded* frame; append `:face` to use the face box):
   `python3 $VSTUDIO/workflows/cover/scripts/extract_frames.py collage my-talk.mp4 work/cover_src 2.5 37 76 80:face`
   Defaults fit a "slide on top, face below" layout; change `--slide-box/--face-box` for other layouts.
3. `cp $VSTUDIO/workflows/cover/templates/cover_collage.template.html work/cover.html`, edit the tag, badges,
   headline and pills.
4. `python3 $VSTUDIO/workflows/cover/scripts/render_cover.py work/cover.html -o work/cover.png` (1080x1920; add
   `--platform xiaohongshu --platform douyin ...` for per-platform sizes, see Platforms)

## Pattern B — face on quadrants
1. Pick a **talking** frame (mid-word, mouth slightly open, eyes on camera; idle frames look posed) from the contact sheet
   (or the `pick` ranking above).
2. Crop the face region, stopping **above any burned-in caption band**:
   `python3 $VSTUDIO/workflows/cover/scripts/extract_frames.py face my-talk.mp4 work/cover_src/face_src.png --t 70 --box 0,0.5,1,0.948`
3. Optional retouch: `python3 -m vstudio.retouch work/cover_src/face_src.png work/cover_src/face_src.png --slim .05 --eye .04`
   (`--preset none|natural|daily|glam` for makeup, `--faces all` for group shots; see `references/RETOUCH.md`)
   (`PYTHONPATH=$VSTUDIO/lib` if vstudio isn't pip-installed).
4. Matte: `python3 $VSTUDIO/workflows/cover/scripts/matte.py work/cover_src/face_src.png work/cover_face.png --trim --preview`
   - default engine: MediaPipe selfie segmenter + guided-filter edge refinement (Apache-2.0, fast, CPU).
   - `--engine rvm`: Robust Video Matting, cleaner hair. **GPL-3.0**, not vendored: `torch.hub` downloads it at
     runtime under its own licence. Needs torch; uses MPS/CUDA when available; warm-up passes are built in
     (RVM is recurrent, a single cold pass gives a soft alpha).
   - Caption still visible at the bottom? `--crop-bottom 0.1`.
   - Check `work/cover_face.check.png` (alpha over a checkerboard) for halos.
5. Copy 4 clean slides (from `workflows/slides`) to `work/cover_src/bg_tl.png … bg_br.png`.
6. `cp $VSTUDIO/workflows/cover/templates/cover_face_quadrants.template.html work/cover.html`; set
   `.face-wrap` width/height to the **same aspect as the matted PNG** (matte.py prints it). Otherwise
   `object-fit:contain` shrinks the face and leaves empty space. Example: PNG 1080×770 (1.40) → 980×700.
7. Render as in A (`render_cover.py`).

## Pattern C — premium split cover (retouched face left, dark panel right)
1. Grab the best face frame at full resolution (any aspect; it is scaled to the cover height) and retouch it:
   `python3 -m vstudio.retouch work/cover_src/face.png work/cover_src/face_retouched.png --slim .05 --eye .04 --makeup .5 --preset natural`
   (or put `"retouch": {...}` in the config and split_cover.py does it, cached as `*.retouched.png`).
2. Optional hero thumbnail: a frame of the thing the video shows (an explainer frame, a product shot).
3. Write `work/split_cover.json` from `$VSTUDIO/workflows/cover/examples/split_cover.example.json`:
   - `quote` (serif italic, highlight colour) + `by` line — a short third-party line that frames the post.
   - `title.lines` (CJK bold, auto-shrinks to the panel) with `title.highlight` substrings in `brand.highlight`.
   - `thumbnail.path` + `crop` fractions (rounded corners, drop shadow, hairline outline).
   - `chips` (outlined pills, `ink|dim|highlight|accent`), `stamp` (rotated `brand.accent` tag over the photo, e.g. 亲测),
     `corner_tag` (bottom-right `brand.highlight` tag, e.g. 记笔记 ↓).
   - `outputs`: one entry per size, e.g. 1440×1080 with `photo_w` 760 (4:3) and 1920×1080 with `photo_w` 900 (16:9).
   - `face_x: "auto"` centres the photo crop on the detected face (`vstudio.face`); a number (0–1) overrides.
4. `python3 $VSTUDIO/workflows/cover/scripts/split_cover.py work/split_cover.json [--platforms xiaohongshu:horizontal,xiaohongshu,douyin,youtube]`
5. Look at both sizes. 小红书 shows a centre crop of horizontal covers in the feed, so keep the face and the first
   title line inside the middle ~75 %. Title length rules: `persona.platforms.<platform>.title_max`.

## Platforms
Cover sizes come from `vstudio.platform.cover_size` (PLATFORMS.md):

| platform | cover | feed shows |
|---|---|---|
| 小红书 (`xiaohongshu`, 3:4 / 9:16 posts) | 1080x1440 | whole cover |
| 小红书 horizontal (`xiaohongshu:horizontal`) | 1920x1080 | **centre 4:3** (x 240..1680) |
| 抖音 / TikTok (`douyin`, `tiktok`) | 1080x1920 | profile grid: centre 3:4 |
| YouTube Shorts | 1080x1920 | whole cover |
| YouTube | 1280x720, ≤ 2 MB; keep titles left of x 1100 (timestamp) | whole cover |
| B站 | 1146x717 (16:10) | whole cover |

- **A / B (templates)**: `render_cover.py page.html -o cover.png --platform xiaohongshu --platform douyin --platform youtube`
  lays the page out at a design size of the same aspect (short side 1080), scales type with `--fs`, then resizes to the
  exact cover size; `<out>.<platform>-<orientation>.png` each, + `.feed.jpg` where the feed crops.
- **C (split cover)**: an output with `"platform": "..."` takes its size from the profile. Portrait sizes (3:4, 9:16)
  use the stacked layout (photo band on top, panel below). For 小红书 16:9 the design is laid out **feed-safe**: the
  whole 4:3 design sits in the centre crop and the photo runs on to the left edge (`"feed_safe": false` turns it
  off); every platform output with a feed crop also writes `<path>.feed.jpg`. `--platforms a,b,c` adds outputs.
- V-track talking-head covers: `workflows/talkinghead/scripts/vertical/cover.py config.py --platform ...` (same sizes).

## Rules (all patterns)
- Exact canvas sizes: 1080×1920 for A/B by default (per platform with `render_cover.py --platform`); whatever
  `outputs` says for C.
- **Accent.** The collage / face-quadrant templates use `--cover-accent` = persona `cover.accent` (default teal
  `#2dd4bf`, their original look; `render_cover.py --accent '#ff2442'` for one render). They no longer follow
  `brand.accent`, which stays the on-video red. Pattern C (split cover) still uses `brand.accent` / `brand.highlight`
  (stamp, chips, title highlight) so it matches the video's graphics. Plain `python -m vstudio.render` on a template
  renders teal at 1080x1920.
- Headline pattern for A/B: `Subject <span class="punch">is/isn't [contrarian punch].</span>` (accent italic punch).
  It should be the same sentence as the script hook (see `workflows/preproduction`).
- Fonts: the templates use `@font-face` on `assets/fonts/*` which `vstudio.render` copies from the repo font cache.
  Never point at system fonts.
- Each quadrant / cell must show distinct content; four near-identical frames read as a glitch.
- Trust the decoded frame size over ffprobe metadata (it has reported 720×1280 for a 1080×1920 file).
- The cover only replaces the first ~1 s of picture (`workflows/polish --cover`); audio is untouched.

## Self-check
- [ ] Canvas size exact; PNG opens with no broken transparency
- [ ] Accent/highlight colours match the slides and on-video graphics
- [ ] B: matte has no halo and no caption strip; `.face-wrap` aspect = PNG aspect
- [ ] C: face and title line 1 survive a centre crop; quote fits on one line; chips don't hit the right edge
- [ ] Top tag / headline don't cover the focal content
