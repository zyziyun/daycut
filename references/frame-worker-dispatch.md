# Dispatch context (read after _role.md)

- PROJECT_DIR: <PROJECT_DIR>
- Canvas 1920×1080. Captions: enabled — root caption track owns y > 840; keep every element at y ≤ 800.
- Output for each assigned frame: `compositions/<frame_id>.html` and `compositions/<frame_id>.motion.json` (NOT compositions/frames/).
- Every frame has a user-confirmed sketch: `storyboard/sketches/fNN.svg` (same 1920×1080 coordinates as the canvas). Keep its layout and copy; ignore its bottom subtitle band (y ≥ 850).
- REFERENCE IMPLEMENTATION (already passes lint and renders correctly — copy its structure exactly):
  `compositions/f07-scale.html`. Same pattern: @font-face inside the template with root-relative `assets/fonts/...` paths; `#root` sized 100% with no background; one full-duration `class="clip"` stage div (data-start=0, data-duration=<scene duration>, data-track-index=1) holding a full-size `<svg viewBox="0 0 1920 1080">`; GSAP loaded by `<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js">` INSIDE the template; one IIFE that builds repeated SVG nodes with createElementNS, then one paused timeline registered at the end as `window.__timelines["<frame_id>"]`.
- Lessons already learned from lint (hard rules):
  1. Asset paths are project-root-relative (`assets/fonts/stix-two-text.ttf`), never `../`.
  2. Do not call `tl.fromTo()` twice on the same target. For a second animation of an element use `tl.to()` (or add `immediateRender: false` to the later fromTo's destination vars).
  3. Root `data-composition-id` = file name = timeline key = frame_id. Root has `data-width="1920" data-height="1080" data-duration="<duration>"`.
  4. Prefix every id and class with `<frame_id>-`.
  5. No background on #root, no full-bleed ground (index paints it). No `<audio>`.
  6. Use the true minus sign "−" (U+2212) for negative numbers in visible text.
- You MAY run `npx hyperframes lint` from PROJECT_DIR to check your files (it lints all present compositions; only fix findings in YOUR files). Do not edit index.html, STORYBOARD.md, frame.md, or any other frame's file. Do not run render or snapshot.
- When done, reply with one line per frame: frame_id, final duration, and any deviation from the shot sequence.
