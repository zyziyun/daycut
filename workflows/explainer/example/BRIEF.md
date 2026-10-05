---
workflow: general-video
flow: automation
storyboard: yes
message: "Quantization is rounding, done cleverly: trade a little precision for a model that is 4-8x smaller and faster."
destination: youtube
aspect: 1920x1080
language: en
audience: "curious people with limited math background (high-school level)"
length: 5-7min
angle: concept
voice: openai
---

## Intent

A 3Blue1Brown-style explainer of model quantization: why it exists, the principle and
the math (worked by hand), how it is done, what it is for, and the main types. Built for
someone with limited math knowledge: every formula is introduced visually first.
User's words: "should focus on principal/数学计算，为什么，怎么做，how，功能，分类，everything".

## Customizations

- Narration: English, generated with OpenAI TTS (gpt-4o-mini-tts; user switched from Hedra, has OpenAI credit; OPENAI_API_KEY in env). Claude picks the voice; send a short sample first.
- Subtitles: bilingual, burned in, English line on top, 中文 line below, synced to narration. Also export en.srt and zh.srt.
- 3b1b look: dark navy background, animated number lines, weight grids, colour-coded step-by-step equations.

## Notes

- No music bed (voice only), offered as optional later.
- Subtitles occupy the bottom ~22% of frame; keep all math in the top two-thirds.
- Use the OpenAI /v1/audio/speech API directly; word timings via local whisper for subtitle sync.
- Length expanded to ~10 min at user request ("可以再多一些10分钟左右，细化一点，更容易理解"): 18 frames.
- Background music: HeyGen catalog bgm_003 ("calm minimal ambient, whiteboard explainer style"), looped with 6s crossfades to full length, -30 LUFS, carved under narration (strength 0.8). Narration normalized to -16 LUFS.
- Transitions: user asked for "效果动画切换可以更丰富多样一些" → 9 transition types across 17 seams (blur, push, vertical push, circle iris, zoom-through, fade, focus pull, colour blocks, chroma glitch, 3D flip, zoom-out), authored in index.html root timeline on .scene-wrap wrappers.
- Note: tools/make_index.py regenerates index.html; re-run hyperframes-audio carve.mjs after regenerating.
