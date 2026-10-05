# PORT_NOTES — preproduction

## Sources
- `content-skills/skills/script-voice/SKILL.md` (no code).
- `content-skills/skills/pronunciation-drill/SKILL.md` + its implementation `content-skills/scripts/make_drill.py`.

## What changed / dropped
- **script-voice split in two.** Generic craft (format/length table, hook formula, body rules, the mandatory
  insight + reframe patterns, closing patterns A–D, anti-pattern table, 6-phase process, templates) →
  `references/script_craft.md` + WORKFLOW.md. Creator-specific voice (learner-educator stance, "What I find
  interesting"/"the lens I keep coming back to" phrasing, banned self-positioning lines, no false modesty,
  AI/tech domain, 165 wpm) → persona `voice.*` keys, shown in `examples/persona.voice.example.yaml`.
- All worked examples in script-voice were the creator's real script lines (ChatGPT / Transformer / context / MCP
  hooks and closings) → replaced with synthetic examples. The "Known anti-patterns from real revisions" table is
  kept in generalized form.
- New `scripts/lint_script.py`: mechanizes the checkable rules (em-dashes, parentheses, tropes, CTAs, authority
  framing, AI-tell words, meta lines, emoji, long sentences, fragments, digits < 10, signpost, word count/format).
- `make_drill.py`: hard-coded WORDS list (real script sentences) → JSON/TXT input file; hard-coded Desktop outputs
  and `/tmp/drill_clips` → `-o` stem + temp dir; added `--script` membership check (the source's constraint #1),
  the markdown reference card (documented in source but never generated), **loudnorm** (documented as required but
  the source skipped it; now two-pass to persona loudness), `--dry-run`, `--max-words`, tunable speeds/gaps.
- TTS backends: Kokoro via mlx-audio (Apple Silicon, as source) + **edge-tts** and **OpenAI TTS** fallbacks for
  non-Mac; all clips resampled to 24 kHz mono PCM so concat is engine-agnostic.
- Dropped: the hard-coded `.tts-env` venv activation path.
- Verified: lint on the synthetic example (clean); drill `--dry-run`; a real 3-word Kokoro run
  (46 s, -14.8 LUFS / -1.2 dBTP). edge/openai paths not executed (network/API key).

## Capabilities
tts, loudness, other (script writing craft, script lint, pronunciation drill).

## Duplicates for phase 2 (`lib/vstudio`)
- `scripts/make_drill.py:tts` — TTS wrapper (kokoro / edge / openai); the explainer workflow has its own OpenAI
  narration. Candidate `vstudio.tts`.
- `scripts/make_drill.py:main` two-pass loudnorm block — same as `workflows/polish/scripts/polish.py:measure`.
- `scripts/make_drill.py:silence`/concat — audio assembly helpers.

## Persona keys used
- existing: `voice.persona`, `voice.rules`, `audio.loudness_lufs`.
- **new** (all read with safe defaults): `voice.wpm` (165), `voice.phrases_avoid` ([]), `voice.signposts` ([]),
  `voice.phrases_prefer` and `voice.domain` and `voice.language` (doc/LLM-facing only),
  `tts.kokoro_voice` (af_heart), `tts.edge_voice` (en-US-AriaNeural), `tts.openai_voice` (alloy).

## Platform-specific
- Kokoro path needs Apple Silicon + mlx-audio; `--engine auto` falls back to edge-tts, then OpenAI.
- Lint heuristics are English-oriented (word counts, fragments); CJK characters count as half a word.

## Phase 2b rewire
Swaps (old → new): `tts`/`pick_engine`/`to_wav`/`DEFAULT_VOICE` → `vstudio.tts.synth` + `tts.pick_engine` (kokoro / edge /
openai all kept; voice from `--voice`, else persona `tts.<engine>_voice`, else lib default); `silence` + ffmpeg concat
→ in-memory assembly with `audio.read_wav` / `audio.write_wav` (numpy zero gaps); inline two-pass loudnorm →
`audio.loudnorm_2pass` (once to .wav, once to .m4a at 96k). `lint_script.py` untouched (no lib equivalent).
Behaviour changes: clips are 48 kHz (was 24 kHz) and cached in `$VSTUDIO_CACHE/tts` (re-runs are free); the `.wav`
is now loudness-normalised too (was the raw concat) and both outputs are 48 kHz stereo (m4a was 44.1 kHz mono);
openai default is now `gpt-4o-mini-tts` / voice `cedar` via plain HTTPS (was `tts-1` / `alloy` via the `openai`
package; `--model tts-1 --voice alloy` restores it).
Tests: 3-word Kokoro drill (example words; mlx-audio present) → 45.2 s, wav −14.1 LUFS / −1.5 dBTP, m4a −14.2 LUFS /
−1.1 dBTP (phase 1: 46 s, −14.8 LUFS); `--dry-run` on the 5-word example; lint on the example script (clean);
py_compile + `--help`; `pytest tests` 34 passed. edge/openai not executed (network / key).
Found: Kokoro (mlx-audio) crashes on some sentence+speed combos ("broadcast_shapes ... cannot be broadcast", e.g.
"Inference is the part you pay for." at 0.85) — upstream bug, documented in WORKFLOW.md Notes.
Lib requests: `tts._kokoro` should include the mlx_audio stdout/stderr tail in "mlx_audio produced no wav" (the real
error is printed to stdout with exit 0); a public `tts.default_voice(engine)` for logging the resolved voice.
