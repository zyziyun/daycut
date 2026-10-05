# Spoken-script craft (generic)

Craft rules for scripts that will be *spoken* on camera or by TTS: short-form (60–180 s) and mid-length (3–10 min)
explainers. Creator-specific taste (stance, signature phrases, banned phrases, topic domain) lives in the persona
`voice.*` keys, not here. All examples are synthetic.

## 1. Format and length

| Format | Length | Where | Words (at `voice.wpm`, default 165) | Shape |
|---|---|---|---|---|
| Short | 60–90 s | TikTok / Shorts / Reels / 小红书 | ~165–250 | ONE idea, 3 beats: setup → reveal → so-what |
| Long short | 90–180 s | same (Shorts allows 3 min) | ~250–510 | one idea + 2–3 sub-points, one pivot |
| Mid-length | 3–10 min | B站, YouTube | ~500–1650 | 3–5 named sections of 45–90 s, each closes on a takeaway |

Seconds ≈ words ÷ wpm × 60. Speeding the final edit up (see `workflows/polish`) shortens this; write for the
natural pace, not the sped-up one.

## 2. The hook (first 5–10 s) — most of the work

Short / long-short formula, three sentences, ~20 words:
```
[You statement.] [Surprising claim about that thing.] [Anchoring detail: a number, year or size.]
```
- "You check the weather app every morning. Most of its forecast comes from one global model. That model reruns every six hours."
- "You think more RAM makes a laptop faster. It often doesn't. Past a point it changes nothing."

Mid-length: 4–6 sentences, same pattern, or open on a question the viewer recognises from their own life.

Rules: the hook IS the headline (if it can't be the cover text, rewrite it — see `workflows/cover`); no self-intro,
no agenda, no length disclosure; concrete numbers; no throat-clearing (`So,` `Alright,` `OK,`) before sentence one.
Write the hook **last**, once you know what you are hooking into.

## 3. Body

- One idea per sentence; each section delivers one beat (claim, explanation, example or takeaway).
- Continuous prose with spoken connectors (`so`, `and`, `because`, `the thing is`, `what that means`).
- Spoken pivots between sections (`Now here's where it gets interesting`), at most once per major shift.
- Sentence length: average 12–18 words, drop to ~6 for emphasis, never over 25 (split it).
- Concrete over abstract, active over passive, named examples over "modern tools".
- Numbers under 10 spelled out (`eight pages`); 10 and up as digits; years always digits. If TTS reads the script,
  spell numbers the way they should be spoken.
- Expand an acronym once, then use it freely. Use contractions wherever a person would.

## 4. The one insight (mandatory)

Every script carries one paragraph that reframes the topic at a deeper layer — the reason to watch instead of
reading a summary. Patterns:

| Reframe | Synthetic example |
|---|---|
| substrate / hardware constraint | "The algorithm didn't win because it was smarter. It won because it fit the chips." |
| cost pressure behind a design | "Every retry costs money, so idempotency is really a cost ceiling." |
| history most explanations skip | "The key idea was published three years before the famous paper." |
| second-order effect | "Faster training wasn't the point. It made the model finally fit the hardware." |
| inversion of common wisdom | "The rule isn't 'use the biggest window'. It's closer to the opposite." |

Signpost it so the viewer knows this is the moment ("And here's the part I don't see explained enough.").

## 5. Closing (10–15 s)

Hand the viewer a portable thought tool, not an engagement request. Patterns:
- **A, reframe:** "What I find interesting about this isn't X. It's Y." End on a quotable line.
- **B, lens:** "That's the lens I use whenever Z shows up. I ask [question]. [Memorable line.]"
- **C, concrete action** (how-tos only): a specific small thing to go do + a specific comment prompt about it.
- **D, specific comment hook:** "What's a rule in your team that everyone knows but nobody wrote down?"

The last sentence must work as a screenshot on its own. No length disclosure or self-promotion; a channel mention,
if needed, is informational ("The full walkthrough is on the channel.").

## 6. Universal anti-patterns

| Anti-pattern | Why | Fix |
|---|---|---|
| Em-dashes | read as written text, not speech | period or comma |
| Phrase fragments ("Eight pages. 2017.") | slide bullets, not speech | full sentences with subject + verb |
| Creator-trope openers ("OK so quick thing…", "You won't believe…", "Today we're talking about…", "Buckle up") | fake within 2 s | you-statement or the fact itself |
| Generic CTAs ("follow for more", "hope that helps", "smash like", "comment your thoughts") | adds nothing | closing pattern A–D |
| Consulted-authority framing ("every time someone asks me", "as an expert", "most people don't realize") | patronising | observational framing (persona `voice.phrases_prefer`) |
| Reading the slide ("Top is X. Below that, Y.") | annotation, not speech | "At the very top is X. Below that comes Y." |
| Meta-commentary ("this is the most important slide", "if you remember one thing") | wastes time | cut |
| Forward / backward references ("more on that later", "to recap") | navigation noise | cut |
| AI-tell vocabulary (delve, dive into, navigate, leverage, tapestry, journey, comprehensive, robust, seamless, "in today's fast-paced world", "it's important to note") | instantly recognisable | plain words |
| Bare list openers ("Three reasons.") and auto-balanced categories | sound templated | fold the count into a sentence; leave uneven sets uneven |
| Emojis in the spoken script | unreadable aloud | outline notes only |

## 7. Process

1. **Premise** (no script yet): the one takeaway in ≤15 words; what the viewer wrongly believes; the mental tool
   they keep; why you find it interesting. If the takeaway won't fit in 15 words, the topic isn't ready.
2. **Structure:** pick the format, list sections with one-line takeaways, check they tell a story in order.
3. **Draft:** continuous prose, overshoot length, mark the insight paragraph, hook last.
4. **Read-aloud pass** (non-negotiable): tongue-trippers, disguised bullets, padding, doubled definitions,
   forward references, AI-tell words.
5. **Tighten:** cut every sentence without new information or voice; "could the paragraph open on its second
   sentence?" — often yes.
6. **Lint + self-check** (`scripts/lint_script.py`), then lock. After lock: pronunciation drill.

## 8. Templates

Short / long short:
```
[HOOK — 3 short sentences, ends on the anchoring detail]
[TRANSITION — one sentence into the body]
[BODY — one idea, optional 2–3 beats of 15–25 s]
[INSIGHT — one signposted paragraph]
[CLOSING — pattern A/B/C/D, quotable last line]
```
Mid-length:
```
# Title
## HOOK (0–15 s)
## SECTION 1 — name (45–90 s)   transition in, takeaway out
## SECTION 2 … (3–5 sections; the insight sits in the heart section)
## CLOSE (15–30 s)
```
