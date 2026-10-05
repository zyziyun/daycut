# preproduction — script writing + pronunciation drills

**Use when:** before anything is recorded: drafting or revising a spoken script for a short (60–180 s) or
mid-length (3–10 min) video, fixing a flat hook or a generic ending, or preparing the narrator to say the hard
words in a locked script. **Inputs:** a topic / notes / draft. **Outputs:** `SCRIPT.md` (locked, linted) and an
optional `pronunciation_drill.{m4a,wav,md}` shadowing pack. Downstream: `workflows/slides` (visuals),
`workflows/cover` (the hook doubles as cover text), `workflows/polish` (final export).

Generic craft lives in [`references/script_craft.md`](references/script_craft.md). The creator's own voice
(stance, preferred and banned phrases, insight signposts, pace, TTS voice) lives in persona `voice.*` / `tts.*`;
see [`examples/persona.voice.example.yaml`](examples/persona.voice.example.yaml). Read both before writing.

Run from the project folder; `$VSTUDIO` = repo root.

## A. Script

1. **Premise first** (no prose yet). Answer in one or two sentences each: the one takeaway (≤15 words), what the
   viewer wrongly believes now, the mental tool they keep, why the creator finds it interesting. If the takeaway
   doesn't fit in 15 words, stop and narrow the topic.
2. **Format + structure.** Pick short / long-short / mid (craft §1). List sections with a one-line takeaway each;
   check that the takeaways tell a story in order.
3. **Draft** in continuous spoken prose, in the persona voice (`voice.persona`, `voice.phrases_prefer`,
   `voice.rules`). Overshoot length. Mark the one insight paragraph and signpost it (`voice.signposts`).
   Write the hook **last** with the formula: you-statement → surprising claim → anchoring number.
4. **Read-aloud pass** (non-negotiable). Break tongue-trippers, connect disguised bullet lists, cut padding,
   doubled definitions, forward references.
5. **Lint:**
   ```bash
   python3 $VSTUDIO/workflows/preproduction/scripts/lint_script.py SCRIPT.md --format short
   ```
   Errors: em-dashes, parentheses (if the persona bans them), trope openers, generic CTAs, authority framing,
   AI-tell words, meta/navigation lines, emoji, `voice.phrases_avoid`. Warnings: sentences > 25 words, possible
   fragments, digits under 10, missing insight signpost, word count vs. format at `voice.wpm`.
   Lint is a floor, not the judge: still run the self-check below.
6. **Lock.** Hand the hook sentence to the cover headline and the first slide.

`SCRIPT.md` format that other workflows read: `## SECTION` headings, the spoken text as indented blocks,
optional `**Delivery:**` notes and `ZH:` translation lines (ignored by the linter). See
`examples/script.example.md` (synthetic).

### Self-check before lock
- [ ] Zero em-dashes; every sentence has a subject and a verb
- [ ] Hook ≤3 sentences (≤6 mid-length) with "you" and a concrete number or year; no throat-clearing
- [ ] Voice matches `voice.persona`; no banned openers, closers or `voice.phrases_avoid`
- [ ] Exactly one signposted insight paragraph that reframes the topic at a deeper layer
- [ ] Closing uses pattern A/B/C/D; last line is screenshot-worthy alone
- [ ] Word count fits the format; read aloud once with no stumbles

## B. Pronunciation drill (after the script is locked)

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
   Voice per engine from `persona.tts.<engine>_voice`, or `--voice`. Use the same voice as any TTS preview so the
   reference stays consistent.

## Notes
- mlx-audio Kokoro can crash on one specific sentence at one speed (`broadcast_shapes ... cannot be broadcast`,
  surfaced as "mlx_audio produced no wav"). Reword the sentence slightly or nudge `--normal` (0.85 → 0.86).
- The craft is written for English scripts. For 中文口播 keep the structural rules (hook formula, one insight,
  closing patterns, no em-dashes); sentence-length and wpm targets don't transfer (count characters, ~4–5 字/s).
- Don't run the drill on a draft: words change, and the narrator ends up drilling sentences they won't say.
