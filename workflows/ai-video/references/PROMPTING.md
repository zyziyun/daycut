# From concept to prompts: storyboard, character bible, per-model templates

## 1. Concept and script (before any generation)

- Start from a format you can name ("what if an ad were shot like X", a two-person workplace sketch...). When a
  reference video defines the format, break it down first: beat list with timestamps, what repeats, where the
  payoff lands, how text is used on screen.
- Write the dialogue as speech, not translation: short lines a real person in that role would say, distinct
  voices, callbacks that advance rather than repeat. Lock **one approved transcript** with line ids and
  speakers; draft subtitles never override it.
- Comedy structure that scored well in self-review: a hook in the first 3 s, escalation where each beat is
  bigger than the last, rule-of-three (two set the pattern, the third breaks it), a reaction close-up after
  each laugh line, and a deadpan tone ("seriously absurd") instead of mugging.
- Iterate the script with an explicit rubric (logic, characters, idea, jokes, fun, consistency, effect) and
  re-score after every round; stop when a new pivot would restart the scoring.
- Duration: decide it with the user before time-based generation; leave room for pauses and the punchline.

## 2. Character bible and continuity anchors

For every recurring character lock: face (from own photos with consent, or invented), glasses/hair/wardrobe,
silhouette, voice (timbre, pace, accent), and a one-line look string used verbatim in every prompt.

- **Look sheets**: chest-up, plain light-grey background, soft even light, **neutral expression, mouth
  closed**. A smiling look sheet made the character smile in every later shot, even in danger.
- Skin: start from a natural photo and remove only part of the blemishes; keep pores and fine lines. Heavy
  retouching reads as wax once animated.
- Two roles played by one face: separate them by hair + wardrobe + props, and keep each role's identity
  attached to its own sheet/subject.
- **Scene master**: generate one wide still of each location with everybody in their start positions and
  approve it. It is the spatial authority: every shot in that location is derived from it (first frame made
  from the master + the character sheet), so set, light direction, positions and props match.
- Write down physical continuity (which hand holds what, who touches what, wet/dry state, screen direction,
  180-degree line) and repeat the relevant part in each shot prompt.
- Review all anchors together once with the user before the main pass.

## 3. Shot list -> units

Each shot: id, scene, characters, screen duration, camera (size, angle, lens, move), action, lines, audio mode.
Group shots that share a set-up into one unit (`unit:`) and cut them apart in the edit. Plan-time checks in
`plan.py`: duration snapped to what the model accepts, prompt length, number of references, one scene per unit.

## 4. Per-model templates (what `plan.render_prompt` builds)

Shared rules (all models):
- Camera language, not adjectives: "Medium close-up, 85mm, from beside the ledge", "handheld, 35mm documentary",
  "slow drone push-in", "low angle from below". "Cinematic" alone produced template-looking shots.
- Acting line: grounded, restrained, small reactions; nobody looks into the lens; no grinning in danger.
- Texture words: visible pores, flyaway hairs, rain droplets on glasses; negative: plastic/airbrushed skin,
  perfect studio light, oversaturated.
- **No text in frame**: screens, signs and paper stay blank; titles, labels, phone pop-ups, captions and
  disclaimers are added in post (generated text came out garbled, cropped or ghosted every time).
- Audio: ask for dialogue + ambience, **no music** (score in post); say which language and register.
- Framing for bodies: "whole body including legs and feet visible, standing ON TOP of X, not sunk into it".
  Hidden-then-revealed body parts vanish otherwise.
- Avoid extreme angles for faces (top-down onto an upturned face invented a new person); use eye-level or
  side angles and include the character sheet as a reference, not just the scene master.

| Model | Template shape | Notes |
|---|---|---|
| Kling 3.0 Omni | first frame (image_to_image from scene master + look sheet, 3-4 options, pick one) -> image_to_video with "图片1 is the first frame" + one shot of action + dialogue | one prompt = one shot; subjects `<<<id>>>`; 4-6 s; turn smart storyboard off in the web UI |
| Seedance (即梦) | `@图片1 = A (look), @图片2 = B (look), voice @音频1` + scene + `【t0-t1秒】shot ...` blocks + "hold last frame" | up to 15 s, several shots; one line only; cut on real scene changes afterwards |
| MiniMax Hailuo | single shot, first-frame image, camera move words [U: bracket commands like `[Push in]`] | keep prompts short; not used per-shot in the sessions |

## 5. Repairs

Retry only the failed unit; keep accepted takes. When a fix is needed, prefer trimming/splicing an accepted
take over regenerating it. State which take owns the opening, which owns the replacement, and the exact cut
interval. After a repair is accepted, stop using superseded variants: one explicit edit list (`timeline.yaml`).
