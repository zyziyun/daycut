"""Effect registry: every visual / audio effect in video-studio as one declarative catalogue.

Each entry (a dict) follows the shot-card idea (what, when, energy, duration, params with how they
feel when changed, pitfalls) plus the machine bits needed to reuse it from code:

  id, name, category, what           identity and a one-line description
  engines                            subset of ENGINES (pil-frame, ffmpeg, hyperframes, html, audio)
  entry                              {engine: [entry point, ...]}; an entry point is
                                       "vstudio.module:attr"      importable from lib/
                                       "path/in/repo.py:symbol"   function, class or config key in that file
                                       "path/in/repo.html"        a template file
  where                              human pointer (markdown) shown in EFFECTS.md
  params                             [(name, default, how it feels when changed)]
  when, energy, duration, max_uses   when to use; low | med | high | n/a; typical length / hold; budget
  pitfalls                           [str]
  tested                             "tests/<file>.py" (covered) or "no"
  reuse, variants                    how to call it from another workflow; named variants bundled in the row

API
  get(id)                                    one entry (KeyError if unknown)
  find(category=, engine=, energy=, text=)   filter; text matches id/name/what/when/variants
  available_in(engine)                       entries that have that engine
  as_markdown()                              the generated block of references/EFFECTS.md
  check_entry(ep)                            (ok, detail) for one entry point

CLI
  python -m vstudio.effects --write-md       regenerate the marker block in references/EFFECTS.md
  python -m vstudio.effects --check          verify every entry point resolves
  python -m vstudio.effects --show ID        print one entry as a card
  python -m vstudio.effects --list [--engine E] [--category C]

To add an effect, see references/ADDING_EFFECTS.md.
"""
import importlib
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
EFFECTS_MD = ROOT / "references" / "EFFECTS.md"
BEGIN = "<!-- BEGIN GENERATED: effects registry (python -m vstudio.effects --write-md) -->"
END = "<!-- END GENERATED: effects registry -->"

ENGINES = ("pil-frame", "ffmpeg", "hyperframes", "html", "audio")
ENGINE_LABEL = {"pil-frame": "PIL", "ffmpeg": "ffmpeg", "hyperframes": "HF", "html": "HTML", "audio": "audio"}
ENERGIES = ("low", "med", "high", "n/a")
REQUIRED = ("id", "name", "category", "what", "engines", "entry", "where", "params", "when", "energy",
            "duration", "max_uses", "pitfalls", "tested", "reuse")

CATEGORIES = {
    "camera": "1. Camera / zoom",
    "layout": "2. Layout / split",
    "cards": "3. Cards & overlays",
    "text": "4. Text & captions",
    "highlight": "5. Highlight / emphasis",
    "freeze": "6. Freeze / hold",
    "transitions": "7. Transitions",
    "looks": "8. Looks / grade",
    "audio": "9. Audio / SFX",
    "progress": "10. Progress / chapter bars",
    "covers": "11. Covers",
}

# path shorthands
TH = "workflows/talkinghead/scripts/vertical/compose.py"
PS = "workflows/photo-story/scripts/photostory/"
VL = "workflows/vlog/scripts/build_vlog.py"
LF = "workflows/longform-to-short/scripts/"
CC = "workflows/call-clips/scripts/"
PR = "workflows/promo-recut/scripts/build_promo.py"

REGISTRY = {}


def _add(id, name, category, what, engines, entry, where, params, when, energy, duration, max_uses,
         pitfalls=(), tested="no", reuse="", variants=()):
    if id in REGISTRY:
        raise ValueError(f"duplicate effect id {id!r}")
    REGISTRY[id] = dict(id=id, name=name, category=category, what=what, engines=list(engines), entry=entry,
                        where=where, params=[tuple(p) for p in params], when=when, energy=energy,
                        duration=duration, max_uses=max_uses, pitfalls=list(pitfalls), tested=tested,
                        reuse=reuse, variants=list(variants))


HF, PIL, FF, HTML, AU = "hyperframes", "pil-frame", "ffmpeg", "html", "audio"

# ------------------------------------------------------------------------------------------------
# 1. Camera / zoom
# ------------------------------------------------------------------------------------------------
_add("punch-in", "Punch-in (eased)", "camera", "Talking head scales up for a window, then back", [HF],
     {HF: ["vstudio.hf:punch_in"]}, "`lib/vstudio/hf.py:punch_in`",
     [("scale", 1.14, "1.08 reads as a breath, 1.14 as 'listen', >1.25 crops the forehead"),
      ("in_dur", 0.45, "<0.3 s snaps like a jump cut; >0.7 s drifts and loses the beat"),
      ("out_dur", 0.5, "keep >= in_dur so the return is gentler than the push")],
     "Stress a sentence in a talking head without cutting", "med", "0.45 s in, window 2-5 s, 0.5 s out",
     "~1 per 20 s of talk; vary windows", ["Put it on an inner wrapper (#face-zoom); keep the outer wrapper free for split / zoom-through"],
     "tests/test_hf.py", "`hf.punch_in([[12.0, 15.5]])` on an inner wrapper around your video")
_add("punch-and-stay", "Punch-and-stay", "camera", "One punch that holds (e.g. on the punchline)", [HF],
     {HF: ["vstudio.hf:punch_at"]}, "`hf.py:punch_at`",
     [("scale", 1.16, "bigger = more 'gotcha'; above 1.25 the face fills the frame"),
      ("dur", 0.5, "shorter feels like a crash zoom"), ("origin", "50% 38%", "aim at the eyes, not the frame centre")],
     "Land a punchline or a reveal and stay there", "high", "0.5 s move, holds to the next cut", "1-2 per video (A7)",
     ["Pairs with hf.stamp ~0.9 s later; do not stack with another full-frame hit (A4)"], "tests/test_hf.py",
     '`hf.punch_at("#ow", 41.2)`, then `hf.stamp(..., at=42.1)`')
_add("wrapper-zoom-entrance", "Wrapper zoom entrance", "camera", "Settles from 1.15x and transparent", [HF],
     {HF: ["vstudio.hf:enter_zoom"]}, "`hf.py:enter_zoom`",
     [("from_scale", 1.15, "1.05 is a soft settle, 1.3 a dramatic arrival"), ("dur", 0.6, "<0.4 s pops, >1 s floats")],
     "Bring in any section wrapper (outro, new section)", "med", "0.6 s", "1 per section",
     ["The wrapper must start hidden (opacity 0) in CSS"], "tests/test_hf.py", "Use it to bring in any section wrapper (promo's outro)")
_add("per-sentence-punch", "Per-sentence punch-in (hard cut)", "camera",
     "Face-centred zoom per sentence: EMPH sids get emph_zoom, odd sids get alt_zoom", [PIL],
     {PIL: [TH + ":zoom", TH + ":EMPH", TH + ":FACE"]}, "`workflows/talkinghead/scripts/vertical/compose.py:zoom`",
     [("emph_zoom", 1.32, "the 'this matters' framing; >1.4 loses the shoulders"),
      ("alt_zoom", 1.16, "alternating framing hides jump cuts; 1.0 disables it")],
     "Vertical talking head with jump cuts between sentences", "med", "one sentence (2-6 s)", "every other sentence; EMPH <= 1 in 4",
     ["compose.py is not importable (reads argv at import); copy zoom() (cv2.warpAffine about the tracked face)"],
     "no", "Copy `zoom()`; in HF use `hf.punch_in`")
_add("ken-burns", "Ken Burns (8 motions)", "camera", "Slow pan / zoom / 3D turn on one photo", [PIL],
     {PIL: [PS + "shots.py:ImageShot"]}, "`workflows/photo-story/scripts/photostory/shots.py:ImageShot`",
     [("motion", "in", "in/out = intimacy vs context; pan follows the reading direction"),
      ("z", 1.12, "end zoom; >1.25 over 4 s reads as a crash, not a drift"),
      ("c", "(0.5, 0.5)", "zoom centre; put it on the subject's eyes or the detail named in the line")],
     "Any still photo held >= 2 s", "low", "3-6 s per photo", "unlimited, but alternate directions",
     ["Needs a photo-story Ctx and shot dict", "Two consecutive shots panning the same way read as one slide"],
     "no", "`ImageShot(C, sh, name).frame(lt)` with a `Ctx`; in HF use the hyperframes-keyframes skill",
     ["in", "out", "panL", "panR", "up", "down", "still", "flip"])
