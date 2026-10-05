# preproduction — script writing + pronunciation drills

**Use when:** before anything is recorded: drafting or revising a spoken script for a short (60–180 s) or
mid-length (3–10 min) video, fixing a flat hook or a generic ending, or preparing the narrator to say the hard
words in a locked script. **Inputs:** a topic / notes / draft. **Outputs:** `SCRIPT.md` (locked, linted) and an
optional `pronunciation_drill.{m4a,wav,md}` shadowing pack. Downstream: `workflows/slides` (visuals),
`workflows/cover` (the hook doubles as cover text), `workflows/polish` (final export).

Generic craft lives in [`references/script_craft.md`](references/script_craft.md). The creator's own voice
(stance, preferred and banned phrases, insight signposts, pace, TTS voice) lives in persona `voice.en.*` (English
scripts) / `voice.zh.*` (中文口播) and `tts.*`; see the [Voice schema](#voice-schema) below and
[`examples/persona.voice.example.yaml`](examples/persona.voice.example.yaml). Read both before writing.

Run from the project folder; `$VSTUDIO` = repo root.

## A. Script

1. **Premise first** (no prose yet). Answer in one or two sentences each: the one takeaway (≤15 words), what the
   viewer wrongly believes now, the mental tool they keep, why the creator finds it interesting. If the takeaway
   doesn't fit in 15 words, stop and narrow the topic.
2. **Format + structure.** Pick short / long-short / mid (craft §1). List sections with a one-line takeaway each;
   check that the takeaways tell a story in order.
3. **Draft** in continuous spoken prose, in the persona voice for the script's language (`voice.<lang>.persona`,
   `.phrases_prefer`, `.rules`; see Voice schema). Overshoot length. Mark the one insight paragraph and signpost it (`voice.<lang>.signposts`).
   Write the hook **last** with the formula: you-statement → surprising claim → anchoring number.
4. **Read-aloud pass** (non-negotiable). Break tongue-trippers, connect disguised bullet lists, cut padding,
   doubled definitions, forward references.
