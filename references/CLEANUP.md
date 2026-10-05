# Speech cleanup: 气口 / filler / 重复 / 口误 (`vstudio.cleanup`)

One shared tool for every workflow that keeps original speech: talking heads, long recordings, calls,
promo recuts, vlog and photo-story clips with speech. It finds what to remove, lets the creator decide
the uncertain ones, cuts word-safe and frame-exact, and checks the result by re-transcribing it.

```
analyze  ->  cleanup.json (EDL) + cleanup_review.md   ->  creator replies "确认 3,5,9 / 保留 7"
apply    ->  <stem>.clean.<tag>.mp4 + <stem>.clean.<tag>.cleanup.json (TimeMap, kept words)
verify   ->  re-ASR, lost content words -> exit 1
```

## What it detects

Every edit has `t0, t1, kind, text, confidence, action (auto | confirm | keep), reason`, plus the context
before / after it.

| kind | 中文 | What | Default |
|---|---|---|---|
| `pause` | 气口 | silence longer than `pause_min`, **squeezed** to `clamp(gap*pause_ratio, gap_min, gap_max)` (at least `gap_sentence` after a sentence end), never deleted outright | auto |
| `breath` | 气口+换气 | a pause containing a breath (soft, noise-like run); `gentle` keeps the breath, the others remove it | auto |
| `lead` / `tail` | 开头/结尾静音 | silence before the first / after the last word of a range, trimmed to `lead` / `tail` | auto |
| `filler` | 口头禅 | hesitations 嗯 呃 额 um uh erm → high confidence. 啊 哦 and semantic fillers 那个 这个 就是 然后 对吧 / like, you know, I mean, so, well only when the audio isolates them (pause before / after, drawn out). Real-word uses stay: 「那个问题」, 「我就是喜欢」, "I like it", "you know what", "what I mean" → `keep`; sentence-final particles (好啊) are not flagged at all | auto / confirm / keep |
| `filler-merged` | 粘连口头禅 | whisper glued a filler onto the next word (one over-long word with an energy dip then a rise): cut up to the rise, the word stays | confirm |
| `stammer` | 结巴 | 我我们, we we, the the, clipped starts (pro- problem): the full / last copy is kept | auto / confirm |
| `repeat` | 重复 | n-gram said twice back to back (像这个像这个): the last copy is kept. Deliberate doubling (对对, very very, 慢慢) → keep | auto / keep |
| `restart` | 说一半重来 | a phrase abandoned and started again (我们明天去 … 我们明天要讲): the abandoned part goes | confirm |
| `retake` | 重录句 | a whole sentence said again within `retake_window` s: the earlier take goes (lower confidence when the later take is much shorter: maybe keep the first) | confirm |
| `asr-noise` | 识别噪声 | text whisper invented over silence / music (`asr.drop_hallucinations`) | confirm |

`retake`, `filler-merged` and `asr-noise` are never auto (`never_auto`). Without audio everything is
detected from whisper timing at lower confidence and pauses are never auto.

## Profiles

| profile | pauses squeezed from | kept gap | auto from confidence | breaths |
|---|---|---|---|---|
| `gentle` | 0.80 s | 0.35-0.70 s | 0.92 | kept |
| `standard` (default) | 0.45 s | 0.18-0.40 s (0.30 after a sentence) | 0.85 | removed |
| `tight` | 0.25 s | 0.08-0.20 s | 0.75 | removed |

Persona overrides (`persona.local.yaml`), all optional - unknown keys in `overrides=` raise:

```yaml
cleanup:
  profile: standard            # default profile
  crossfade: 0.02              # 10-30 ms equal-power crossfade at every join
  pad: 0.035                   # silence left beside a kept word at a word-edit edge
  fillers_extra: [其实, 对不对]  # your own 口头禅 (treated like 那个 / 就是)
  never_cut: [然后]             # tokens never flagged as filler / repeat
  never_auto: [retake, filler-merged, asr-noise]
  profiles:
    tight: {auto_min: 0.8}
```