_add("code-zoom", "Code-zoom cut-in", "camera",
     "Tighter crop on the code block, centred on the code-colour centroid, with a seamless join", [FF],
     {FF: [LF + "zoom_targets.py:code_rgb", LF + "build_timeline.py:zoom_crop"]},
     "`workflows/longform-to-short/scripts/zoom_targets.py`, `build_timeline.py:zoom_crop`",
     [("zoom.box", "[736, 336]", "smaller box = bigger code; below ~600 px wide the text pixelates"),
      ("zoom.tol", "colour tolerance", "too loose catches the page background")],
     "Screen recordings where the code / panel is unreadable at full frame", "low", "the whole window being read",
     "as needed (it is legibility, not a flourish)", ["Crop must keep A6 legibility: check at 480 px wide"],
     "no", "`crop=w:h:x:y,scale=W:H` on the window; zoom_targets finds any flat-coloured panel")
_add("zoom-through", "Zoom-through into a framed screen", "camera",
     "The shot scales 1.35x and blurs out while the framed screen lands, then drifts", [HF],
     {HF: ["vstudio.hf:zoom_through", "vstudio.hf:framed_screen"]}, "`hf.py:zoom_through` (+ `framed_screen`)",
     [("scale_in", 0.84, "final screen size; 0.9+ hides the grid backdrop"),
      ("drift", 0.85, "slow drift keeps the screen alive; 0 freezes it")],
     "Go from a talk into a highlights reel or demo", "high", "~1 s move, then the reel", "1 per video (A7)",
     ["Keep the source video playing ~0.5 s past `at`"], "tests/test_hf.py",
     "`hf.zoom_through(at, until)` + `hf.framed_screen(...)`")
_add("stabilize", "Stabilize", "camera", "deshake + crop", [FF], {FF: [VL + ":stab_prefix"]},
     "`workflows/vlog/scripts/build_vlog.py:stab_prefix`",
     [("stab_rx/ry", 32, "search range; raise for walking footage, costs time"),
      ("stab_zoom", 0.93, "crop to hide edges; <0.9 visibly loses resolution")],
     "Handheld phone / walking clips", "n/a", "whole clip", "unlimited", ["Do not add fake shake afterwards (A9)"],
     "no", "Prepend `deshake=rx:ry:edge=clamp,crop=iw*k:ih*k` to any chain")
_add("loupe", "Loupe", "camera", "A magnifier travels a path over the photo", [PIL],
     {PIL: [PS + "overlays.py:loupe"]}, "`photostory/overlays.py:overlays` (`loupe=`)",
     [("loupe", "[(x, y), ...]", "fewer points = calmer path"), ("loupe_mag", 2.3, ">3 makes texture mush")],
     "Show a detail inside a photo (inscription, brushwork)", "low", "3-5 s", "1-2 per video",
     ["Every coordinate is a 0-1 fraction of the box"], "no", "photo-story shot opt; elsewhere copy the block (needs `C.b`)")

# ------------------------------------------------------------------------------------------------
# 2. Layout / split
# ------------------------------------------------------------------------------------------------
_add("split-screen", "Split screen", "layout",
     "Full-frame face clipped to an inset() and slid aside per window; windows < 0.2 s apart are bridged", [HF],
     {HF: ["vstudio.hf:split_screen", PR + ":split_inset"]}, "`hf.py:split_screen`; geometry in `build_promo.py:GEO`",
     [("dur", 0.7, "slide time; <0.5 s jerks, >1 s steals the line"),
      ("bridge", 0.2, "windows closer than this merge so the face does not bounce")],
     "Talking head + something to show (screenshot, recording)", "med", "0.7 s in, window >= 3 s", "the main device of a promo; 1 star use + repeats",
     ["Fill the freed side, or it reads as a broken layout"], "tests/test_hf.py",
     "Any HF project with a talking-head wrapper; fill the freed side with `screenshot_cards` or a `<video>`")
_add("vertical-face-band", "Vertical face band + card", "layout", "9:16 promo: face band on top, card below", [HF],
     {HF: [PR + ":GEO", PR + ":split_inset"]}, '`build_promo.py:GEO["vertical"]`',
     [("split_inset", "inset(200px 40px 1000px 40px round 28px)", "taller band = more face, less card")],
     "Vertical promo with screenshots", "med", "same as split windows", "as split screen",
     ["Card text must still pass A6 at 1080 wide"], "no", "`--orientation vertical`, or pass GEO values to `hf.split_screen`")
_add("call-layouts", "Call layouts", "layout",
     "2 tiles stacked, trio (2 masked guests + host), landscape pair, landscape trio (6 s-smoothed reframe)", [PIL],
     {PIL: [CC + "render_vertical.py:TILE_H", CC + "render_trio.py", CC + "render_landscape.py", CC + "render_landscape_trio.py"]},
     "`workflows/call-clips/scripts/render_vertical.py`, `render_trio.py`, `render_landscape.py`, `render_landscape_trio.py`",
     [("TILE_H", 608, "taller tiles crop more of the shoulders"), ("REFRAME_S", 6, "smoothing; shorter follows faster but wobbles")],
     "Zoom / Meet / Teams recordings", "low", "whole clip", "one layout per clip",
     ["Regions are x,y,w,h of the gallery; recheck after the call layout changes"], "no",
     "`build_clips.py --renderer <file>`; `--guest-region` / `--host-region`", ["vertical", "trio", "landscape", "landscape-trio"])
_add("fit-modes", "Fit: crop / pad / blur-pad / stretch", "layout", "Fit any aspect into the canvas", [FF],
     {FF: ["vstudio.cut:fit_chain", VL + ":fit_chain"]}, "`lib/vstudio/cut.py:fit_chain`; `vlog/scripts/build_vlog.py:fit_chain`",
     [("fit", "crop", "crop fills but cuts; blur keeps the whole shot on a soft bed; pad is honest but boxy")],
     "Mixed-aspect sources in one timeline", "n/a", "whole clip", "unlimited", ["stretch distorts faces; never on people"],
     "tests/test_core.py", "`cut.fit_chain(size, mode)` or `xfade_assemble(fit=...)`", ["crop", "pad", "blur", "stretch"])
_add("browser-chrome-crop", "Browser-chrome crop", "layout",
     "Detects doc / browser headers per span and crops them plus the bookmark bar, then fits and pads", [FF],
     {FF: [LF + "geometry.py:browser_header_px", LF + "render.py"]}, "`longform-to-short/scripts/geometry.py`; `render.py`",
     [("browser_header_px", 115, "too small leaves the tab strip; too big eats the page title")],
     "Screen-share recordings", "n/a", "per span", "unlimited", ["Re-run geometry when the window changes size"],
     "no", "Run geometry.py on any screen recording and use the crop spans")
_add("photo-layouts", "Photo layouts", "layout", "Multi-photo compositions in the picture box", [PIL],
     {PIL: [PS + "shots.py:CollageShot", PS + "shots.py:MedalShot", PS + "shots.py:build", PS + "shots.py:KINDS"]},
     "`photostory/shots.py` (`CollageShot` ... `MedalShot`; factory `build(C, sh, k)`)",
     [("src", '"collage:a,b,c"', "more photos = less time per photo; >4 reads as a contact sheet"),
      ("yaw", "tilt angle", "small (<15 deg) for elegance, large for drama")],
     "Comparisons, sets, routes, quotes inside a photo story", "med", "3-6 s", "vary kinds; each kind 1-2 per video",
     ["Returns a (BOX_H, BOX_W, 3) float32 frame; needs a Ctx"], "no", "`shots.build(C, sh, k).frame(lt)`",
     ["collage", "film", "split", "grid", "rows", "tilt", "deck", "quote", "route", "medal"])
_add("video-in-photo-story", "Video in a photo story", "layout", "Pre-cut, graded clip read frame by frame", [PIL, FF],
     {PIL: [PS + "shots.py:VideoShot"], FF: [PS + "shots.py:prep_video"]}, "`photostory/shots.py:VideoShot`, `prep_video`",
     [("speed", 1.0, "<1 for dreamy slow motion; >1.3 looks like a mistake on people"), ("grade", "VEQ", "match the photo grade")],
     "Short live moments between photos", "med", "2-5 s", "unlimited", ["Grade it like the stills or it pops out"],
     "no", "photo-story spec `src=\"v1234\"`")

