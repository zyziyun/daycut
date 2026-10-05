# Portrait retouch (`vstudio.retouch`)

Skin smoothing (磨皮), makeup (彩妆) and reshape for **stills** (covers) and **video** (talking-head bodies).
Everything is our own code on OpenCV / NumPy; the only models are MediaPipe's (Apache-2.0).

```python
from vstudio.retouch import retouch, RetouchState
out = retouch(img, lm=landmarker)                          # stills: detects the main face
out = retouch(img, f=face, preset="daily", makeup=.5)      # with a face you already have
out = retouch(frame, f=tracked, state=RetouchState(video=True), grid=160, makeup=.3)   # video
```
```bash
python3 -m vstudio.retouch in.png out.png --preset natural            # stills CLI
python3 $VSTUDIO/workflows/talkinghead/scripts/vertical/retouch_video.py body_v.mp4 x --test 300,2500
python3 $VSTUDIO/workflows/talkinghead/scripts/vertical/retouch_video.py body_v.mp4 body_rt.mp4 --workers 5
```

## Pipeline
1. **Reshape** - Moving Least Squares (rigid) warp: jaw/cheek controls pulled toward the face axis (`slim`),
   eye rings scaled (`eye`, plus `eye_extra` only while squinting). Landmarks are moved by the same
   deformation (no re-detection), so later masks sit on the reshaped face.
