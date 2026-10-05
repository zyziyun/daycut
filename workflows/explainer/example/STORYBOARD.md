---
format: 1920x1080
duration: ~10min
message: "Quantization is rounding, done cleverly: trade a little precision for a model that is 4-8x smaller and faster."
arc: Hook → Intuition (rounding, bits) → Why (storage) → Principle (number line) → Math by hand (scale, zero-point, quantize, dequantize, errors cancel) → Types (sym/asym, outliers, granularity, PTQ/QAT) → Real tools → Trade-offs → Recap
audience: curious people with limited math background
mode: collaborative
style: 3b1b-inspired — near-black navy, blue/yellow/teal/red math colour code, serif titles, mono numbers
safe_zone: math lives in y 80–800; bilingual subtitles band y 850–1040
colour_code: "x = blue #58C4DD · s = yellow #F4D35E · z = teal #5CD0B3 · q = pink #E88CC4 · error = red #FC6255"
audio: "voice: OpenAI gpt-4o-mini-tts cedar @1.0 · light ambient music bed, carved under voice"
---

## Changes from v1

- User: "可以再多一些10分钟左右，细化一点，更容易理解" → 14 → 18 frames: added Rounding you already know (02), Bits are switches (04), Why small errors don't add up (11); split Outliers (13) and Granularity (14) with worked numbers; added two more worked quantize examples (09), full dequant table (10), symmetric worked scale (12), calibration (15).
- User: add a light background music bed.

## Locked

- v1 layouts approved by user; voice cedar approved.

## Frame 1 — Hook: 140 GB vs 24 GB

- duration: 19s
- transition_in: cut
- status: animated
- src: compositions/f01-hook.html
- motion: dataviz-countup + stat-bars-and-fills + kinetic-type-beats
- sketch: storyboard.html#frame-01
- voiceover: "Here's a strange fact. A language model with seventy billion parameters needs about a hund…"

## Frame 2 — Rounding you already know

- duration: 30s
- transition_in: crossfade
- status: animated
- src: compositions/f02-rounding.html
- motion: kinetic-type-beats + svg-path-draw (gradient posterize wipe)
- sketch: storyboard.html#frame-02
- voiceover: "Before any math, notice that you round things all the time. A price of three ninety-nine i…"

## Frame 3 — What a weight is

- duration: 24s
- transition_in: crossfade
- status: animated
- src: compositions/f03-weights.html
- motion: svg-path-draw + waterfall-entry + zoom-out-workspace-reveal
- sketch: storyboard.html#frame-03
- voiceover: "So, what numbers are we talking about? Underneath, a neural network is a giant pile of num…"

## Frame 4 — Bits are switches

- duration: 30s
- transition_in: crossfade
- status: animated
- src: compositions/f04-switches.html
- motion: grid-card-assemble + spring-pop-entrance + counting-dynamic-scale
- sketch: storyboard.html#frame-04
- voiceover: "And space is measured in bits. Think of a bit as a light switch. One switch has two positi…"

## Frame 5 — Number formats

- duration: 35s
- transition_in: cut
- status: animated
- src: compositions/f05-formats.html
- motion: grid-card-assemble + stat-bars-and-fills + counting-dynamic-scale
- sketch: storyboard.html#frame-05
- voiceover: "The standard way to store a weight, called F P thirty-two, uses thirty-two bits: one for t…"

## Frame 6 — The core idea: snap to the ruler

- duration: 27s
- transition_in: cut
- status: animated
- src: compositions/f06-number-line.html
- motion: spring-pop-entrance + nudge-curve + waterfall-entry
- sketch: storyboard.html#frame-06
- voiceover: "So here's the core idea. Picture all your weights as dots on a number line. They can sit a…"

## Frame 7 — The scale s

- duration: 29s
- transition_in: crossfade
- status: animated
- src: compositions/f07-scale.html
- motion: svg-path-draw + kinetic-type-beats + coordinate-target-zoom
- sketch: storyboard.html#frame-07
- voiceover: "Let's do one by hand. Here are six weights. The smallest is minus one, the largest is two.…"

