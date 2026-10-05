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

## Wave B
Changes:
- `lint_script.py`: per-language voice profiles. `--lang auto|en|zh` (auto = zh when CJK ≥30% of letters) picks
  `voice.<lang>.*` key by key → flat legacy `voice.*` → built-in default (flat `wpm` is not inherited by zh). English
  path is the old code unchanged. New zh rule set: 破折号 (a `——` run counts once), 括号 (if `rules` mention
  parenthes/括号), generic 口播 trope openers / CTAs / authority / AI-tell / meta lists (家人们, 今天给大家分享, 点赞关注,
  一键三连, 很多人不知道, 赋能, 这期视频…), emoji, `phrases_avoid`, signposts, sentence > 40 字 warn, length in 字
  (CJK chars + 1 per latin word) at `voice.zh.cpm`. English-only heuristics (fragments, digits < 10, avg words) skipped.
- `--platform NAME[:orientation]`: target = `profile.length.sweet` × pace (en words at `voice.en.wpm`, zh 字 at
  `voice.zh.cpm`); `platform.check_length` → ERROR over the hard max, warn outside the sweet spot / under min.
  `--platform` wins over `--format` (note printed); `--format` default is still `short` when no platform.
- `make_drill.py`: voice = `--voice` > `voice.en.tts.<engine>_voice` > `tts.<engine>_voice` (lib) > engine default.
- `examples/persona.voice.example.yaml` rewritten as `voice: {en: {...}, zh: {...}}` + top-level `tts:`; WORKFLOW.md
  gained "Voice schema" (key table) and "Platforms"; `script_craft.md` gained §7 worked revisions (hook / paragraph /
  closing + one zh 口播, all fresh synthetic topics) and zh length targets in §1.
Tests (temp files in /tmp/preprod-waveb, not committed):
- Default output identical to `git show HEAD:…/lint_script.py` (diff empty) on `examples/script.example.md` with no
  flags, `--format mid`, `--format long-short --strict`, on a synthetic bad English script, and with a flat-only
  persona override (`VSTUDIO_PERSONA`, `voice.en/zh: null`, flat `wpm`/`rules`/`phrases_avoid`/`signposts`).
- Language selection: override with `voice.en.phrases_avoid: ["a cache"]`, `voice.zh.phrases_avoid: ["缓存"]`; an EN
  script containing both hits only 'a cache', a synthetic zh script containing both hits only '缓存'.
- Platforms: zh `--platform douyin` → "151 字 ≈ 34s … target 68-270 字 … sweet spot 15-60s" clean; en
  `--platform youtube` → target 1155-3300 words + sweet-spot warning; 4× example on `youtube-shorts` → ERROR over 180 s.
- zh trope script → dash/opener/CTA/AI-tell/emoji/40 字 hits; the example persona YAML lints the example script clean.
- py_compile, `--help` (both scripts), `make_drill --dry-run`, `pytest tests -q` 104 passed.
New persona keys: `voice.en.{persona,domain,wpm,rules,phrases_prefer,phrases_avoid,signposts}`,
`voice.en.tts.<engine>_voice`, `voice.zh.{persona,domain,cpm,wpm (alias of cpm, 字/min),rules,phrases_prefer,
phrases_avoid,signposts}`, `voice.zh.tts.<engine>_voice` (documented only; nothing reads it yet).
Lib requests:
- `vstudio.tts.synth(..., lang=)` / `default_voice(engine, lang)` resolving `voice.<lang>.tts.<engine>_voice` before
  `tts.<engine>_voice`, so zh previews pick a zh voice without each workflow re-implementing the lookup.
- A shared `vstudio.text` helper for CJK detection / spoken-length units (`detect_lang`, `zh_units` in
  `lint_script.py`; `platform._has_cjk` and `config.xhs_len` are close cousins).
- `persona.example.yaml` `voice:` could adopt the `en:`/`zh:` sub-blocks (flat keys keep working).
