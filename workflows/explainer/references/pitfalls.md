# Pitfalls (each one happened)

## HyperFrames composition
- **Asset paths are project-root-relative** (`assets/fonts/x.ttf`), never `../assets/...` — lint error `invalid_parent_traversal_in_asset_path`, and Studio 404s.
- **Everything inside `<template>`** in a sub-composition: `<style>`, `<script>`, the GSAP `<script src>`. Head content is discarded.
- **Never `fromTo` twice on the same target** — the second call's from-values become the resting state before any tween runs (`gsap_repeated_fromto_without_baseline`). Use `tl.to()` for later animations, or `immediateRender: false`.
- **Root id = file name = timeline key.** Prefix every other id/class with the scene id.
- **No ground on scene roots.** The index paints one shared background; scenes are transparent so transitions composite cleanly.
- **Caption track** host needs `data-track-kind="captions"`.
- **Sub-composition internal duration caps visibility.** Lengthening the host slot is not enough: the scene's own root + stage clip `data-duration` must be stretched too, or the outgoing scene vanishes when a transition starts (`make_index.py --patch-scenes`).
- Never name a font with no shipped file (system CJK fonts fall back silently in the headless renderer). `JetBrains Mono` is bundled by the renderer; STIX and CJK fonts need `@font-face`.

## Audio
- OpenAI TTS returns 24 kHz mono WAV; normalize the joined narration to −16 LUFS. Final mixed render landed at −14.7 LUFS.
- `media-use resolve --type bgm` needs the **HeyGen CLI** (`curl -fsSL https://static.heygen.ai/cli/install.sh | bash`, then `heygen auth login --oauth`) — `hyperframes auth login` alone is not enough. Put `~/.local/bin` on PATH.
- `carve.mjs` needs `@hyperframes/core` installed in the project at the pinned CLI version.
- Regenerating `index.html` drops the carve attributes — re-run carve after every `make_index.py`.

## Subtitles
- Whisper sometimes swallows the first word of a line; start each line's first cue at the line's audio offset, not at the first transcribed word.
- Display text ≠ spoken text. Spoken "zero point five one divided by zero point two" must read "0.51 ÷ 0.2". Keep the word "one" when it's a pronoun ("one question", "one outlier").
- Long EN cues wrap to two lines; keep EN ≤ ~100 chars, ZH ≤ ~40.

## Content / design
- One colour = one meaning for the whole film (x blue, s yellow, z teal, q pink, error red). Workers will copy sketch colours even when they break the code — check.
- Mark illustrative charts as illustrative on screen.
- Snapshot at ~85 % of each scene window (most content visible) and mid-transition; a scene's first second is mostly empty by design.
- Sketch text with multiple spaces collapses in SVG — use `&#160;`.