## Frame 8 — The zero-point z

- duration: 24s
- transition_in: cut
- status: animated
- src: compositions/f08-zero-point.html
- motion: nudge-curve + spring-pop-entrance
- sketch: storyboard.html#frame-08
- voiceover: "Next, where does zero go? Our ruler starts at minus one, so real zero sits five steps up. …"

## Frame 9 — Quantize

- duration: 46s
- transition_in: cut
- status: animated
- src: compositions/f09-quantize.html
- motion: kinetic-type-beats + waterfall-entry + counting-dynamic-scale
- sketch: storyboard.html#frame-09
- voiceover: "Now the recipe. To quantize a weight x, divide by the scale, round to the nearest whole nu…"

## Frame 10 — Dequantize and error

- duration: 37s
- transition_in: cut
- status: animated
- src: compositions/f10-dequant-error.html
- motion: kinetic-type-beats + coordinate-target-zoom + waterfall-entry
- sketch: storyboard.html#frame-10
- voiceover: "When the model runs, we go backwards. Subtract the zero-point, and multiply by the scale. …"

## Frame 11 — Why small errors don't add up

- duration: 43s
- transition_in: crossfade
- status: animated
- src: compositions/f11-errors-cancel.html
- motion: waterfall-entry + counting-dynamic-scale
- sketch: storyboard.html#frame-11
- voiceover: "But a model has billions of weights. Why don't all these little errors pile up into a big …"

## Frame 12 — Symmetric vs asymmetric

- duration: 46s
- transition_in: crossfade
- status: animated
- src: compositions/f12-sym-asym.html
- motion: comparison-split
- sketch: storyboard.html#frame-12
- voiceover: "What we just did is called asymmetric quantization. The range can be lopsided, minus one t…"

## Frame 13 — The outlier problem

- duration: 35s
- transition_in: cut
- status: animated
- src: compositions/f13-outlier.html
- motion: coordinate-target-zoom + counting-dynamic-scale
- sketch: storyboard.html#frame-13
- voiceover: "Now, the real enemy: outliers. Imagine most weights live between minus one and one, but on…"

## Frame 14 — More rulers: granularity

- duration: 38s
- transition_in: crossfade
- status: animated
- src: compositions/f14-granularity.html
- motion: grid-card-assemble + theme-crossfade-morph
- sketch: storyboard.html#frame-14
- voiceover: "The fix is to use more rulers. Per-tensor quantization uses one scale for an entire layer,…"

## Frame 15 — PTQ vs QAT

- duration: 41s
- transition_in: crossfade
- status: animated
- src: compositions/f15-ptq-qat.html
- motion: comparison-split + svg-path-draw
- sketch: storyboard.html#frame-15
- voiceover: "There's also the question of when to quantize. Post-training quantization, or P T Q, takes…"

## Frame 16 — Real methods

- duration: 33s
- transition_in: crossfade
- status: animated
- src: compositions/f16-methods.html
- motion: grid-card-assemble + spring-pop-entrance
- sketch: storyboard.html#frame-16
- voiceover: "You'll find these ideas inside popular tools. G P T Q quantizes one column at a time, and …"

## Frame 17 — Trade-offs

- duration: 29s
- transition_in: crossfade
- status: animated
- src: compositions/f17-tradeoffs.html
- motion: dataviz-countup + stat-bars-and-fills + svg-path-draw
- sketch: storyboard.html#frame-17
- voiceover: "So what do you actually gain? Going from sixteen bits to eight halves the memory, with alm…"

## Frame 18 — Recap

- duration: 27s
- transition_in: fade
- status: animated
- src: compositions/f18-recap.html
- motion: waterfall-entry + kinetic-type-beats + titlecard-reveal
- sketch: storyboard.html#frame-18
- voiceover: "Let's put it all together. Pick a range, and split it into steps. That's your scale. Mark …"