# ------------------------------------------------------------------------------------------------
# 3. Cards & overlays
# ------------------------------------------------------------------------------------------------
_add("screenshot-card-3d", "3D screenshot card", "cards", "A card slides in with rotationY -28 to -6 deg, drifts, then leaves", [HF],
     {HF: ["vstudio.hf:screenshot_cards"]}, "`hf.py:screenshot_cards`",
     [("card_w", 760, "wider = more readable, less face"), ("accent", "#FF2442", "brand accent for box / highlights")],
     "Show a screenshot while the speaker talks about it", "med", "card on screen >= 3 s", "1 card per claim; the 3D entry stars once, later cards can enter flatter",
     ["Use high-res screenshots (they get scaled)", "Text inside must pass A6"], "tests/test_hf.py",
     '`hf.screenshot_cards([dict(id="c1", img=..., w, h, s, e, scroll=[[3, 0]])])`')
_add("card-scroll", "Card scroll keyframes", "cards", "The image scrolls to bring row y to the top at time t", [HF],
     {HF: ["vstudio.hf:screenshot_cards"]}, "`hf.py:screenshot_cards` (`scroll=[[t, y], ...]`)",
     [("scroll", "[[t, y_img_px]]", "eased 0.6-1.2 s; faster reads as a jump, slower as dead air")],
     "Long screenshots where the line being discussed is below the fold", "low", "0.6-1.2 s per move", "as needed",
     ["Hold >= 1 s on the target row before highlighting (A1)"], "tests/test_hf.py", "Find rows with `promo-recut/scripts/find_rows.py`")
_add("chips-row", "Chips row", "cards", "Pills pop in one by one; a star chip is gold; all fade at end", [HF],
     {HF: ["vstudio.hf:chips"]}, "`hf.py:chips`",
     [("items", "[[t, text, star]]", "stagger 0.2-0.5 s; accelerate into the last one (A2)"), ("gold", "#F4D35E", "star colour; one star only")],
     "List of features / tags", "med", "pop 0.3 s each, hold >= 1 s full", "1 row per section", ["Only one star chip (A7)"],
     "tests/test_hf.py", '`hf.chips([[3, "Writing", 0], [4, "Video", 1]], end=9)`')
_add("overlay-images", "Chip / badge / tag / stamp images", "cards", "Themed RGBA images for PIL / ffmpeg compositors", [PIL, FF],
     {PIL: ["vstudio.overlays:chip", "vstudio.overlays:badge", "vstudio.overlays:tag", "vstudio.overlays:stamp"]},
     "`lib/vstudio/overlays.py:chip`, `badge`, `tag`, `stamp`",
     [("style", "outline", "outline is quiet, filled is loud, star is the one to remember"), ("scale", 1.0, "match frame height; 1.0 = 1080p")],
     "Any per-frame or ffmpeg compositor", "low", "hold >= 1 s", "unlimited (each style stars once)", ["Pre-render once; do not rebuild per frame"],
     "tests/test_visual.py", "Paste with `draw.alpha_paste`; ffmpeg can overlay as `-loop 1` PNGs",
     ["outline", "filled", "star", "tag", "ghost"])
_add("badge", "Badge (jingxuan / preview)", "cards", "Solid label that slides in", [HF, PIL],
     {HF: ["vstudio.hf:badge"], PIL: ["vstudio.overlays:badge"]}, "`hf.py:badge`; `overlays.badge`",
     [("accent", "#FF2442", "the brand accent; a second colour dilutes it")],
     "Mark a section as highlights / preview", "low", "whole section", "1 per section", [], "tests/test_hf.py",
     'HF: `hf.badge("...", s, d, at)`; PIL: `overlays.badge("...")`')
_add("outlined-tag", "Outlined tag", "cards", "Fading pill (e.g. 'full version / excerpt / 1.1x')", [HF],
     {HF: ["vstudio.hf:tag"]}, "`hf.py:tag`", [("pos_css", "right:160px; top:956px;", "keep clear of captions")],
     "Context labels", "low", "section", "1-2 per video", [], "tests/test_hf.py", "`hf.tag(...)`")
_add("framed-screen", "Framed screen", "cards", "Rounded, shadowed screen playing a video on a grid backdrop; shrinks away at exit", [HF],
     {HF: ["vstudio.hf:framed_screen", "vstudio.hf:grid_backdrop_css"]}, "`hf.py:framed_screen`, `grid_backdrop_css`",
     [("rate", 1.0, "1.1-1.2 tightens a reel without chipmunk audio (muted anyway)")],
     "Any 'video inside a monitor' beat", "med", "length of the reel", "1 per video", ["Enter with zoom_through"],
     "tests/test_hf.py", "`hf.framed_screen(src, start, dur, exit_at)`")
_add("notes-panel", "Notes panel", "cards", "Card with header, bullets and a rotated tag", [PIL, FF],
     {PIL: ["vstudio.overlays:notes_panel", TH + ":PANELS"], FF: [LF + "burn_final.py"]},
     "`overlays.py:notes_panel`; per-row reveal in talkinghead `compose.py` (`PANELS`)",
     [("width", 620, "wider = fewer line breaks but covers the face"), ("theme", "notes-red", "match the creator persona")],
     "Summarise 2-4 points the speaker is listing", "low", "reveal 0.3 s per row; hold >= 2 s after the last row",
     "1 per topic", ["Max ~4 bullets; text must pass A6"], "tests/test_visual.py",
     "PIL image; burn with ffmpeg `overlay=...:enable='between(t,a,b)'`; for HF save a PNG",
     ["notes-red", "notes-yellow", "teal", "navy"])
_add("callout-bubble", "Callout bubble", "cards", "Speech bubble that slides up 24 px", [PIL],
     {PIL: ["vstudio.overlays:callout", TH + ":CALLOUTS"]}, "`overlays.py:callout`; `compose.py` (`CALLOUTS`)",
     [("max_w", 560, "narrow bubbles wrap more lines")], "Side comments, asides", "low", "2-4 s", "~1 per 30 s",
     [], "tests/test_visual.py", "Same as the notes panel")
_add("node-card", "Node card", "cards", "'NEXT' seam card", [PIL],
     {PIL: ["vstudio.overlays:node_card", CC + "render_vertical.py:render_node_card"]},
     "`overlays.py:node_card`; `call-clips/.../render_vertical.py:render_node_card`",
     [("eyebrow", "", "small kicker; keep to 1-3 words")], "Topic change inside a clip", "low", "fade 0.35 s, hold ~1.5 s",
     "1 per topic change", [], "tests/test_visual.py", "Paste at a cut and fade over 0.35 s")
_add("quote-card", "Quote card", "cards", "Balanced quote lines with the speaker in teal", [PIL],
     {PIL: [CC + "render_trio.py:render_quote"]}, "`call-clips/scripts/render_trio.py:render_quote`",
     [("width", 980, "narrower = more lines, more poster-like")], "Pull a strong line from a call", "low", "hold >= 2 s",
     "1-2 per clip", [], "no", "Copy the function")
_add("circle-face-list", "Circle-face list scene", "cards", "Blurred bg, ringed circle crop of the face, title, popping tokens", [PIL],
     {PIL: [TH + ":blurbg", TH + ":circle_inset", TH + ":token_img", TH + ":CIRCLES"]}, "`compose.py` (`blurbg`, `circle_inset`, `token_img`)",
     [("R", 290, "circle radius; bigger keeps the speaker present, smaller gives tokens room")],
     "Listing items while still seeing the speaker", "med", "the list span (4-10 s)", "1-2 per video", ["talkinghead only (not importable)"],
     "no", "Copy the 3 helpers")
_add("shrink-to-card", "Shrink-to-card scene", "cards", "Frame shrinks to a 0.55x rounded card over a blurred copy, with title and lines", [PIL],
     {PIL: [TH + ":card", TH + ":blurbg", TH + ":CARDS"]}, "`compose.py:card`",
     [("s", 0.55, "smaller card = more room for lines, less face"), ("r", 36, "corner radius")],
     "A section summary over the speaker", "med", "4-8 s", "1-2 per video", [], "no", "Copy `card()` + `blurbg()`")
_add("privacy-sticker", "Privacy sticker", "cards", "Face-tracked sticker covering a participant, with a coverage proof", [PIL],
     {PIL: [CC + "track_face.py:region", CC + "apply_sticker.py:sticker", CC + "verify_coverage.py"]},
     "`call-clips/scripts/track_face.py` -> `apply_sticker.py`; `verify_coverage.py`",
     [("scale", 2.40, "coverage margin; lower risks a peeking cheek"), ("smooth", 0.25, "more = calmer sticker, lags fast moves")],
     "Hide a participant's face", "n/a", "whole clip", "unlimited", ["Always run verify_coverage --min-coverage 1.0"],
     "no", "`track_face.py VIDEO --region ...`, then `apply_sticker.py VIDEO --track --sticker cat.png`")