## The review / approve loop

1. `analyze` writes `cleanup.json` and `cleanup_review.md`. The sheet lists 待确认 CONFIRM first, then
   自动删 AUTO, 气口 AUTO, 保留 KEEP; each row is numbered with `…before【removed】after…` and the reason.
2. The creator listens to the confirm items and replies, e.g. `确认 3,5,9 / 保留 7`, `删 2-4 不删 6`,
   `全部确认`, `approve 3,5 keep 7`. 确认 = also cut these; 保留 = do not cut these (works on auto items too).
3. `apply --reply "确认 3,5,9 / 保留 7"` (or `--approve 3,5,9 --keep 7`, `--all-confirm`, extra editor cuts
   `--cut 12.3-12.9`).
4. `verify OUTPUT` re-transcribes the cut and compares it (normalised, fillers ignored) with the words that
   should remain. A lost content word fails loudly with its source and output time: keep the edit that
   covers it (`--keep N`) and re-apply. Leftover hesitations / immediate repeats are listed as warnings.

Safety rules built in:
- **Word-safe edges**: a word edit runs from the silence after the previous kept word to the silence
  before the next one (quiet-run edges ± `pad`, else the quietest 10 ms frame between them) - never
  inside a kept word, even though whisper word ends run early.
- **Sample-exact A/V**: kept spans snap OUTWARD to the frame grid; video is cut frame-exact, audio is
  built from PCM at 48 kHz to exactly the same length with an equal-power crossfade at each join and
  encoded once (no AAC concat), so drift is impossible.
- **Idempotent, versioned**: apply never rewrites the EDL; the output name carries a hash of the
  decisions, so re-applying the same decisions is a no-op and different decisions never overwrite each
  other. `analyze` writes `cleanup.2.json` instead of overwriting an EDL the creator may have edited
  (`--force` to overwrite). apply refuses a source whose duration differs from the EDL's (never cut an
  already-cut file).

## CLI

```bash
python -m vstudio.cleanup analyze talk.mp4 [--transcript talk.asr.json] [--ranges 12.5-80,1:40-2:10] \
       [--profile gentle|standard|tight] [--lang zh] [--prompt "terms"] [--out cleanup.json] [--force]
python -m vstudio.cleanup review cleanup.json
python -m vstudio.cleanup apply cleanup.json --reply "确认 3,5,9 / 保留 7"   # or --approve/--keep/--all-confirm/--cut
python -m vstudio.cleanup verify talk.clean.<tag>.mp4 [--transcript got.json]   # exit 1 = lost words
```

Audio-only sources (`.wav`, `.m4a`) work the same; the output is `.wav`.

## Python API

```python
from vstudio import cleanup
edl = cleanup.analyze("talk.mp4", transcript="talk.asr.json", profile="standard")
print(cleanup.review_sheet(edl))
res = cleanup.apply(edl["_path"], reply="确认 3,5,9 / 保留 7")   # dict(out, keep, timemap, applied, tag, ...)
rep = cleanup.verify(res["out"])                                # dict(ok, missing, leftovers)
```

In memory (no files, no render - the workflow keeps its own assembly):

