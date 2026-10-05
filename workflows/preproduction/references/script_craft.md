# Spoken-script craft (generic)

Craft rules for scripts that will be *spoken* on camera or by TTS: short-form (60–180 s) and mid-length (3–10 min)
explainers. Creator-specific taste (stance, signature phrases, banned phrases, topic domain) lives in the persona
`voice.en.*` / `voice.zh.*` keys, not here. All examples are synthetic.

## 0. Scope and stance

Use for: drafting a short or mid-length spoken script, revising a draft that sounds creator-tropey, robotic or
machine-written, cutting a long piece down into short versions, fixing pacing, a flat hook or a generic ending.

Not for: marketing copy, sales scripts and ad reads (different persuasion rules); long video essays over ~15 min
(they need their own cadence and chaptering); written articles and blog posts (spoken cadence reads oddly on the
page). The default stance below is tuned for education / explainer content; other genres should override it in
persona `voice.<lang>.persona`.

Generic stance rules (the persona refines them, it rarely needs to contradict them):
- Confident but observational: share what you noticed, don't pronounce from above.
- No false modesty either ("I'm probably wrong, but", "I'm no expert"); it reads as fishing and wastes seconds.
- "We" only when it really includes the viewer ("we finally had a fix"), never a royal we.
- The speaker is a person talking to one viewer, not a narrator addressing "everyone".

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

All three formats share the voice and the rules below; they differ in **hook intensity** and **section count**.
Pick the format before writing a word.

## 2. The hook (first 5–10 s) — most of the work

Short / long-short formula, three sentences, ~20 words:
```
[You statement.] [Surprising claim about that thing.] [Anchoring detail: a number, year or size.]
```
- "You check the weather app every morning. Most of its forecast comes from one global model. That model reruns every six hours."
- "You think more RAM makes a laptop faster. It often doesn't. Past a point it changes nothing."

- "Cleaning out the garage is the job everyone postpones. It's also the easiest one to split up. Fifteen minutes a day is enough."

Mid-length: 4–6 sentences, same pattern (you-statement → claim → anchoring detail → transition), or open on a
question the viewer recognises from their own life: "Why does every printer jam the week of a deadline? The
answer has less to do with luck than with humidity."

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
- Expand an acronym once, then use it freely. Use contractions wherever a person would (`it's`, `you're`,
  `won't`); the uncontracted form only for emphasis.
- Connectors such as `so`, `because`, `the thing is`, `honestly` are speech scaffolding, not filler: keep them.
  Padding is different: "so what I want to say is", "basically what I'm getting at" add nothing, cut them.

Word-level pairs:
```
abstract:  The system maintains state across sessions.
concrete:  The app re-sends your whole history every time you hit enter.

passive:   A warning is shown by the browser.
active:    The browser shows a warning.

vague:     modern note-taking tools
named:     a paper notebook, a notes app, a sticky note on the monitor
```

### Shape per format
- **Short (60–90 s):** one idea total, three beats (setup → reveal → so-what), one or two sentences per beat.
- **Long short (90–180 s):** one main idea and 2–3 supporting points; one spoken pivot at the major turn. If the
  video pairs with slides, budget ~6–12 s of narration per slide (see `workflows/slides`).
- **Mid-length (3–10 min):** 3–5 named sections of 45–90 s. Open each with a one-sentence transition; close each
  on a takeaway, never a summary of what was just said.

### Every line must be speech, not a slide
A line that ends in a period is a full sentence with a subject and a verb. Fragments belong on the slide, not in
the voice-over.
```
fragment:  Twelve volts. Two wires.
spoken:    The whole thing runs on twelve volts. It only needs two wires.

fragment:  No timer, no sensor, no schedule.
spoken:    There was no timer. There was no sensor. Nobody had a schedule.

annotation: Kettle. Teapot. Cup.
spoken:     The kettle comes first. The teapot comes next. And at the very end comes the cup.
```

### What to cut (dead weight in every script)
- Forward references: "we'll get to that in a minute", "more on that later".
- Backward recaps: "so, to recap what we just covered".
- Meta-flagging: "this is really important", "if you remember one thing".
- Self-narration about the medium: "in this video", "on this slide", "across these twelve slides", timing or
  slide-count references, navigation hints.
- Filler reassurance: "don't worry if this doesn't click", "this might sound complicated".
- Doubled definitions: "the router, which is the box that sends traffic, basically the thing that routes" → say it once.

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

