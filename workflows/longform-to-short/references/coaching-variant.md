# Variant: 1v1 / small-group coaching call → anonymised, host-only lecture

Use when the source is a coaching call or office hours and only the instructor's teaching should
be published (participant privacy). No dedicated scripts yet — these are the recipes that worked;
the main pipeline (keep list, pitch windows, subs, covers) still applies.

## Who is speaking
- Platform speaker labels are often wrong. Diarize instead: embed each whisper segment with
  `resemblyzer`, 2-cluster (agglomerative, cosine), host = the cluster with the longest total
  duration. Keep host segments only. Sanity-check the participant by CONTENT (questions, "I"
  statements about their own job search), never by any label.
- Participant questions you need to keep for context → `pitches.windows` (−3 semitones by default,
  duration preserved). Verify with `qa.py` (f0 should drop ~3 st; the host stays unchanged).

## Privacy is visual too
Meeting recordings leak identity three ways:
1. **Gallery view** — title bar shows names and avatar tiles. Detect by low detail: Laplacian
   variance < ~250 on a 480x270 gray frame → DROP the clip (`geometry.py` also marks these spans
   `crop: null`).
2. **Browser bookmark bar** — exposes work links, emails, usernames. Detect three light bands at the
   top; crop the top ~134 px (at 1080p) — `geometry.browser_header_px` handles the common case.
3. **Presenter name tag** — an overlay at the top or bottom of the share; crop ~44 px top on content
   frames, or `geometry.bottom_trim` for the bottom "<name>'s screen" label.

Always finish with `qa.py` mosaics at 1/15–1/30 s and look at every tile: zero names, avatars,
bookmark bars, email addresses.

## Filler / repeat tightening (word level, good for English)
- Drop filler words {um, uh, hmm, er, ah, …} and filler phrases ("give me a second", "let me see",
  "my bad"); collapse immediate 1- and 2-gram repeats.
- Build kept intervals from the remaining words, breaking whenever a word was dropped between two
  kept words (so the filler's TIME is excluded — merging on gap alone silently keeps it) or the
  pause is ≥ 0.6 s. Then 1.2–1.25×. Typical: 25–30% runtime saved before the speed factor.
- Feed the intervals as `cuts` (gaps between kept intervals) or build `keep.ranges` directly.

## Subtitles
- Same retime-through-timeline mapping; put accent-specific ASR mis-hearings in
  `persona.local.yaml → subtitles.term_fixes` (creator-wide) or `config.subtitles.term_fixes`
  (this video). Typical families: acronyms heard as other acronyms (LLM), product names heard as
  common words (a model name heard as a country, an assistant name heard as "cloud"), "prompt"
  heard as "problem", "chunk" heard as "trunk", "few-shot" heard as "field shot".
- For code / slides, burn with `burn.encoder: x264` (crf ~20) — crisper text than VideoToolbox.

## Pronunciation follow-up (optional)
List the technical terms the host mispronounced with IPA + a simple respelling; a shadowing
drill can be generated with a TTS drill tool.
