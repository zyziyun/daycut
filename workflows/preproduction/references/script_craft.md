# Spoken-script craft (generic)

Craft rules for scripts that will be *spoken* on camera or by TTS: short-form (60–180 s) and mid-length (3–10 min)
explainers. Creator-specific taste (stance, signature phrases, banned phrases, topic domain) lives in the persona
`voice.en.*` / `voice.zh.*` keys, not here. All examples are synthetic.

## 1. Format and length

| Format | Length | Where | Words (at `voice.en.wpm`, default 165) | Shape |
|---|---|---|---|---|
| Short | 60–90 s | TikTok / Shorts / Reels / 小红书 | ~165–250 | ONE idea, 3 beats: setup → reveal → so-what |
| Long short | 90–180 s | same (Shorts allows 3 min) | ~250–510 | one idea + 2–3 sub-points, one pivot |
| Mid-length | 3–10 min | B站, YouTube | ~500–1650 | 3–5 named sections of 45–90 s, each closes on a takeaway |

中文口播: count characters instead of words, at `voice.zh.cpm` (default 270 字/min ≈ 4.5 字/s): short ≈ 270–405 字,
long short ≈ 405–810 字, mid ≈ 810–2700 字. `lint_script.py --platform <name>` replaces these with the platform's
sweet spot × pace.

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

## 7. Worked revisions (synthetic)

Fresh examples on neutral topics, written in the learner-educator voice (`voice.en`). Each one is
Before → why it fails → After.

**Hook** (topic: why phone batteries degrade)

- Before: "OK so quick thing. Today we're talking about batteries — and honestly, most people don't realize how they work."
- Why it fails: throat-clearing opener, an agenda instead of a claim, an em-dash, and authority framing that tells
  the viewer they're behind. Nothing concrete in the first five seconds; no number to anchor it.
- After: "You charge your phone to a hundred percent every night. That habit wears the battery out faster than
  heavy use does. After about five hundred full cycles, most phones hold noticeably less."

**One paragraph** (topic: why a spreadsheet slows down as it grows)

- Before: "Spreadsheets get slow. Formulas. Lots of them. When you have a comprehensive workbook with many sheets
  that reference each other and also volatile functions that recalculate every time anything changes anywhere in
  the file, performance can degrade significantly (especially on older laptops)."
- Why it fails: three fragments read like slide bullets, then one 40-word sentence nobody can say in a breath;
  "comprehensive" is an AI-tell word, the parentheses can't be spoken, and "performance can degrade" is abstract.
- After: "What I find interesting is that the size of the file isn't really the problem. Some functions recalculate
  every time you touch any cell, even one on another sheet. So a workbook with a few hundred of them redoes all that
  work on every keystroke. That's the lag you feel when you type."

**Closing** (topic: why bus timetables pad their schedules)

- Before: "So yeah, that's basically why buses are late sometimes. Hope that helps! Let me know in the comments and
  follow for more."
- Why it fails: a summary that adds nothing, then three generic CTAs. The last line can't stand alone as a screenshot.
- After (pattern B, lens): "That's the lens I keep coming back to when a schedule looks generous. I ask who it's
  protecting. Most of the time, slack in a timetable is a promise someone decided to keep."

**中文口播（自信从业者口吻，`voice.zh`）** (题目：为什么冰箱不要塞太满)

- Before: "家人们，今天给大家分享一个冰箱小技巧——很多人不知道，冰箱其实不能塞太满哦，记得点赞关注！"
- 为什么不行：套路开头、破折号、"很多人不知道"的居高临下、结尾求关注；没有具体数字，也没讲清原因。
- After: "冰箱塞满七成以上，制冷反而会变差。冷气要靠流动才能带走热量，塞得太满，风道一堵，靠里的东西就冷不透。
  我的做法是留出出风口前面那一拳的空间。说白了，冰箱冷不冷，看的不是功率，是空气能不能走得动。"

## 8. Process

1. **Premise** (no script yet): the one takeaway in ≤15 words; what the viewer wrongly believes; the mental tool
   they keep; why you find it interesting. If the takeaway won't fit in 15 words, the topic isn't ready.
2. **Structure:** pick the format, list sections with one-line takeaways, check they tell a story in order.
3. **Draft:** continuous prose, overshoot length, mark the insight paragraph, hook last.
4. **Read-aloud pass** (non-negotiable): tongue-trippers, disguised bullets, padding, doubled definitions,
   forward references, AI-tell words.
5. **Tighten:** cut every sentence without new information or voice; "could the paragraph open on its second
   sentence?" — often yes.
6. **Lint + self-check** (`scripts/lint_script.py`), then lock. After lock: pronunciation drill.

## 9. Templates

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