_add("camera-off-avatar", "Camera-off avatar", "cards", "Full-tile cat avatar", [PIL, HTML],
     {HTML: ["workflows/call-clips/assets/cat_avatar.html"], PIL: [CC + "verify_avatar.py"]},
     "`call-clips/assets/cat_avatar.html`, `verify_avatar.py`", [("--tile", "960x540", "match the tile size exactly")],
     "A participant with camera off", "n/a", "whole clip", "unlimited", [], "no", "Render with `render_sticker.py --size 960x540`")
_add("photo-overlays", "Photo overlays", "cards", "Develop, shimmer, dust, pounce holes, red pen, triangle, loupe, timeline, count-up, label", [PIL],
     {PIL: [PS + "overlays.py:overlays", PS + "subtitles.py:make_label"]},
     "`photostory/overlays.py:overlays(C, sh, f, lt)`; `label` in `render.py` + `subtitles.make_label`",
     [("fx", "()", "one fx per shot; stacking reads as a filter pack"), ("hl_t", 0.3, "red pen draw-on time")],
     "Point at something inside a photo story shot", "med", "per shot", "each overlay stars once (A7)",
     ["Coordinates are 0-1 fractions of the box"], "no", "Use them in a photo-story spec",
     ["develop", "shimmer", "dust", "prick", "hl", "tri", "loupe", "tl", "count", "label"])
_add("polaroid", "Polaroid / taped card", "cards", "Taped polaroid with a shadow and caption", [PIL],
     {PIL: ["vstudio.cover:polaroid", PS + "shots.py:make_card"]}, "`lib/vstudio/cover.py:polaroid`; `photostory/shots.py:make_card`",
     [("rot", 0, "+-2-6 deg feels hand-placed; >10 deg feels thrown")], "Scrapbook / travel looks, covers", "low",
     "hold >= 1 s", "unlimited in a scrapbook section", [], "tests/test_visual.py", '`cover.polaroid(img, 600, rot=-4, cap="...")`')

# ------------------------------------------------------------------------------------------------
# 4. Text & captions
# ------------------------------------------------------------------------------------------------
_add("keyword-subtitles-hf", "Keyword subtitles (HF)", "text", "Cue pops up 14 px and fades; highlighted term in the highlight colour", [HF],
     {HF: ["vstudio.hf:subtitles", "vstudio.overlays:cue_html", "vstudio.overlays:hf_cue_css"]},
     "`hf.py:subtitles` + `overlays.cue_html` + `overlays.hf_cue_css`",
     [("geo", "horizontal", "vertical geo sits higher for platform UI")], "Every narrated HF video", "low", "per cue",
     "always on", ["Highlight <= 1 term per cue"], "tests/test_hf.py", "`overlays.cue_html(...)`, then `hf.subtitles(cues)`")
_add("burned-subtitles-pil", "Burned subtitles (PIL)", "text", "Bold line with stroke, keywords in yellow, balanced CJK wrap", [PIL],
     {PIL: ["vstudio.draw:text_layer", TH + ":split_sub", TH + ":chunk_times"]}, "`lib/vstudio/draw.py:text_layer`; talkinghead `compose.py`",
     [("stroke", 6, "thicker survives busy backgrounds but looks heavy"), ("sub_size", 54, "below 5 % of frame height fails A6")],
     "Per-frame compositors", "low", "per cue", "always on", ["Measure the rendered cap height (A6)"], "tests/test_visual.py",
     '`draw.text_layer("...", draw.load_font("cjk-bold", 54))`')
_add("ass-subtitles", "ASS subtitles", "text", "libass burn-in with highlight and bilingual alt line", [FF],
     {FF: ["vstudio.subs:ass_write", LF + "burn_final.py"]}, "`lib/vstudio/subs.py:ass_write`; `longform-to-short/scripts/burn_final.py`",
     [("alt_scale", 0.72, "secondary language size; <0.6 fails A6"), ("outline", 2.4, "thicker on busy video")],
     "Pure ffmpeg pipelines", "low", "per cue", "always on", [], "tests/test_core.py", '`subs.ass_write(cues, "s.ass")`, then `-vf ass=s.ass`')
_add("bilingual-subtitles", "Bilingual EN/ZH subtitles", "text", "EN above ZH; **word** in gold", [PIL],
     {PIL: [PS + "subtitles.py:make_sub", "vstudio.draw:bilingual_layer"]}, "`photostory/subtitles.py:make_sub`",
     [("f2 size", "0.72x", "secondary line size")], "Bilingual stories", "low", "per cue", "always on", [], "tests/test_lib_requests.py",
     "photo-story; elsewhere `draw.bilingual_layer`")
_add("pop-words", "Pop words", "text", "Big stroked word with a -4 deg bounce", [PIL],
     {PIL: [TH + ":pop_img", TH + ":ease_pop", TH + ":POPS"]}, "`compose.py:pop_img` + `ease_pop`",
     [("size", "per pop", "bigger = louder; > 15 % frame height competes with the face"), ("hold", "per pop", ">= 1 s (A1)")],
     "Punctuate a key word", "high", "pop 0.25 s, hold >= 1 s", "<= 1 per 15 s", ["Not on every sentence (A7)"],
     "no", "talkinghead; in HF use `hf.stamp` with `angle=-4`")
_add("title-card", "Title card", "text", "Centred boxed title + gold sub line; back.out pop, lifts away", [HF],
     {HF: ["vstudio.hf:title_card"]}, "`hf.py:title_card`",
     [("hold", 1.9, "< 1 s fails A1"), ("size", 96, "headline size; keep >= 5 % frame height")],
     "Section openers", "med", "pop 0.4 s + hold 1.9 s", "1 per section", [], "tests/test_hf.py", '`hf.title_card("...", s, at, sub="...")`')
_add("hook-title", "Hook title (talkinghead)", "text", "2-line hook title (line 2 has keywords) + badge", [PIL],
     {PIL: [TH + ":HOOK_TITLE", TH + ":HOOK_BADGE_TEXT"]}, "`compose.py` (`HOOK_TITLE`, `HOOK_BADGE_TEXT`)",
     [("hook_badge", "STYLE", "badge text sets the promise; keep 2-4 characters")], "Opening seconds of a short", "high",
     "first 2-4 s", "1 per video", ["One subject in the opening (A8)"], "no", "talkinghead config")
_add("step-labels", "Step labels", "text", "Numbered '01 ...' labels swap in place over a reel", [HF],
     {HF: ["vstudio.hf:step_labels"]}, "`hf.py:step_labels`", [("labels", "[{s, e, n, t}]", "one label per clip; >= 1.5 s each")],
     "Tutorial steps, reels", "low", ">= 1.5 s per label", "1 set per reel", [], "tests/test_hf.py", "`hf.step_labels(labels, start, dur)`")
_add("end-card", "End card", "text", "Serif kicker, big line, dim CTA; staggered fade-ups", [HF],
     {HF: ["vstudio.hf:end_card"]}, "`hf.py:end_card`", [("size", 80, "main line size")], "Outro / CTA", "low", "3-4 s", "1 per video",
     ["The finale before it should be the energy peak (A10)"], "tests/test_hf.py", '`hf.end_card(E, 3.2, "kicker", "main", "CTA")`')
_add("chapter-card", "Chapter card", "text", "Full-frame '02 / 05 + title' card", [PIL],
     {PIL: ["vstudio.overlays:chapter_card", LF + "make_assets.py", PS + "subtitles.py:make_chapter"]},
     "`overlays.py:chapter_card`; `longform-to-short/scripts/make_assets.py`; photo-story `subtitles.make_chapter`",
     [("cards.dur", 1.6, "< 1.2 s and the title cannot be read")], "Chapter boundaries in long videos", "med", "1.6 s",
     "1 per chapter", ["Pair with card_sting.wav"], "tests/test_visual.py", "Render as a PNG and insert as a `-loop 1` still")
