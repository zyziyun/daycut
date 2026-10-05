# Adding an effect, and porting one to another engine

Effects live in three places:

1. **Code**: the implementation in one or more engines.
2. **The registry** (`lib/vstudio/effects.py`): one declarative entry per effect.
3. **The catalogue** (`references/EFFECTS.md`): its tables are generated from the registry.

Transitions also have the cross-engine bridge `lib/vstudio/xfade.py`, which gives one name an
implementation in HyperFrames, ffmpeg and PIL.

The entry format borrows the shape of the shot cards in
[video-shotcraft](https://github.com/Vincentwei1021/video-shotcraft) (Apache-2.0): a one-liner, when to
use, duration, energy, a parameter table with how each value feels when changed, and pitfalls. The
fields are restated in our own words. No card content is copied.

---

## 1. Pick the engine(s)

| Engine | Pick it when | Code goes in |
|---|---|---|
| `hyperframes` | The project is already HTML/GSAP (explainer, promo-recut), or the effect needs CSS (3D transforms, clip-path, blur on DOM) | `lib/vstudio/hf.py` (a generator returning `{"css","html","js"}`), or `xfade.py` for transitions |
| `ffmpeg` | The pipeline is a filter graph (vlog, longform, call-clips, polish), or the effect is a whole-frame op (grade, crop, xfade) | A function returning a filter string, in the lib module that owns the area (`cut`, `media`, `overlays`) |
| `pil-frame` | It needs per-frame logic on numpy frames (face tracking, layouts, photo-story) | A pure function on float32 `(H, W, 3)` frames in `lib/vstudio` (`draw`, `overlays`, `xfade`). Do not put it in a workflow script that reads argv at import. |
| `html` | A still (cover, slide) rendered by headless Chrome | `workflows/<wf>/templates/*.html` + `vstudio.render` |
| `audio` | Sound | `lib/vstudio/audio.py` |

Rules of thumb:

- Implement it in the engine where it is cheapest to get *right* first. Port it later through the bridge.
- Put reusable code in `lib/vstudio`. A function inside `workflows/*/scripts` can only be listed as
  "copy this". `compose.py` cannot even be imported.
- A pure function of `(a, b, p)` or `(frame, t)` with no context object is the easiest to share. If your
  effect needs a texture (leak, ink, jag), generate it from the frame shape and cache it with
  `functools.lru_cache`, as `xfade._leak_mask` does. Do not require photo-story's `Ctx`.

## 2. Write the code

- **HF**: follow the HyperFrames rules at the top of EFFECTS.md:
  - Overlays start at `opacity: 0` in CSS.
  - Incoming tweens use `fromTo(..., {immediateRender: false})`. Outgoing tweens use `to()`.
  - Never use two `fromTo` on one target.
  - Inline numbers as JSON (`hf._v`).
- **ffmpeg**: return a string, never run ffmpeg inside the generator. For an `xfade` custom
  expression, use only `A`, `B`, `X`, `Y`, `W`, `H`, `P`, `PLANE` and `a0..a3()` / `b0..b3()`. Never use
  `st()` / `ld()`: xfade's slice threads share those registers, which shows up as random noise. `P` runs
  from 1 to 0, so write `q = (1-P)`. Inputs are 8-bit YUV, so colours need Y/U/V values per plane
  (`xfade._yuv`, `xfade._plane`).
- **PIL**: take float32 frames and return float32 frames of the same shape. Support both 0-255 and 0-1
  ranges (the `peak` argument). At p=0 return A and at p=1 return B exactly. `xfade.blend` already
  enforces that for transitions.

## 3. Add the registry entry

Add one `_add(...)` call in `lib/vstudio/effects.py`, in the right section:

```python
_add("my-effect", "My effect", "highlight",                 # id (kebab-case, unique), name, category
     "One line: what the viewer sees",                       # what
     [HF, PIL],                                              # engines
     {HF: ["vstudio.hf:my_effect"], PIL: ["vstudio.overlays:my_effect"]},   # entry points
     "`hf.py:my_effect`; `overlays.my_effect`",              # where (markdown, shown in EFFECTS.md)
     [("size", 96, "how it feels when you raise / lower it"),
      ("dur", 0.4, "< 0.25 s pops, > 0.8 s floats")],        # params: (name, default, feel)
     "When to reach for it",                                 # when
     "med",                                                  # energy: low | med | high | n/a
     "0.4 s in, hold >= 1 s",                                # typical duration / hold
     "1-2 per video (A7)",                                   # max uses per video
     pitfalls=["What goes wrong in practice"],
     tested="tests/test_effects.py",                         # or "no"
     reuse="`hf.my_effect(...)` from any HF project",
     variants=["a", "b"])                                    # optional named variants
```

Entry-point forms:

- `vstudio.module:attr` is imported.
- `path/in/repo.py:symbol` must exist and mention `symbol` as a word. Use this for functions in workflow
  scripts and for config keys.
- A bare path (a template) must exist.

`python -m vstudio.effects --check` verifies them all.

Then regenerate the catalogue and run the tests:

```bash
PYTHONPATH=lib python3 -m vstudio.effects --write-md      # rewrites the marker block in EFFECTS.md
PYTHONPATH=lib python3 -m vstudio.effects --show my-effect
python3 -m pytest tests -q
```

Never edit the generated block by hand. `test_effects_md_block_is_generated_and_stable` fails when it
drifts. The intro and the recipes outside the markers are hand-written: add a recipe there if the effect
is part of a common request.

## 4. Test template

```python
# tests/test_<area>.py
import numpy as np
from vstudio import effects, xfade            # + your module

def test_my_effect_registry():
    e = effects.get("my-effect")
    assert all(effects.check_entry(ep)[0] for eps in e["entry"].values() for ep in eps)

def test_my_effect_pil_contract():
    a = np.zeros((36, 64, 3), np.float32); b = np.full_like(a, 255)
    f = my_effect(a, b, 0.5)                  # pure function
    assert f.shape == a.shape and f.dtype == np.float32 and np.isfinite(f).all()

def test_my_effect_hf_snippet():
    out = hf.my_effect(...)
    assert set(out) == {"css", "html", "js"}
    assert "opacity: 0" in out["css"]          # overlays start hidden
```

For ffmpeg, render 1-2 s of synthetic `testsrc2` / `smptebars` clips at 160x90 (see
`test_ffmpeg_render_through_xfade_assemble`). Assert the duration, and assert that a mid-effect frame
differs from both ends. Never use real media in tests.

## 5. Snapshot check (look at it)

Tests prove that the effect runs. Only a snapshot shows whether it looks right.

```bash
# PIL: a strip of p = 0.25 / 0.5 / 0.75
PYTHONPATH=lib python3 - <<'EOF'
import numpy as np, subprocess
from PIL import Image
from vstudio import xfade
def grab(src):
    r = subprocess.run(["ffmpeg","-v","error","-f","lavfi","-i",f"{src}=s=480x270:d=1","-frames:v","1",
                        "-pix_fmt","rgb24","-f","rawvideo","-"], capture_output=True)
    return np.frombuffer(r.stdout, np.uint8).reshape(270, 480, 3).astype(np.float32)
a, b = grab("testsrc2"), grab("smptebars")
row = [np.clip(xfade.blend("light-leak", a, b, p), 0, 255).astype(np.uint8) for p in (.25, .5, .75)]
Image.fromarray(np.concatenate(row, 1)).save("snap.png")
EOF
# ffmpeg / HF: grab a mid-effect frame from the rendered file
ffmpeg -ss <offset + d/2> -i out.mp4 -frames:v 1 snap_mid.png
```

Compare the PIL, ffmpeg and HF snapshots side by side at the same p. When you add or change a custom
ffmpeg expression, look for speckle noise. Speckle means a register race or a wrong plane.

## 6. AESTHETICS checklist for a new effect

Fill the registry fields from these rules (see [AESTHETICS.md](AESTHETICS.md)):

- **A1 hold**: if the effect carries information, `duration` includes a hold of at least 1 s.
- **A2 easing**: no linear motion. Use ease-in-out, or accelerate-then-rest for groups.
- **A4 full-frame hits**: if the effect moves the whole frame (shake, flash, frame pump), say "counts as
  a full-frame hit (A4)" in `max_uses`.
- **A5 transitions**: the duration is borrowed from the neighbours. One transition per cut.
- **A6 legibility**: any text is at least 5 % of frame height after scale or perspective.
- **A7 stars once**: `max_uses` is honest. Light, glow and stamp effects are 1-2 per video.
- **A9**: no fake camera shake unless the effect is explicitly documentary.
- **A11**: name the matching SFX in `pitfalls` or `reuse` if the effect is a visible action.

---

## 7. Porting an effect to another engine via the bridge

For transitions:

1. Add or extend the entry in `xfade.SPECS`:
   `_s(what, default_duration, (pil_fn, level, gap), _hf(...), _ff(...), aliases=(...))`.
2. **PIL**: write `_p_<name>(a, b, p, e, pk, **opts)`. `e` is the eased p and `pk` is the white level.
   Use the shared helpers: `_resample` (scale / shift), `_box_blur` / `_box_blur_x`, `_grid`,
   `_lowfreq`, `_rgb(color, pk)`.
3. **ffmpeg**: prefer a built-in xfade name (`ffmpeg -h filter=xfade` lists them). Set `fallback=` if it
   is newer than ffmpeg 5. Otherwise write `_x_<name>()` returning a custom expression (no `st`/`ld`).
4. **HF**: if one of `hf.TRANSITIONS` is the same look, set `_hf("<type>")`. Otherwise add a branch to
   `_hf_custom` and the name to `_HF_CUSTOM`.
5. Be honest about `level`: `exact` (same look), `near` (same idea, small difference) or `approx`
   (closest stand-in). Write the `gap` in one line. `coverage_markdown()` publishes it in EFFECTS.md
   section 7.
6. Run `--write-md` and the tests. `test_every_hf_transition_is_bridged` and `test_blend_endpoints`
   cover new names automatically.

For non-transition effects, there is no automatic bridge. Port the effect by writing a sibling
implementation, list both entry points under their engines in the same registry entry, and state the
difference in `pitfalls`.

## 8. Worked example: light-leak in ffmpeg + PIL + HF

The starting point was photo-story only: `transitions.py` `kind="leak"`. It needed a `Ctx` for the
`LEAK` texture from `looks.make_leak`.

1. **Texture without Ctx**. `xfade.LEAK_BLOBS` holds the three warm radial blobs from `make_leak` as
   0-1 fractions of the frame. `_leak_mask(h, w)` builds the texture from the frame shape and caches it.
2. **PIL**. `_p_leak` is the photo-story formula, with the white level `pk` replacing the hard-coded 255:
   ```python
   np.minimum(pk, a*(1-e) + b*e + leak*pk*(strength*sin(pi*p)))
   ```
   Use it with `xfade.blend("light-leak", A, B, p)` (alias `"leak"`).
3. **ffmpeg**. There is no built-in, so `_x_leak()` writes a custom expression:
   - The blob mask is computed in normalised coordinates (`X/W`, `Y/H`), so the subsampled chroma
     planes line up with luma.
   - It is added per plane: Y +200·k, U −40·k (less blue), V +45·k (more red), with
     `k = strength·sin(πq)·mask`.
   - The result is clipped to 0-255.

   Use it with `cut.xfade_assemble(..., transition=xfade.ffmpeg_transition("light-leak"))`. It costs
   about 1.5 s per 1080p frame.
4. **HF**. `_hf_custom("light-leak")` does three things:
   - It cross-fades the wrappers (`to` on the outgoing one, `fromTo` with `immediateRender: false` on
     the incoming one).
   - It adds an overlay `#tx-leak-<k>`: three `radial-gradient`s in the same blob colours,
     `mix-blend-mode: screen`, `opacity: 0` in CSS.
   - It pulses that overlay to 0.9 and back over `d`.

   Use it with `xfade.hf_transitions([("light-leak", "w-a", "w-b", T, 0.7)])`.
5. **Registry**: entry `light-leak` lists all three entry points, with `strength` and `duration` feel,
   "<= 2 per video", and pitfalls (warm footage clips to orange).
6. **Checks**:
   - `test_blend_endpoints[light-leak]` checks the PIL contract.
   - `test_ffmpeg_render_through_xfade_assemble[light-leak]` checks a real render, including a noise
     check.
   - `test_hf_transitions_mix_native_and_bridge` checks that the overlay starts hidden.
   - The snapshot strip from section 5 compares the three engines by eye.

Known gaps:

- HF uses CSS gradients with a screen blend instead of additive light.
- ffmpeg adds the light in YUV, so very saturated sources shift slightly differently from the PIL RGB add.

---

## Adoption (existing code that should call the bridge)

The bridge and registry add capability without touching existing workflows. The owners of these files
should switch to them:

| Where | Today | Switch to |
|---|---|---|
| `workflows/photo-story/scripts/photostory/transitions.py:transition` | Own per-frame math that needs a `Ctx` | Keep `TRD`. Delegate the frame math to `xfade.blend(kind, P, N, p)`. Same kinds (`leak` is an alias). |
| `workflows/vlog/scripts/build_vlog.py` (`transition`, xfade chain) | Raw xfade names only | Pass `xfade.ffmpeg_transition(name)`, so `whip`, `light-leak`, `iris`, `blocks` etc. work by their shared names. Validate config names with `xfade.resolve`. |
| `workflows/explainer/scripts/make_index.py` | `hf.scene_transitions` with the 11 native types | `xfade.hf_transitions(...)` accepts the same tuples plus `whip`, `flash`, `fadeblack`, `light-leak`, `slideup`, `wipe`, `cut`. |
| `workflows/promo-recut/scripts/build_promo.py` | Uses `hf.scene_transitions` where it has scene cuts | Same as explainer |
| `workflows/talkinghead/scripts/vertical/compose.py` | Hard cuts + `xfade_assemble` fades; scene-change whoosh | Per-frame scene changes can use `xfade.blend`, and ffmpeg joins `xfade.ffmpeg_transition`. Keep the whoosh SFX (`audio.cue_sheet_for`). |
| `workflows/call-clips/scripts/build_clips.py` (`XFADE`) | `fade` dissolves | Unchanged by default. Any styled join should go through `xfade.ffmpeg_transition`. |
| `SKILL.md` section 3 and the "≈155 effects" line | Hand count, transitions row | Point to `vstudio.effects` (`find` / `--list`) and `vstudio.xfade`. The registry count comes from the EFFECTS.md footer. |
| Any new workflow effect | Documented only in prose | Add a registry entry (section 3) and regenerate EFFECTS.md. |