Signpost it so the viewer knows this is the moment. Generic signposts (the persona `voice.<lang>.signposts` adds
the creator's own; `lint_script.py` looks for both):
- "And here's the detail I don't see explained enough."
- "But there's one part of this that most explanations skip."
- "The part that doesn't get talked about enough is this."
- "What's actually happening underneath is different."

## 5. Closing (10–15 s)

Hand the viewer a portable thought tool, not an engagement request. Patterns:
- **A, reframe:** "What I find interesting about this isn't X. It's Y." End on a quotable line.
- **B, lens:** "That's the lens I use whenever Z shows up. I ask [question]. [Memorable line.]"
- **C, concrete action** (how-tos only): a specific small thing to go do, one line that admits the gap between
  watching and doing, and a specific comment prompt about what they tried.
- **D, specific comment hook** (topics that invite discussion): "What's a rule in your team that everyone knows but
  nobody wrote down?" Never the generic "drop your thoughts below".

The last sentence must work as a screenshot on its own. Never "hope that helps", "wild, right?", "follow for more";
no length disclosure, channel branding or self-promotion. A channel mention, if needed (e.g. a short pointing at the
long version), is informational ("The full walkthrough is on the channel."). One closing line, not two CTAs.

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
| A list of names standing alone ("Kettles, toasters, blenders.") | list fragment | "Kettles, toasters and blenders all fail the same way." |
| Filler reassurance ("don't worry if…", "this might sound complex") | spends seconds on nothing | cut |
| False modesty ("I might be wrong, but…") | undercuts the claim | state it; hedge only a specific fact |
| Two CTAs in a row ("Hope that helps. Don't forget to subscribe.") | both generic | one quotable line or one specific prompt |
| Emojis in the spoken script | unreadable aloud | outline notes only |

`scripts/lint_script.py` catches the mechanical ones (dashes, tropes, CTAs, authority, AI-tell, meta, reassurance,
emoji, long sentences, likely fragments); stance, doubled definitions and slide-reading need the read-aloud pass.

## 7. Worked revisions (synthetic)

Fresh examples on neutral topics, written in the learner-educator voice (`voice.en`). Each one is
Before → why it fails → After.

**Hook, three rungs** (topic: why a houseplant dies in winter). Fixing a hook is usually two steps, not one:

- Bad (throat-clearing): "Hey everyone, welcome back. Today I want to talk about houseplants and a few things I've
  learned about keeping them alive."
- Better, still authority-flavoured: "Every time someone asks me why their plant died, I give the same answer. It
  was the water."
- Best (formula: you → claim → anchor): "You water your plant every Sunday. In winter that schedule is what kills
  it. Most indoor plants need about half as much from November on."

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
- Same topic, pattern A (reframe): "What I find interesting isn't that buses run late. It's that the timetable
  already expects them to. The schedule was never a prediction, it was a buffer."
- Pattern C (concrete action, a how-to on reading timetables): "If this was useful, try it on your own line
  tomorrow. Find the stop where the timetable suddenly adds two minutes. Watching a video about it is easy, spotting
  it on a real sheet is the part that sticks. Tell me which stop on your route has the biggest gap."

**中文口播（自信从业者口吻，`voice.zh`）** (题目：为什么冰箱不要塞太满)

- Before: "家人们，今天给大家分享一个冰箱小技巧——很多人不知道，冰箱其实不能塞太满哦，记得点赞关注！"
- 为什么不行：套路开头、破折号、"很多人不知道"的居高临下、结尾求关注；没有具体数字，也没讲清原因。
- After: "冰箱塞满七成以上，制冷反而会变差。冷气要靠流动才能带走热量，塞得太满，风道一堵，靠里的东西就冷不透。
  我的做法是留出出风口前面那一拳的空间。说白了，冰箱冷不冷，看的不是功率，是空气能不能走得动。"

## 8. Process

Time budgets are guides for a 60–180 s script; if a phase blows its budget, ship the rough version and improve the
next one.

1. **Premise** (~10 min, no script yet): the one takeaway in ≤15 words; what the viewer wrongly believes; the
   mental tool they keep; why you find it interesting (informs the voice, not the script). If the takeaway won't
   fit in 15 words, the topic isn't ready.
2. **Structure** (~10 min): pick the format, list sections as headings with one-line takeaways, check they tell a
   story in order.
3. **Draft** (30–60 min): continuous prose, overshoot length (cutting is easier than padding), mark the insight
   paragraph and signpost it, hook last.
4. **Read-aloud pass** (~15 min, non-negotiable): performance voice, out loud. Tongue-trippers → break up;
   disguised bullets → connect; padding, doubled definitions, forward references, filler reassurance → cut;
   AI-tell words → replace.
5. **Tighten** (~15 min): cut every sentence without new information or voice; "could the paragraph open on its
   second sentence?" (often yes); a word-level pass against §3 and §6.
6. **Lint + self-check** (`scripts/lint_script.py`, then §10), then lock. Don't edit the script while recording.
   After lock: pronunciation drill.

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

## 10. Pre-lock self-check (every unchecked box → revise)

- [ ] Zero em-dashes
- [ ] Every sentence has a subject and a verb (no phrase fragments, no slide annotations)
- [ ] Hook ≤3 sentences (short) or ≤6 (mid-length), contains "you" and a specific number or year, no throat-clearing
- [ ] No trope openers ("OK quick thing", "today we'll…") and no generic closers ("follow for more", "hope that helps")
- [ ] Stance matches the persona: observational, not a consulted authority, no false modesty
- [ ] Exactly one paragraph is the insight, and it is signposted
- [ ] Closing uses pattern A / B / C / D; its last line is screenshot-worthy on its own
- [ ] No AI-tell vocabulary, meta-commentary, forward/backward references or filler reassurance
- [ ] Read aloud once with no stumbles
- [ ] Length fits the format (words ÷ `voice.en.wpm`, or 字 ÷ `voice.zh.cpm`) or the `--platform` sweet spot