_add("running-header", "Running header", "text", "Section names, per-section progress, titles", [PIL],
     {PIL: [PS + "subtitles.py:Header"]}, "`photostory/subtitles.py:Header`", [("SECTIONS", "spec", "<= 6 sections or labels crowd")],
     "Photo stories with sections", "low", "whole video", "always on", [], "no", "photo-story")
_add("3b1b-techniques", "3b1b scene techniques", "text", "Draw-on lines, count-ups, type-in, clip wipes, axis grow, math built term by term", [HF],
     {HF: ["workflows/explainer/references/design-truth.md", "workflows/explainer/assets/reference-scene.html"]},
     "`workflows/explainer/references/design-truth.md`, `assets/reference-scene.html`",
     [("ease", "power2.out", "entrances; back.out(1.6) for pops; sine.inOut for drift"), ("drift", "<= 6 px", "more reads as wobble")],
     "Explainer scenes", "med", "per scene", "each technique stars once per scene", ["Each scene is a sub-composition with its own paused timeline"],
     "no", "Copy from the reference scene",
     ["draw-on", "count-up", "type-in", "clip-wipe", "axis-grow", "stagger", "svgOrigin", "drift", "math-terms"])
_add("slides", "Slides", "text", "Square / vertical slide presets as PNG or animated clip", [HTML],
     {HTML: ["workflows/slides/templates/slides_vertical.template.html", "workflows/slides/scripts/render_slides.py"]},
     "`workflows/slides/templates/slides_vertical.template.html`, `scripts/render_slides.py`, `record_slides.py`",
     [("--accent", "persona", "one accent per deck")], "B-roll for vertical videos", "low", "3-6 s per slide", "unlimited", [],
     "no", "Drop PNGs or clips into any edit", ["s-title", "s-contrast", "s-three", "s-punch", "s-bars", "s-recap"])

# ------------------------------------------------------------------------------------------------
# 5. Highlight / emphasis
# ------------------------------------------------------------------------------------------------
_add("highlighter-rows", "Highlighter rows", "highlight", "A yellow multiply bar sweeps across a screenshot row", [HF],
     {HF: ["vstudio.hf:screenshot_cards"]}, "`hf.py:screenshot_cards` (`hl=[[t, y0, y1, frac]]`)",
     [("frac", 0.6, "width fraction; 1.0 covers the whole row like a marker scrawl")], "Point at one line in a screenshot", "low",
     "sweep 0.5 s, hold >= 1 s", "1-2 per card", [], "tests/test_hf.py", "Rows from `find_rows.py`")
_add("red-box", "Red box", "highlight", "Accent rounded box pops (back.out) around a region", [HF],
     {HF: ["vstudio.hf:screenshot_cards"]}, "`hf.py:screenshot_cards` (`box=[t, y0, y1]`)", [("accent", "#FF2442", "brand accent")],
     "Frame a block in a screenshot", "med", "pop 0.4 s, hold >= 1 s", "1 per card", [], "tests/test_hf.py", "Same as highlighter rows")
_add("stamp-hf", "Stamp", "highlight", "Bordered word slams in from 2.2x", [HF], {HF: ["vstudio.hf:stamp"]}, "`hf.py:stamp`",
     [("angle", -12, "0 is a label, -12 a rubber stamp, beyond -20 slapstick"), ("size", 96, "headline size")],
     "Verdict words ('works', 'tested')", "high", "slam 0.3 s, hold >= 1 s", "1-2 per video (A7)", ["Add stamp.wav at the same time (A11)"],
     "tests/test_hf.py", '`hf.stamp("...", s, d, at)`')
_add("stacking-stamps", "Stacking stamps", "highlight", "White plate + accent stamp slam-ins; same end time = stack", [PIL],
     {PIL: ["vstudio.overlays:stamp", TH + ":STAMPS"]}, "`overlays.py:stamp`; `compose.py` (`STAMPS`)",
     [("angle", 8, "alternate signs when stacking"), ("size", 56, "")], "Per-frame verdicts", "high", "slam 0.25 s each", "1 stack per video",
     ["Animate the scale with ease_pop; thud SFX per stamp, stepping down (A12)"], "tests/test_visual.py", '`overlays.stamp("...", 8)`')
_add("red-pen-ellipse", "Red-pen ellipse + dim", "highlight", "Double ellipse drawn on, outside dimmed 50 %", [PIL],
     {PIL: [PS + "overlays.py:hl", "vstudio.cover:redpen_ellipse", PS + "cover.py:circled"]}, "`photostory/overlays.py` (`hl=`)",
     [("hl_t", 0.3, "draw-on time; faster feels like a teacher's mark")], "Point at a region of a photo", "med", "draw 0.3 s, hold >= 1.5 s",
     "1-2 per video", [], "tests/test_lib_requests.py", "photo-story; for covers `cover.redpen_ellipse`")
_add("gold-count-up", "Gold count-up", "highlight", "Big number counting up, with a caption", [PIL],
     {PIL: [PS + "overlays.py:count"]}, "`photostory/overlays.py` (`count=`)", [("count", '(n, "EN", "ZH")', "")],
     "Numbers worth remembering", "med", "count 1 s, hold >= 1 s", "1-2 per video", [], "no",
     "photo-story; in HF use the explainer count-up proxy pattern")
_add("reveal-fx", "Shimmer / develop / sketch reveal", "highlight", "Gold light sweep; develop from a warm wash; pencil-to-colour", [PIL],
     {PIL: [PS + "overlays.py:shimmer", PS + "overlays.py:develop", PS + "shots.py:pencil"]}, "`photostory/overlays.py`, `shots.py:pencil`",
     [("fx", '("shimmer",)', "one per shot")], "A hero photo's first appearance", "med", "1-2 s", "light effects <= 2 per video",
     ["Light effects are the fastest to cheapen; never on every photo"], "no", "photo-story spec", ["shimmer", "develop", "sketch"])

# ------------------------------------------------------------------------------------------------
# 6. Freeze / hold
# ------------------------------------------------------------------------------------------------
_add("freeze-split", "Freeze-frame split", "freeze", "Video split into clip + still + clip; resumes with data-media-start", [HF],
     {HF: ["vstudio.hf:freeze_clips"]}, "`hf.py:freeze_clips`", [("hold", "2.6", "every later time shifts by hold")],
     "Pause on a moment to explain it", "med", "hold 2-3 s", "1-2 per video", ["Extract the still with ffmpeg -ss cut_at -frames:v 1"],
     "tests/test_hf.py", "`hf.freeze_clips(src, freeze, start, cut_at, hold, media_dur, rate)`")
_add("freeze-hold-card", "Freeze hold + flying zoomed card", "freeze", "Dims the freeze; a zoomed card flies out, holds, flies back", [HF],
     {HF: ["vstudio.hf:freeze_hold"]}, "`hf.py:freeze_hold`",
     [("hold", 2.6, "time to read the card; < 2 s fails A1 for a prompt"), ("fly_from", "(380, -150)", "start offset; from where the text sits in the screenshot")],
     "Enlarge a prompt / a line from a screen", "high", "fly 0.6 s, hold 2-3 s", "1 per video (A7)", [], "tests/test_hf.py",
     '`hf.freeze_hold(T, 2.6, (380, -150), "label", "assets/img/prompt.png")`')
_add("transient-freeze", "Transient freeze", "freeze", "Holds the frame from 0.4 s before an accidental screen flash; live audio continues", [FF],
     {FF: [LF + "transient_scan.py:white_thresh", LF + "build_timeline.py", LF + "render.py"]},
     "`longform-to-short/scripts/transient_scan.py` -> `freezes`, `build_timeline.py`, `render.py`",
     [("white_thresh", 0.55, "lower catches more flashes and more false hits")], "Screen recordings with flashes", "n/a",
     "length of the flash", "as needed", [], "no", "transient_scan works on any screen recording")

# ------------------------------------------------------------------------------------------------
# 7. Transitions
# ------------------------------------------------------------------------------------------------
_add("hf-scene-transitions", "11 scene transitions", "transitions", "GSAP scene-to-scene transitions on wrapper divs", [HF],
     {HF: ["vstudio.hf:scene_transitions", "vstudio.hf:transition", "vstudio.hf:TRANSITIONS"]},
     "`hf.py:scene_transitions`, `hf.transition`, `hf.TRANSITIONS`; menu in `workflows/explainer/references/transitions.md`",
     [("d", "per type (0.45-1.1 s)", "borrowed from both neighbours (A5); longer = calmer"),
      ("blocks", 8, "more panels = busier chapter break")],
     "Scene changes in HF projects; one calm family + iris for the core reveal + blocks for chapters", "med",
     "blur .8, fade .45, push .7, vpush .7, iris 1.1, zoom .8, focus .9, blocks 1.1, chroma .8, flip .9, zoomout 1.0",
     "hard cut is the default; styled ones only where place / day / mood changes (A5)",
     ["Stretch each outgoing scene by d", "Never two transitions on one cut"], "tests/test_hf.py",
     "`hf.scene_transitions([...])`, or `xfade.hf_transitions` for any bridge name",
     ["blur", "fade", "push", "vpush", "iris", "zoom", "focus", "blocks", "chroma", "flip", "zoomout"])