5. **Lint:**
   ```bash
   python3 $VSTUDIO/workflows/preproduction/scripts/lint_script.py SCRIPT.md --format short
   python3 $VSTUDIO/workflows/preproduction/scripts/lint_script.py SCRIPT.md --platform douyin   # see Platforms
   ```
   The language is auto-detected (`--lang auto|en|zh`; zh when CJK is ≥30% of the letters) and picks the
   `voice.<lang>` profile and rule set.
   English errors: em-dashes, parentheses (if the persona bans them), trope openers, generic CTAs, authority
   framing, AI-tell words, meta/navigation lines, self-narration about the medium ("in this video", "next slide"),
   filler reassurance ("don't worry if…"), emoji, `voice.en.phrases_avoid`. Warnings: padding ("so what I want to
   say is"), sentences > 25 words, possible fragments, digits under 10, missing insight signpost, word count vs.
   target at `voice.en.wpm`.
   中文 errors: 破折号, 括号 (if banned), 口播套路开头 (家人们, 今天给大家分享, 话不多说…), 求赞求关注 CTA in the closing
   (点赞关注, 一键三连, 下期见…), authority framing (很多人不知道…), AI-tell words (赋能, 闭环, 值得注意的是…), meta
   lines (这期视频, 后面会讲…), filler reassurance (别担心, 听起来有点复杂…), emoji, `voice.zh.phrases_avoid`. Warnings: sentence > 40 字, missing signpost,
   字数 vs. target at `voice.zh.cpm`. The English-only heuristics (fragments, digits under 10, average words per
   sentence) are skipped for zh.
   Lint is a floor, not the judge: still run the self-check below.
6. **Lock.** Hand the hook sentence to the cover headline and the first slide. From here the script is frozen:
   don't rewrite it during recording (that is how a two-hour session becomes five). End-to-end recipe:
   [`references/SOP_SHORT_VIDEO.md`](../../references/SOP_SHORT_VIDEO.md).

Time budgets per phase, the full pre-lock checklist and worked before/after revisions (hook ladder, paragraph,
closings A/B/C, 中文口播) are in `references/script_craft.md` §7, §8, §10.

`SCRIPT.md` format that other workflows read: `## SECTION` headings, the spoken text as indented blocks,
optional `**Delivery:**` notes and `ZH:` translation lines (ignored by the linter). See
`examples/script.example.md` (synthetic).

### Self-check before lock
- [ ] Zero em-dashes; every sentence has a subject and a verb
- [ ] Hook ≤3 sentences (≤6 mid-length) with "you" and a concrete number or year; no throat-clearing
- [ ] Voice matches `voice.<lang>.persona`; no banned openers, closers or `voice.<lang>.phrases_avoid`
- [ ] Not a consulted authority, no false modesty
- [ ] Exactly one signposted insight paragraph that reframes the topic at a deeper layer
- [ ] Closing uses pattern A/B/C/D; last line is screenshot-worthy alone
- [ ] No AI-tell words, meta/navigation lines or filler reassurance (lint clean)
- [ ] Word count fits the format; read aloud once with no stumbles

## Voice schema

One `voice:` block in `persona.local.yaml`, with a sub-profile per script language. `lint_script.py` resolves each
key as `voice.<lang>.<key>` → flat legacy `voice.<key>` → default, so a persona with only the flat keys lints exactly
as before (exception: the flat `wpm` is English words/min and is not inherited by zh). Full example:
[`examples/persona.voice.example.yaml`](examples/persona.voice.example.yaml).

| Key (under `voice.en` / `voice.zh`; flat `voice.*` = legacy fallback) | Default | Read by |
|---|---|---|
| `persona` | (none) | you / the LLM when drafting (stance: en = curious learner-educator, zh = confident practitioner) |
| `domain` | (none) | LLM-facing only |
| `language` (flat legacy only) | `en` | doc only; the sub-block name now carries the language |
| `en.wpm` (flat `wpm`) | 165 words/min | lint_script.py: seconds estimate, length target |
| `zh.cpm` (or `zh.wpm`, read as 字/min) | 270 字/min (4.5 字/s) | lint_script.py: seconds estimate, length target |
| `rules` | [] | lint_script.py: "parenthes" / "括号" in a rule turns the parentheses check on; rest LLM-facing |
| `phrases_prefer` | [] | LLM-facing only |
| `phrases_avoid` | [] | lint_script.py: ERROR on each hit (on top of the built-in generic en / zh trope lists) |
| `signposts` | [] | lint_script.py: counts as the insight signpost (plus built-in generic ones) |
| `en.tts.<engine>_voice` | → `tts.<engine>_voice` | make_drill.py (drills are English) |
| `zh.tts.<engine>_voice` | (none) | documented for zh TTS previews; no preproduction tool reads it yet |
| top-level `tts.<engine>_voice` (`kokoro`, `edge`, `openai`) | af_heart / en-US-AriaNeural / cedar | `vstudio.tts` (make_drill.py, previews) |

Tests or one-off overrides: point `VSTUDIO_PERSONA=/path/override.yaml` at a YAML file; it is merged over the persona.

## Platforms

`lint_script.py --platform <name>[:orientation]` (`xiaohongshu`, `douyin`, `tiktok`, `youtube`, `youtube-shorts`,
`bilibili`; aliases like `xhs`, `抖音`, `shorts` work) turns the length check into a platform check:

- target range = `vstudio.platform.profile(name).length.sweet` (seconds) × pace: `voice.en.wpm` words/min for English,
  `voice.zh.cpm` 字/min for Chinese. E.g. 抖音 sweet 15–60 s × 270 字/min → 68–270 字; YouTube 420–1200 s × 165 wpm →
  1155–3300 words.
- the estimated seconds go through `platform.check_length`: over the hard max → **ERROR**; outside the sweet spot or
  under the minimum → warning. Override sweet/max per platform in persona `platforms.<name>.length`.
- precedence: `--platform` wins; `--format` is only used for length when no `--platform` is given (a note is
  printed if you pass both). Without either, the classic `short` target applies, so existing runs are unchanged.

```bash
python3 $VSTUDIO/workflows/preproduction/scripts/lint_script.py SCRIPT.md --platform youtube-shorts
python3 $VSTUDIO/workflows/preproduction/scripts/lint_script.py 口播.md --platform douyin        # zh auto-detected
python3 $VSTUDIO/workflows/preproduction/scripts/lint_script.py SCRIPT.md --platform xhs --lang en
```
Nothing else in preproduction depends on the platform (no canvas, captions or audio here); the rendered video's
per-platform export happens downstream (`python -m vstudio.export`).

## B. Pronunciation drill (after the script is locked)

For a narrator who wants to practise the hard words of *this* script before recording (non-native accent,
tricky stress, names and jargon). Not a general pronunciation course: words that aren't in the script add nothing,
and more than ~12 words makes the drill too long; split it into two runs instead. The drill audio is a practice
file only; it never goes into the video.

1. **Pick 5–10 words** (8 is the sweet spot, the script refuses >12): read the script aloud, mark every stumble or
   unclear stress, prioritise by frequency in the script > visibility > pitfall risk. Every word must be in the
   locked script; drills map to what is about to be recorded, not general vocabulary.
2. **Write the list** as JSON (`word, sentence, ipa, pitfall, bad, good`) or TXT (`word | sentence | ipa | pitfall`):
   `cp $VSTUDIO/workflows/preproduction/examples/drill_words.example.json work/drill_words.json`
3. **Generate:**
   ```bash
   python3 $VSTUDIO/workflows/preproduction/scripts/make_drill.py work/drill_words.json \
       -o work/pronunciation_drill --script SCRIPT.md
   ```
   Per word: slow word (0.65×) → 1.2 s → slow word → 1.2 s → script sentence (0.85×) → 2.2 s; spoken intro first.
   Output `pronunciation_drill.wav` and `.m4a` (both two-pass loudnorm to `persona.audio.loudness_lufs`, 48 kHz
   stereo; the m4a is AAC 96k, AirPods-ready), and `.md` reference card (IPA, pitfall, BAD/GOOD, source sentence; words missing from the
   script are flagged). `--dry-run` writes only the card.
   Length ≈ 6 + n × 9.6 s (real runs land a bit longer with natural pacing).
4. **TTS engine** (`--engine auto` picks the first available):
   - `kokoro` — Kokoro-82M via `mlx-audio` on Apple Silicon (`pip install mlx-audio`), local, default voice `af_heart`.
   - `edge` — `pip install edge-tts`; any OS, free, needs network; default `en-US-AriaNeural`.
   - `openai` — `OPENAI_API_KEY`; any OS; `gpt-4o-mini-tts` with `speed` (`--model tts-1` for the old model);
     default voice `cedar`.
   All engines go through `vstudio.tts.synth`: clips are cached in `$VSTUDIO_CACHE/tts/`, so re-running a drill
   after editing one sentence only synthesises that sentence.
   Voice per engine: `--voice`, else persona `voice.en.tts.<engine>_voice` (drills are English), else
   `tts.<engine>_voice`, else the engine default. Use the same voice as any TTS preview so the
   reference stays consistent.

### Drill self-check
- [ ] Every word appears in the locked script (`--script` flags the ones that don't)
- [ ] 5–10 words; each has IPA, a one-line pitfall and the source sentence (BAD/GOOD when the mistake is typical)
- [ ] Audio loudness-normalised (the script does this; check the printed LUFS)
- [ ] `.m4a` well under ~1 MB per minute (larger usually means a wrong sample rate or bitrate)
- [ ] The `.md` card sits next to the audio; practise 2–3 times before recording

## Notes
- mlx-audio Kokoro can crash on one specific sentence at one speed (`broadcast_shapes ... cannot be broadcast`,
  surfaced as "mlx_audio produced no wav"). Reword the sentence slightly or nudge `--normal` (0.85 → 0.86).
- The craft is written for English scripts. For 中文口播 keep the structural rules (hook formula, one insight,
  closing patterns, no em-dashes); the linter switches to character counts (`voice.zh.cpm`, default 270 字/min ≈
  4.5 字/s) and a 40 字 sentence limit.
- Don't run the drill on a draft: words change, and the narrator ends up drilling sentences they won't say.