| function | use |
|---|---|
| `load_words(tr)` | any transcript shape (vstudio.asr dict, whisper segments, `{w,t,te}`, `{word,start,end}`, tuples) → word dicts |
| `energy_of(audio, words, ranges)` | decode + calibrate the audio once; pass as `energy=` / `en` below |
| `detect(words, audio=, ranges=, profile=, id_offset=)` | the edits (same dicts as the EDL); several ranges share one numbering, ids start at `id_offset + 1` |
| `clean(words, audio, lo, hi, approve=, keep=, extra=, ranges=, id_offset=)` | one window (`lo, hi`) or several (`ranges=[...]`, one numbering): `edits`, `keep` (replaces `cut.split_window`), `cuts` (replaces `cut.find_cuts`; applied edits + snapped editor cuts), `extra` (the snapped editor cuts), `timemap` |
| `keep_segments(edits, ranges, approve, keep, all_confirm, extra)`, `applied_ids`, `as_cuts` | decisions → kept spans / cut list |
| `timemap(keep)`, `remap_words(words, tm)` | `cut.TimeMap` source → cleaned seconds for captions, overlays, cues |
| `write_sidecar(out, source, keep, words, language, fps=, **fields)` | the `<out stem>.cleanup.json` that `verify` reads, for a cut the workflow rendered itself (a retouched body, a sentence drop): kept spans in `source` seconds + the source-timeline words → `expected` / remapped `words`; `tag` = hash of (source, keep, fields) |
| `word_limits(words, t0, t1)` | how far a range may grow before it reaches a neighbour word |
| `safe_edge(words, t, en, side="start"/"end")` | move one edge out of a word (word clamp). `"end"` = keep up to `t`: grows over the word it cuts short, never over a word starting at or after `t` |
| `snap_range(words, t0, t1, en)` | hand-written keep range → word-safe edges |
| `snap_cut(words, en, a, b)`, `snap_cuts(words, en, cuts, ranges)` | manual (editor) cut → word-safe `(a, b)` (the words whose midpoint is inside go; never into the previous word's sounding end or the next kept word's onset) / a list → `[[a, b, "edit: why"]]`, only those touching `ranges` |
| `norm_ranges(ranges)`, `join_words(words)`, `saved_seconds(edits, ranges)` | sorted + merged spans (`[]` when empty); transcript-style text of words (no space next to CJK); seconds actually removed = the merged union of the edits (the review sheet's 省 Xs) |
| `word_tail(en, t, limit)`, `extend_end(words, en, h0, h1, fade, speed)` | a word's real sounding end; extend a hook / clip end over the last word's tail plus its fade, never into the next word (the fade shrinks instead) |
| `parse_reply(text)`, `parse_ranges(text)`, `content_check(expected, got)` | creator reply, `12.5-80,1:40-2:10`, normalised lost-word diff |

### Several clips / windows on one review sheet

Edit ids are what the creator answers with, so one sheet needs one numbering:

```python
edls, off = {}, 0
for c in clips:                                   # several source files: offset each EDL
    edls[c] = cleanup.analyze(f"clip{c}.mp4", ranges=rg[c], out=f"cleanup.c{c}.json", id_offset=off)
    off += len(edls[c]["edits"])
res = cleanup.clean(words, None, ranges=[(12, 40), (55, 80)], energy=en)   # several windows of ONE source
res = cleanup.clean(words, None, a, b, energy=en, id_offset=len(sheet))      # or window by window
```

### A cut rendered by the workflow itself

When the workflow cuts a *derived* file (e.g. the retouched body) with its own renderer instead of
`apply`, it still gets `verify`: `write_sidecar(out, source=parent, keep=spans_in_parent_seconds,
words=parent_timeline_words, language, fps=, applied=..., reply=...)`, then `verify(out)`.

## How workflows use it

- **talkinghead**: per raw clip `analyze(..., id_offset=)` (one sheet for all clips) → creator confirms →
  the body is cut by the workflow (`strict_pass` / `drop_pass`) and each cut writes `write_sidecar` →
  `verify`; the sidecar TimeMap and remapped words drive captions / overlays.
- **longform-to-short**: per sub-range `clean(..., id_offset=len(episode edits))`, one sheet per episode;
  hook / clip ends through `extend_end`, hand-written ranges through `snap_range`.
- **call-clips**: per window `clean(words, audio, lo, hi, extra=editor cuts)` (or `analyze --ranges`
  + a reviewed reply); editor cuts through `snap_cut(s)`.
- **promo-recut** (`norm_ranges` / `join_words` for its KEEP spans and draft subtitles), **vlog** / **photo-story** clips with speech: `analyze --ranges` on the speech clips,
  `apply`, then use the cleaned clip as the source of the edit.

Tests: `python3 -m pytest tests/test_cleanup.py -q` (synthetic tone-burst speech, fake ASR, no network).