_add("photo-transitions", "12 photo transitions", "transitions", "Per-frame transitions inside the photo-story picture box", [PIL],
     {PIL: [PS + "transitions.py:transition", PS + "transitions.py:TRD"]}, "`photostory/transitions.py:transition(C, P, N, p, kind)`; durations `TRD`",
     [("trd", "TRD[kind] (0.32-0.7 s)", "whip shortest, leak longest")], "Photo stories", "med", "0.32-0.7 s", "vary; <= 2 styled per minute",
     ["Needs a Ctx; for library use prefer xfade.blend"], "no", "`xfade.blend(name, P, N, p)` (no Ctx) or the photo-story function",
     ["fade", "push", "whip", "flash", "zoom", "iris", "leak", "ink", "blinds", "tear", "slideup", "cut"])
_add("xfade-bridge", "Cross-engine transitions (bridge)", "transitions",
     "One transition name in all three engines: HF GSAP, ffmpeg xfade (built-in or custom expr), PIL per-frame", [HF, FF, PIL],
     {HF: ["vstudio.xfade:hf_transitions"], FF: ["vstudio.xfade:ffmpeg_transition", "vstudio.xfade:ffmpeg_expr"],
      PIL: ["vstudio.xfade:blend"]}, "`lib/vstudio/xfade.py` (`blend`, `ffmpeg_transition`, `ffmpeg_expr`, `hf_transitions`, `coverage`)",
     [("name", "fade", "see the coverage matrix below for how faithful each engine is"),
      ("duration", "xfade.default_duration(name)", "same budget rule as A5")],
     "Any time the same look must exist in two engines (a HF explainer and its ffmpeg cut-down)", "med", "per name (0-1.1 s)",
     "same as the source effect", ["Custom ffmpeg exprs are slow (1-2.5 s per 1080p frame)", "Custom exprs assume 8-bit YUV"],
     "tests/test_effects.py", '`cut.xfade_assemble(pieces, transition=xfade.ffmpeg_transition("iris"))`',
     ["blur", "fade", "push", "vpush", "iris", "zoom", "focus", "blocks", "chroma", "flip", "zoomout", "whip", "flash",
      "fadeblack", "light-leak", "ink", "blinds", "tear", "slideup", "cut", "wipe", "dissolve", "pixelize", "radial"])
_add("light-leak", "Light-leak transition", "transitions", "Cross-dissolve under a warm film light leak", [HF, FF, PIL],
     {HF: ["vstudio.xfade:hf_transitions"], FF: ["vstudio.xfade:ffmpeg_transition"], PIL: ["vstudio.xfade:blend", PS + "looks.py:make_leak"]},
     '`xfade.blend("light-leak", ...)`, `xfade.ffmpeg_transition("light-leak")`, `xfade.hf_transitions([("light-leak", ...)])`',
     [("strength", 0.9, "0.5 is a warm glow, 1.0+ blows the highlights out"), ("duration", 0.7, "< 0.5 s reads as a camera flash")],
     "Travel / memory pieces, a change of day or place", "med", "0.7 s", "<= 2 per video (light effects cheapen fast)",
     ["Warm leak on already warm footage clips to orange; lower strength", "Never on a cut inside one scene"],
     "tests/test_effects.py", '`xfade.blend("light-leak", A, B, p)` per frame of the overlap')
_add("xfade-joins", "Dissolve joins (xfade)", "transitions", "Any ffmpeg xfade between pieces, with acrossfade and mute pads", [FF],
     {FF: ["vstudio.cut:xfade_assemble", "vstudio.cut:render_assembly", VL + ":transition"]},
     "`lib/vstudio/cut.py:xfade_assemble`; vlog `build_vlog.py` (`transition`, `xfade=.8`)",
     [("xfade", 0.3, "0.15 is a soft cut, 0.8 a dreamy dissolve"), ("transition", "fade", "any xfade name or xfade.ffmpeg_transition(...)")],
     "Joining pieces in any ffmpeg workflow", "low", "0.15-0.8 s", "unlimited for plain fades", ["Mute pads keep syllables out of the dissolve"],
     "tests/test_core.py", '`cut.xfade_assemble(pieces, xfade=0.3, transition="fadeblack")`')
_add("hook-montage", "Hook montage", "transitions", "Sped-up hooks with crossfades into the body", [FF],
     {FF: ["workflows/talkinghead/scripts/montage.py:Montage"]}, "`workflows/talkinghead/scripts/montage.py:Montage`",
     [("hook_speed", 1.3, "faster = more urgency; >1.5 hurts intelligibility"), ("body_speed", 1.1, "")],
     "Cold open of a short", "high", "3-8 s", "1 per video", ["The creator picks the hooks"], "no", "`Montage(...)` is importable; use `.graph`")
_add("speed-ramps", "Speed ramps", "transitions", "Per-segment setpts (+ atempo)", [FF],
     {FF: [VL + ":seg_speed", "vstudio.media:atempo_chain"]}, "`vlog/build_vlog.py:seg_speed`; `media.atempo_chain`",
     [("speed", 1.2, "1.1-1.3 is invisible tightening; >2 is a deliberate effect")], "Tightening or energy ramps", "med", "per segment",
     "ramps as an effect: 1 star use", [], "tests/test_core.py", "`setpts=PTS/s` + `media.atempo_chain(s)`")
_add("end-fade", "End fade (no fade-in)", "transitions", "fade=t=out + afade; never a black first frame", [FF],
     {FF: [VL + ":fade_out"]}, "`vlog/build_vlog.py`", [("fade_out", 1.5, "longer is wistful; < 0.8 s feels cut off")],
     "Last pass of any video", "low", "1.5 s", "1 per video", ["Never fade in from black (first frame = cover)"], "no", "Use in any final pass")

# ------------------------------------------------------------------------------------------------
# 8. Looks / grade
# ------------------------------------------------------------------------------------------------
_add("vlog-grade", "Vlog grade", "looks", "eq + warm colorbalance + unsharp", [FF],
     {FF: [VL + ":grade_chain", VL + ":DEFAULT_GRADE"]}, "`vlog/build_vlog.py:grade_chain`",
     [("sat", 1.18, ">1.3 skin goes orange"), ("contrast", 1.12, "crushes shadows above 1.2"), ("warm", "on", "warmth reads as memory")],
     "Travel / lifestyle footage", "n/a", "whole video", "one grade per video", ["Check skin tones"], "no", "Paste the chain into any `-vf`")
_add("talkinghead-grade", "Talking-head grade", "looks", "Denoise + eq + colorbalance + CAS sharpen", [FF],
     {FF: [TH + ":GRADE", "workflows/talkinghead/examples/v_config_example.py:GRADE"]}, "talkinghead config `GRADE`", [("eq brightness", -0.06, "horizontal default")],
     "Talking heads", "n/a", "whole video", "one grade", [], "no", "Paste it")
_add("hdr-to-sdr", "HDR to SDR", "looks", "zscale/tonemap for iPhone HLG", [FF], {FF: ["vstudio.media:hdr_to_sdr_args"]},
     "`lib/vstudio/media.py:hdr_to_sdr_args`", [("force", False, "force tonemap on mis-tagged files")], "iPhone HDR sources", "n/a",
     "whole clip", "always for HDR sources", ["Washed-out greys = HDR left untonemapped"], "tests/test_core.py", "`media.hdr_to_sdr_args(src)`")
_add("film-look", "Film look", "looks", "Grain always; strong = warm desat, flicker, vignette, scratches, dust", [PIL],
     {PIL: [PS + "looks.py:film_look"]}, "`photostory/looks.py:film_look(C, box, gt, strong)`",
     [("strong", False, "strong for memories / archive sections only")], "Archive / memory sections", "low", "section", "strong look 1 section",
     [], "no", "Call it on any `(BOX_H, BOX_W, 3)` float32 frame with a Ctx")