2. **De-shine** - specular highlights pulled toward the skin median (`shine`).
3. **Skin mask** - multiclass selfie segmenter face-skin (body-skin under the chin for the neck at
   `neck` strength) ∩ landmark oval, with holes for eyes / brows / lips; glasses frames (thin
   elongated lines + the segmenter's accessory class), hair strands over the forehead and stubble are
   cut out. No model -> the landmark oval mask (graceful fallback, same API).
4. **Smoothing** - three-band frequency separation in Lab with a guided filter (own box-filter
   implementation; `cv2.ximgproc` when opencv-contrib is present):
   high band (pores, < ~0.6 % face width) x `pores`; mid band (blemishes, unevenness) x (1 - 0.85 `smooth`);
   base tone-evened toward the median skin chroma and a broad local mean (`tone`) and lifted by `light`.
   The lift is on the base only, so texture never washes out.
5. **Blemishes / under-eye** - small dark or red mid-band outliers lose their mid band (`blemish`;
   stills on, video off by default); a crescent under each lower lid is lifted toward cheek
   luminance and de-blued (`undereye`).
6. **Makeup** - see presets. Everything is Lab: chroma moves toward a shade, luminance is shifted,
   never replaced, so lip lines, brow hairs and skin texture survive.
7. **Composite** - a feathered ellipse per face; nothing outside the face (hands, shirt, wall) changes.

## Knobs (defaults: stills / video)
| knob | stills | video | what it does |
|---|---|---|---|
| `slim` | .05 | .042 | jaw / cheek pull toward the face axis |
| `eye` | .04 | .04 | eye ring enlargement (keep small with glasses: lenses already warp) |
| `eye_extra` | 0 | 0 | extra enlargement only while squinting |
| `natural_cap` | .12 | .12 | cap on `slim + eye` (both scaled down proportionally) |
| `identity_guard` | .10 | .10 | max relative drift of landmark ratios (jaw/cheek width vs height, eye vs interocular, mouth, nose-chin); edits beyond it are scaled back |
| `shine` | .8 | .7 | de-shine strength |
| `smooth` | .6 | .55 | mid-band attenuation (0 = none, 1 = mid band -85 %) |
| `pores` | .8 | .8 | high-band gain (1 = untouched texture) |
| `tone` | .35 | .3 | base chroma / luminance evening |
| `light` | .05 | .04 | base luminance lift on skin |
| `blemish` | .5 | 0 | small spot removal |
| `undereye` | .35 | .3 | under-eye lightening + de-blue |
| `neck` | .5 | .5 | neck smoothing strength relative to the face |
| `makeup` | .5 | .3 | overall makeup intensity, 0.5 = preset as designed, 1.0 = double (each component capped at 1) |
| `preset` | natural | natural | `none`, `natural`, `daily`, `glam` |
| `lip` `blush` `brow` `liner` `shadow` `contour` `highlight` `gloss` | preset | preset | per-component strength override (then x `makeup`/0.5) |
| `lip_shade` `blush_shade` `shadow_shade` `liner_shade` | preset | preset | shade name (`rose coral red berry nude pink peach brown black taupe bronze plum mlbb`) or `#rrggbb` |
| `glasses` | auto | auto | `auto` detects frames; `thick` forces liner/shadow off; `none` disables frame handling |
| `skin_seg` | True | True | False = landmark-only skin mask |
| `faces` | main | main | `all` = every face wider than `min_face` (fraction of image width, .06) |
| `face_strength` | None | - | per-face multiplier list, largest face first (e.g. `[1, .6]`) |
| `grid` | 640 | 160 | MLS evaluation grid (longest side); video reuses the field while controls move < 0.35 px |
| `body` | 0 | 0 | whole-body horizontal slim (selfie segmenter); disables the face-only composite |

Video defaults live in `retouch_video.py: VIDEO_DEFAULTS`; persona `retouch.video.<knob>` overrides them
(e.g. `retouch: {video: {makeup: 0}}` to turn makeup off), CLI flags override both. **Video makeup is on by
default**: `natural` preset at `makeup .3` (lips / blush / brows only, landmark-anchored masks; flicker-tested, see
Video: temporal stability). `--makeup 0` turns it off.

## Presets
| preset | lip | blush | brow | liner | shadow | contour | highlight | shades |
|---|---|---|---|---|---|---|---|---|
| none | 0 | 0 | 0 | 0 | 0 | 0 | 0 | - |
| natural | .45 | .35 | .3 | 0 | 0 | .15 | .2 | rose lip, pink blush |
| daily | .65 | .45 | .45 | .35 | .3 | .25 | .25 | rosy pink lip (`mlbb`), peach blush, bronze lid, brown liner |
| glam | .9 | .55 | .6 | .7 | .6 | .4 | .4 | red lip, rose blush, plum lid, black liner |

- Lipstick: lip ring minus the inner mouth (teeth / tongue untouched); chroma moves toward the shade
  around the lip's own median (variation kept), L shifted; gloss = highlights of the ORIGINAL lip
  luminance brightened.
- Blush: soft ellipse from the cheek apple toward the temple, slightly lifted; skin-mask clipped.
- Brows: shape-following fill in the colour of the darkest brow hairs; only lighter gaps darken; tapered
  (soft head, full arch, lighter tail).
- Eyeliner: along the upper lash line, thin at the inner corner, thicker outward, short upward tail.
- Eyeshadow: gradient from the lash line toward the crease, eye opening excluded.
- Contour / highlight: under the cheekbone and along the jaw / nose bridge, forehead centre, chin,
  upper cheekbone.
- Glasses: frame pixels are excluded from all makeup and smoothing; under thick frames (> 2.8 % face
  width) eyeliner and eyeshadow are skipped.

## Video: temporal stability
- `vstudio.face.VideoFaceTracker`: VIDEO-mode landmarker on a face crop (face ≈ half the crop, ≤ 640 px),
  crop re-centred with hysteresis, IMAGE-mode full-frame detection to (re)acquire. `face.detect` keeps
  VIDEO-mode timestamps strictly increasing per landmarker (a lost-face re-acquire used to re-send the same
  timestamp and crash the chunk); a tracker error is re-raised with the frame index and time.
- Telemetry: the MediaPipe 0.10.x task library links a Google usage logger (clearcut, `play.googleapis.com/log`)
  and exposes no opt-out in its Python API or environment (checked on 0.10.35), so vstudio cannot switch it off.
  Retouch works offline; block that host at the firewall if you need zero outbound traffic.
- `vstudio.face.LandmarkSmoother`: One Euro filter in face-width units; centroid filtered separately from
  the per-landmark offsets; eyes / lips / brows get a higher cutoff (blinks and speech are not lagged),
  the outline that carries the slim warp is steadier. Resets on cuts.
- `RetouchState`: segmentation EMA'd in a landmark-anchored canonical face frame; MLS field cache.
- Chunks: each worker processes `WARMUP` = 15 frames before its first written frame and discards them,
  so filter / tracker / mask state is continuous across seams.
- Measured (1080p talking head with thin metal glasses, 180 frames, 3 workers, makeup .3 natural):
  frame-to-frame mean abs diff inside lips / cheeks vs the source: luma ratio 1.01 / 0.94, Lab-a ratio
  1.00 / 1.00; chunked vs single-worker output at the seams differs no more than elsewhere (encode noise).
  ~0.8 s/frame/worker.

## Video speed presets (long videos)
`retouch_video.py --preset fast|quality` (the flag also takes a makeup preset; pass it twice for both, e.g.
`--preset fast --preset daily`).

| preset | what it does | measured (1080x1920 talking head, Apple Silicon, 1 worker) |
|---|---|---|
| `quality` (default) | everything at full resolution; landmarks on a 640 px face crop; 160 px MLS grid re-solved when controls move > 0.35 px; x264 medium | ~0.64 s/frame |
| `fast` | MLS reshape at full resolution; de-shine, skin and makeup on a **half-resolution** copy, added back as an upsampled delta (full-res pore texture untouched); landmarks on a 384 px crop; 240 px grid reused until controls move > 1 px; blemish pass off; x264 faster | ~0.21 s/frame (~3x) |

Expected throughput with 5 workers (workers share cores, so scaling is below linear): a 1-minute 30 fps body
(1,800 frames) takes roughly 4-6 min on `quality` and 1.5-2 min on `fast`; a 10-minute body roughly 45-60 min vs
15-20 min. Difference on a real frame: mean abs 1.9 levels (quality vs source: 3.7); `fast` smooths slightly less
fine detail. Use `fast` for long courses / drafts, `quality` for short hero clips and anything with close-ups.
Always look at `--test` frames of the preset you render with.

## Before / after guidance
- Always check `--test` frames (video) or the cover crop at 100 % before committing to a render: look at
  the jaw line against hair / background (warp), glasses frames (must stay sharp), lip edges (no paint
  outside the line), under-eye (no grey patch).
- If skin looks plastic: lower `smooth` first, then raise `pores` toward 1. If it looks blotchy: raise `tone`.
- Glasses wearers: keep `eye` ≤ .04; prefer `natural` / `daily`; try `--glasses thick` if liner lands on rims.
- Video: keep `makeup` ≤ .4 and `blemish` 0 unless the clip is short and static.

## Ethics / disclosure
Retouching changes how a real person looks. Defaults are deliberately mild and the identity guard caps
reshaping. Retouch only people who agreed to it, never to deceive (e.g. IDs, dating profiles, "no filter"
claims), and follow platform rules: 小红书 / Douyin / YouTube may require labelling AI-altered or
beautified content. Leave moles, scars and other identity features alone unless the person asks
(`blemish` only touches spots under ~2 % of face width; set it to 0 to keep everything).

## Licences: what we use and what we deliberately do not
- Used: MediaPipe Face Landmarker, Selfie Segmenter and Selfie Multiclass Segmenter (Apache-2.0, model
  cards from Google; downloaded by `install.sh`). MLS (Schaefer et al. 2006), guided filter
  (He et al. 2010) and One Euro (Casiez et al. 2012) are independent implementations from the papers.
- Not used: CodeFormer (S-Lab licence, non-commercial), GPEN / GFPGAN (restoration models with
  non-permissive or mixed-licence weights and identity-altering hallucination), EleGANt and other
  makeup-transfer GANs (research licences, dataset terms), BiSeNet face-parsing weights trained on
  CelebAMask-HQ (non-commercial dataset terms), GPL makeup ports (would force GPL on this MIT repo).
  Generative restoration also invents skin and changes identity - the opposite of what we want here.
