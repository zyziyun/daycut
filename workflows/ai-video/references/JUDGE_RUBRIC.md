# Take review rubric ("不要太 AI")

Every generated take is reviewed before it enters the edit: `judge.py sheet` (12-frame strip + 3 large
frames + transcript), then fill `judge.py card`, then `judge.py verdict`. Compiled during the sessions from
public AI-video detection checklists, de-AI prompting guides and script-supervisor continuity practice, then
extended with every failure the creator caught that the reviewer had passed.

**How to look** (each one was learned by missing something):
- Faces at **full size**, side by side with the look sheet: face shape, nose, mouth, glasses. A person small
  in a wide shot was smiling and got passed; a "looks like her" judgement by thumbnail was wrong twice.
- Falls, collapses, dissolves: a frame every **0.25 s** (`--dense`). Eight evenly spaced frames hid a body
  that lost its legs mid-shot.
- Listen and transcribe: wrong words, wrong speaker, a shout that should be a normal voice.
- Check against the scene master and the continuity notes, not just "does it look good".

## Hard flaws (any one = redo)
1. Identity drift - face, glasses, hair, outfit differ from the sheet or change within the take; roles swapped.
2. Premise missing - the action or spatial relation the shot exists for is not on screen.
3. Hands / limbs - extra or fused fingers, hand shape morphing, limbs through objects.
4. Physics - objects through bodies, appearing / vanishing / duplicating, gliding instead of walking.
5. Generated text - any readable or garbled text (all text is added in post).
6. Lip-sync or line - mouth does not match, wrong words, wrong speaker.
7. Body integrity - a hidden part is gone when revealed; person merged into an object; half a body.
8. Scene master - set, positions, props, which hand holds what, screen direction differ from the master.

## Soft flaws (3 or more = redo or fix in post)
plastic skin; perfect symmetry / one-block teeth; dead stare or mechanical blinks; helmet hair; glasses
warping; lighting that does not match the set; oversaturation; studio-dry sound outdoors or unasked music;
template "AI epic" camera; over-acting (open-mouth screaming, grinning, mugging); looking into the lens or
laughing in danger.

## Scores (1-5)
- **A identity**: 5 = matches the sheet throughout; 3 = recognisable with visible drift; 1 = different person / roles swapped.
- **B continuity**: space (180-degree line, eyelines), props (same hand), time (light/weather), performance
  (end of previous shot matches start of next). 5 = cuts invisibly; 3 = one visible jump; 1 = geography unreadable.
- **C completeness**: the shot's information + beat reads at a glance, timing right.
- Whole film (after assembly): **D fun** (hook in 3 s, escalation, rule of three, callbacks advance, pause
  before the laugh line, reaction close-ups), **E originality** (something only this video has).

**Pass**: no hard flaw, A >= 4, B >= 4. **Film pass**: all five >= 4.

## Fixed in post, not judged
-10..15 % saturation, light grain, one grade for all takes, loudness via `vstudio.export` (-14 LUFS).