_add("texture-generators", "Texture generators", "looks", "grain, light leak, ink field, torn edge, dark radial bg, paper", [PIL],
     {PIL: [PS + "looks.py:make_grain", PS + "looks.py:make_leak", PS + "looks.py:make_ink", PS + "looks.py:make_jag",
            PS + "looks.py:make_bg", PS + "looks.py:paper_bg"]},
     "`photostory/looks.py:make_grain/make_leak/make_ink/make_jag/make_bg/paper_bg`", [("seed", "fixed", "deterministic per seed")],
     "Building blocks for other effects", "n/a", "-", "-", ["Need a Ctx; xfade has Ctx-free leak / ink / jag"], "no", "Need a Ctx",
     ["grain", "leak", "ink", "jag", "bg", "paper"])
_add("portrait-retouch", "Portrait retouch", "looks", "Face slim, eyes, de-shine, skin/makeup, body slim", [PIL],
     {PIL: ["vstudio.retouch:retouch", "workflows/talkinghead/scripts/vertical/retouch_video.py"]}, "`lib/vstudio/retouch.py:retouch`",
     [("slim", 0.05, ">0.08 starts to look warped"), ("smooth", 0.6, "above 0.8 skin goes plastic"), ("makeup", 0.5, "")],
     "Covers and talking heads (creator decides)", "n/a", "whole clip", "always subtle", ["Check identity drift"], "tests/test_retouch.py",
     "`retouch.retouch(img)`")

# ------------------------------------------------------------------------------------------------
# 9. Audio / SFX
# ------------------------------------------------------------------------------------------------
_add("sfx-bank", "SFX bank", "audio", "Synthesised pop, whoosh, stamp/thud, ding, ...", [AU],
     {AU: ["vstudio.audio:sfx_bank", "vstudio.audio:SFX_GAINS", "vstudio.audio:write_sfx"]}, "`lib/vstudio/audio.py:sfx_bank`, `SFX_GAINS`, `write_sfx`",
     [("gains", "pop .32, whoosh .4, thud .45, ding .35", "SFX should sit under the voice")], "Any on-screen action that needs a sound (A11)",
     "n/a", "0.1-1.6 s", "repeats must alternate and step down (A12)", [], "tests/test_beats.py", '`audio.write_sfx("assets/sfx")`')
_add("sfx-placement", "SFX placement", "audio", "Mix events into a voice track", [AU],
     {AU: ["vstudio.audio:place_sfx", "vstudio.audio:cue_sheet_for", TH + ":mix_audio"]}, "`audio.py:place_sfx`; talkinghead `compose.py:mix_audio`",
     [("events", "[(t, name)]", "align to the visual hit, not the beat")], "After picture lock (A12)", "n/a", "-", "<= 2 per 2 s",
     [], "tests/test_beats.py", '`audio.place_sfx(x, [(3.2, "pop")], sr)`')
_add("card-stinger", "Card stinger", "audio", "1.6 s noise whoosh + 110 Hz thump at -19 dBFS", [AU],
     {AU: [LF + "make_audio_assets.py:card_sting"]}, "`longform-to-short/scripts/make_audio_assets.py` -> `card_sting.wav`",
     [("level", "-19 dBFS", "")], "Under a chapter card", "med", "1.6 s", "1 per chapter", [], "no", "Copy the WAV under any chapter card")
_add("music-bed", "Music bed + ducking", "audio", "Loops music, ducks it under the voice, optional carve EQ, fades", [AU],
     {AU: ["vstudio.audio:mix_bed", "vstudio.audio:loop_bed", "workflows/explainer/scripts/make_bgm_bed.py:carve"]},
     "`audio.py:mix_bed`; `vlog/scripts/add_music.py`; explainer `make_bgm_bed.py` + `carve.mjs`",
     [("duck_db", -10, "-6 keeps music present, -14 makes it wallpaper"), ("music_lufs", -30, "")], "Every narrated video", "n/a",
     "whole video", "1 bed (+ a no-music version, A13)", [], "tests/test_core.py", "`audio.mix_bed(voice, music, out)`")
_add("loudness", "Loudness", "audio", "Two-pass loudnorm to -14 LUFS", [AU], {AU: ["vstudio.audio:loudnorm_2pass", "vstudio.audio:normalize_stem"]},
     "`audio.py:loudnorm_2pass`, `normalize_stem`", [("lufs", -14, "platform target"), ("tp", -1.5, "")], "Last step of every workflow",
     "n/a", "-", "always", [], "tests/test_core.py", "`audio.loudnorm_2pass(src, dst)`")
_add("voice-anonymize", "Voice anonymize", "audio", "Pitch shift, duration preserved", [AU, FF],
     {AU: ["vstudio.audio:pitch_shift_filter"]}, "`audio.py:pitch_shift_filter`; longform `pitches.windows`",
     [("semitones", -3, "-2 is subtle, -5 sounds processed")], "Privacy for a voice", "n/a", "window", "as needed", [], "tests/test_core.py",
     "`-af` with `audio.pitch_shift_filter(-3)` on the window")

# ------------------------------------------------------------------------------------------------
# 10. Progress / chapter bars
# ------------------------------------------------------------------------------------------------
_add("hf-progress", "HF chapter progress bar", "progress", "Bar + ticks + chapter labels on a scrim; the active label lights up", [HF],
     {HF: ["vstudio.overlays:hf_progress"]}, "`lib/vstudio/overlays.py:hf_progress`", [("geo", "horizontal", "vertical sits under the platform UI")],
     "Long videos with chapters", "low", "whole video", "always on", ["<= 6 chapters"], "tests/test_visual.py",
     '`p = overlays.hf_progress(chs, 0, total)`; paste css/html/js')
_add("progress-bar-pil", "Refined / classic bar (per frame)", "progress", "Segmented gradient bar with knob and pill, or notes-board bar", [PIL],
     {PIL: ["vstudio.overlays:progress_bar"]}, '`overlays.py:progress_bar(style="refined"|"classic")`',
     [("style", "classic", "refined for polished, classic for notes look")], "Per-frame compositors", "low", "whole video", "always on", [],
     "tests/test_visual.py", "Paste `progress_bar(...)` each frame", ["refined", "classic"])
_add("progress-ffmpeg", "Static bar + ffmpeg fill", "progress", "Dim bar PNG + labels + drawbox fill / playhead expression", [FF],
     {FF: ["vstudio.overlays:progress_static", "vstudio.overlays:progress_fill", "workflows/talkinghead/scripts/build_filter.py:progress"]},
     "`overlays.py:progress_static`, `progress_fill`; talkinghead `build_filter.py`", [("y", 1000, "")], "Pure-ffmpeg landscape passes", "low",
     "whole video", "always on", [], "tests/test_visual.py", "Use it for a pure-ffmpeg pass")

# ------------------------------------------------------------------------------------------------
# 11. Covers
# ------------------------------------------------------------------------------------------------
_add("split-cover", "Split cover", "covers", "Retouched photo + quote + title + thumbnail + chips + stamp, several sizes", [PIL],
     {PIL: ["vstudio.cover:split_cover", "workflows/cover/scripts/split_cover.py"]}, "`lib/vstudio/cover.py:split_cover`",
     [("title_highlight", "", "one highlighted word")], "Talking-head covers", "n/a", "still", "1 per video", [], "tests/test_visual.py", "`split_cover(cfg)`")
_add("notes-cover", "Notes cover", "covers", "Frame + sticky-note panels + kicker", [PIL], {PIL: ["vstudio.cover:notes_cover", "vstudio.cover:sticky_note"]},
     "`cover.py:notes_cover`, `sticky_note`", [("mute_bottom", 150, "")], "Talkinghead horizontal cover", "n/a", "still", "1", [],
     "tests/test_visual.py", "talkinghead H cover")
_add("framed-cover", "Framed cover", "covers", "Tilted framed screenshot + eyebrow/big/sub + chips", [PIL],
     {PIL: ["vstudio.cover:framed_cover", "vstudio.cover:framed"]}, "`cover.py:framed_cover`, `framed`", [("tilt", -3, "")],
     "Longform / course covers", "n/a", "still", "1", [], "tests/test_visual.py", "longform cover")
