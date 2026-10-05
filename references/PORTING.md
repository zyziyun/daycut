# Porting rules (phase 1: bring each old skill / project into `workflows/<name>/`)

Repo: `/Users/ziyun/Desktop/design-ml/video-studio` (public, MIT). You own exactly ONE folder:
`workflows/<name>/`. Never edit anything else (not `lib/`, not other workflows, not
`persona.example.yaml`, not the source skill you are porting — sources are READ-ONLY).

## Target layout
```
workflows/<name>/
  WORKFLOW.md       # the playbook (adapted from the old SKILL.md): when to use, pipeline, commands, gotchas
  scripts/          # runnable code, CLI-driven (argparse or a config path as argv[1])
  references/       # long docs, recipes, gotchas (optional)
  templates/        # HTML/JSON/config templates (optional)
  examples/         # SYNTHETIC or sanitized example configs only
  PORT_NOTES.md     # what you did (see bottom)
```
WORKFLOW.md starts with a one-paragraph "Use when" + "Inputs → Outputs", then the pipeline as numbered
steps with exact commands run from the PROJECT dir (the user's video folder), e.g.
`python3 $VSTUDIO/workflows/<name>/scripts/cut.py work/config.py`. `$VSTUDIO` = repo root.

## Hard rules (public repo)
1. **No absolute personal paths.** Nothing under `/Users/...`, `~/Desktop`, `~/Downloads`, `~/Movies`.
   Inputs/outputs come from CLI args or the per-video config file.
2. **Fonts** only via `from vstudio.config import font` → `font("cjk")`, `font("cjk-bold")`, `font("serif")`,
   `font("serif-italic")`, `font("mono")`, `font("mono-bold")`. No Hiragino/PingFang/Songti/Avenir/Georgia/system paths.
   For HTML/HyperFrames, copy needed font files into the project's `assets/fonts/` at runtime from `vstudio.config.FONT_DIR`.
3. **Face / retouch / segmentation** only via `vstudio.face` (`landmarker()`, `detect()`, index sets like
   `FACE_OVAL`, `LEFT_EYE_RING`, `LIPS_OUT`) and `vstudio.retouch` (`retouch(img, f=..., slim=, eye=, smooth=,
   makeup=, shine=, body=)`, `warp_face`, `deshine`, `skin_and_makeup`, `body_slim`). Models via
   `vstudio.config.model("face_landmarker" | "selfie_segmenter")`. Never import from `photo_retouch`.
4. **Creator taste → persona**, not code: speeds, loudness, brand colours, panel theme, title length rules,
   tags, voice/copy rules, term fixes, creator name. Read with `from vstudio.config import persona`
   (see `persona.example.yaml` for existing keys). If you need a NEW key, use it with a safe default
   (`persona().get("x", {}).get("y", default)`) and list it in PORT_NOTES.md — do not edit persona.example.yaml.
5. **No personal content** in code, docs or examples: real names (Wendy, Ziyun, Momo, guests), real
   conversation/script text, real company/product demo URLs, meeting names, face embeddings (`*.npy`),
   personal photos/videos. Replace with neutral placeholders ("Speaker A", "my-talk.mp4").
   Keep generic craft knowledge (gotchas, measured numbers, style menus) — that is the value.
6. **Bootstrap import** at the top of every Python script:
   ```python
   import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
   ```
   (`parents[3]` from `workflows/<name>/scripts/x.py`; adjust for deeper files.)
7. **macOS-only tools** (avconvert, `/Applications/Google Chrome.app`, mlx_whisper) need a fallback or a
   clear check: ffmpeg zscale/tonemap for HDR→SDR; find Chrome/Chromium via `shutil.which` + common paths or
   use Playwright; whisper via `mlx_whisper` if importable else `faster_whisper`.
8. **Third-party code/assets**: keep only what is ours or clearly licensed; note any doubtful asset
   (stickers, SFX, music) in PORT_NOTES.md instead of copying it. Do not vendor GPL code.
9. Keep scripts working: `python3 -m py_compile` every .py; `--help` must run for argparse CLIs.
   Do not run long renders. Do not download large media.
10. Don't silently drop capabilities. If something can't be made generic, keep it working behind config
    and say so in PORT_NOTES.md.

## PORT_NOTES.md (required, short)
- Source(s) ported and what was dropped (with reason).
- Capability list, tagged: cut, pause-squeeze, filler-dedup, asr, captions, bilingual, speed, loudness,
  music, sfx, zoom, split-screen, overlays, notes-panels, progress-bar, hook, freeze-frame, retouch,
  face-track, privacy-mask, hdr, grade, cover, publish-copy, long-to-short, episodes, transitions,
  b-roll, screenshot-cards, tts, photo-fx, other.
- Functions that DUPLICATE something other workflows likely also have (loudnorm, whisper wrapper,
  subtitle time-mapping, notes panels, progress bar, face tracking, cover rendering…) with file:function,
  so phase 2 can unify them into `lib/vstudio`.
- New persona keys used.
- Anything left platform-specific or unverified.