_add("collage-cover", "Collage cover (pattern A)", "covers", "4-frame diagonal collage, X-slash, play diamond", [HTML],
     {HTML: ["workflows/cover/templates/cover_collage.template.html", "workflows/cover/scripts/extract_frames.py:collage"]},
     "`workflows/cover/templates/cover_collage.template.html`", [("--cell-w/h", "boxes", "")], "Short-video covers", "n/a", "still", "1",
     [], "no", "`python -m vstudio.render`")
_add("face-quadrants-cover", "Face on quadrants (pattern B)", "covers", "Matted face over 4 slide quadrants", [HTML],
     {HTML: ["workflows/cover/templates/cover_face_quadrants.template.html", "workflows/cover/scripts/matte.py:rvm"]},
     "`cover/templates/cover_face_quadrants.template.html`, `scripts/matte.py`", [("--engine", "mediapipe", "rvm for hair detail")],
     "Talk with slides", "n/a", "still", "1", [], "no", "Same")
_add("torn-paper-cover", "Torn-paper scrapbook", "covers", "Torn-edge photo pieces with a taped title", [HTML],
     {HTML: ["workflows/vlog/scripts/make_cover.py:build_html"]}, "`vlog/scripts/make_cover.py:build_html`",
     [("roughness", 13, "higher = rougher tear")], "Vlog covers", "n/a", "still", "1", [], "no", "Use it with any stills")
_add("photo-story-cover", "Photo-story cover", "covers", "Title zone + hero split polaroid + taped polaroid row with red circles", [PIL],
     {PIL: [PS + "cover.py:polaroid", PS + "cover.py:circled"]}, "`photostory/cover.py`", [("COVER", "spec", "")], "Photo stories",
     "n/a", "still", "1", [], "no", "`polaroid()`, `circled()`")
_add("frame-scoring", "Frame scoring", "covers", "Picks smiling, eyes-open, centred frames", [PIL],
     {PIL: ["vstudio.cover:score_frames", "vstudio.cover:contact_sheet"]}, "`cover.py:score_frames`, `contact_sheet`",
     [("top_n", 6, ""), ("min_gap", 2.0, "spread picks across the video")], "Choosing a cover frame", "n/a", "-", "-", [],
     "tests/test_visual.py", "Run on any talking video")


# ------------------------------------------------------------------------------------------------
# API
# ------------------------------------------------------------------------------------------------

def get(id):
    try:
        return REGISTRY[id]
    except KeyError:
        raise KeyError(f"unknown effect {id!r}; try effects.find(text=...)") from None


def find(category=None, engine=None, energy=None, text=None):
    out = []
    t = text.lower() if text else None
    for e in REGISTRY.values():
        if category and e["category"] != category:
            continue
        if engine and engine not in e["engines"]:
            continue
        if energy and e["energy"] != energy:
            continue
        if t and t not in " ".join([e["id"], e["name"], e["what"], e["when"], " ".join(e["variants"])]).lower():
            continue
        out.append(e)
    return out


def available_in(engine):
    if engine not in ENGINES:
        raise ValueError(f"engine must be one of {ENGINES}")
    return find(engine=engine)


def check_entry(ep):
    """(ok, detail). 'vstudio.mod:attr' is imported; 'path/file.py:sym' must exist and mention sym as a word;
    a bare path must exist."""
    if ep.startswith("vstudio."):
        mod, _, attr = ep.partition(":")
        try:
            m = importlib.import_module(mod)
        except Exception as ex:                       # optional dependency missing, etc.
            return False, f"import {mod}: {ex}"
        return (hasattr(m, attr), f"{mod}.{attr}") if attr else (True, mod)
    path, _, sym = ep.partition(":")
    p = ROOT / path
    if not p.exists():
        return False, f"missing file {path}"
    if not sym:
        return True, path
    txt = p.read_text(encoding="utf-8", errors="replace")
    ok = re.search(r"(?<![\w-])" + re.escape(sym) + r"(?![\w-])", txt) is not None
    return ok, f"{path}:{sym}"


def _cell(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def _params_md(e):
    return ", ".join(f"`{n}={d}`" if d not in ("", None) else f"`{n}`" for n, d, _ in e["params"])


def as_markdown():
    """The generated catalogue block of references/EFFECTS.md (stable for a given registry)."""
    from . import xfade
    out = []
    for key, title in CATEGORIES.items():
        rows = find(category=key)
        if not rows:
            continue
        out += [f"## {title}", "",
                "| Effect | What | Engine | Where | Params | When to use | Energy | Hold / duration | Max uses | Reuse | Tested |",
                "|---|---|---|---|---|---|---|---|---|---|---|"]
        for e in rows:
            what = e["what"] + (f" ({', '.join('`%s`' % v for v in e['variants'])})" if e["variants"] else "")
            eng = " + ".join(ENGINE_LABEL[x] for x in e["engines"])
            tested = "-" if e["tested"] == "no" else f"`{e['tested'].split('/')[-1]}`"
            out.append("| " + " | ".join(_cell(c) for c in (
                f"{e['name']} <sub>`{e['id']}`</sub>", what, eng, e["where"], _params_md(e), e["when"], e["energy"],
                e["duration"], e["max_uses"], e["reuse"], tested)) + " |")
        out.append("")
        if key == "transitions":
            out += ["### Transition coverage across engines (`vstudio.xfade`)", "",
                    "exact = same look; near = same idea, small visual difference; approx = closest stand-in.", "",
                    xfade.coverage_markdown(), ""]
    n = len(REGISTRY)
    nv = sum(max(1, len(e["variants"])) for e in REGISTRY.values())
    by_engine = ", ".join(f"{ENGINE_LABEL[g]} {len(available_in(g))}" for g in ENGINES)
    out.append(f"**Count**: {n} registry entries in {len(CATEGORIES)} sections ({nv} counting named variants). "
               f"By engine: {by_engine}. Parameter feel, pitfalls and entry points: "
               "`python -m vstudio.effects --show <id>`.")
    return "\n".join(out).rstrip() + "\n"


def write_md(path=EFFECTS_MD):
    """Replace the BEGIN/END marker block in EFFECTS.md with as_markdown(). Returns True if changed."""
    path = pathlib.Path(path)
    txt = path.read_text(encoding="utf-8")
    if BEGIN not in txt or END not in txt:
        raise ValueError(f"{path} has no generated-block markers")
    head, rest = txt.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    new = head + BEGIN + "\n\n" + as_markdown() + "\n" + END + tail
    if new != txt:
        path.write_text(new, encoding="utf-8")
        return True
    return False


def card(id):
    """One entry as a shot-card-style text block."""
    e = get(id)
    lines = [f"{e['name']}  [{e['id']}]  ({CATEGORIES[e['category']]})", f"  what:      {e['what']}",
             f"  engines:   {', '.join(e['engines'])}", f"  when:      {e['when']}",
             f"  energy:    {e['energy']}   duration: {e['duration']}   max uses: {e['max_uses']}", "  params:"]
    lines += [f"    {n} = {d}" + (f"   -- {f}" if f else "") for n, d, f in e["params"]]
    lines += ["  entry points:"] + [f"    [{g}] {ep}" for g, eps in e["entry"].items() for ep in eps]
    if e["pitfalls"]:
        lines += ["  pitfalls:"] + [f"    - {p}" for p in e["pitfalls"]]
    lines += [f"  reuse:     {e['reuse']}", f"  tested:    {e['tested']}"]
    return "\n".join(lines)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="python -m vstudio.effects", description=__doc__.split("\n")[0])
    ap.add_argument("--write-md", action="store_true", help="regenerate the block in references/EFFECTS.md")
    ap.add_argument("--check", action="store_true", help="verify every entry point")
    ap.add_argument("--show", metavar="ID")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--engine", choices=ENGINES)
    ap.add_argument("--category", choices=list(CATEGORIES))
    a = ap.parse_args(argv)
    if a.write_md:
        print("updated" if write_md() else "unchanged", EFFECTS_MD)
    if a.check:
        bad = [(e["id"], ep, d) for e in REGISTRY.values() for eps in e["entry"].values() for ep in eps
               for ok, d in [check_entry(ep)] if not ok]
        for b in bad:
            print("BROKEN", *b)
        print(f"{len(REGISTRY)} entries, {len(bad)} broken entry points")
        if bad:
            return 1
    if a.show:
        print(card(a.show))
    if a.list or (not (a.write_md or a.check or a.show)):
        for e in find(category=a.category, engine=a.engine):
            print(f"{e['id']:24s} {e['energy']:4s} {','.join(e['engines']):28s} {e['name']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
