# SOP: one short talking-head video, topic to published post

An end-to-end recipe that chains the workflows for the most common job: a 60–180 s vertical talking-head short with
slides, for 小红书 / 抖音 / TikTok / YouTube Shorts / Reels. Expect ~4 hours the first time and ~2 hours once the
slides and cover are template swaps (usually by the third video).

`$VSTUDIO` = repo root. Run everything from the video's project folder, e.g. `<videos>/short_NNN_<topic-slug>/`.

## Objective

One topic sentence in, and out:
1. a locked script (~60–120 s of speech), linted
2. a pronunciation drill for the narrator (optional, recommended for non-native speakers)
3. 10–15 square slides, ≤3 of them animated
4. a cleaned, edited talking-head video with the slides in a split layout and captions
5. a cover, then a polished master (loudness, optional speed-up, delivery tags) plus one file per platform
6. post copy per platform, and the post live on at least two platforms

## Constraints

- **One video per session.** Don't batch-produce; each video gets full attention.
- **Lock the script before recording.** Rewriting during the recording session is how 4 hours become 8.
- **Production friction is the enemy.** If a phase blows its budget, ship the rough version and improve the next
  one. Don't perfect.
- **Creative work when fresh.** Visual and editing judgement made late at night looks worse the next morning, and
  you can't tell at the time. Leave taste-critical steps (hooks, cover, cuts) for a rested session.
- **The creator decides taste-critical choices** (hook, which words to cut, cover pattern, speed); the tools propose.

## Phase 1: topic and premise (15 min)

Write the topic in one sentence, then answer in one or two sentences each:
- What is the ONE thing the viewer should walk away knowing?
- What does the viewer already (wrongly) believe about it?
- What concrete action or mental tool should they keep?
- Why does the creator find it interesting? (Informs the voice, not the script.)

**Check:** the first answer fits in 15 words. If not, the topic isn't ready; pick another.

## Phase 2: draft the script (45 min)

`workflows/preproduction` (part A) and `workflows/preproduction/references/script_craft.md`.
- Structure: hook (3 sentences) → walk-through → the one insight (signposted) → closing pattern A–D.
- Continuous spoken prose; no fragments, no em-dashes.
- Length: ~165–250 words for 60–90 s, ~250–330 for 90–120 s at 165 wpm (中文: count 字 at `voice.zh.cpm`).
- Write the hook **last**: you can only hook well once you know what you are hooking into.

## Phase 3: read-aloud pass and lint (15 min)

Read the whole script aloud in performance voice. Fix tongue-trippers, disguised bullet lists, AI-tell words,
doubled definitions, forward references, filler reassurance. Then:
```bash
python3 $VSTUDIO/workflows/preproduction/scripts/lint_script.py SCRIPT.md --platform youtube-shorts --strict   # or douyin, xiaohongshu
```
**Check:** lint has no errors and the self-check in `script_craft.md` §10 is all ticked. Lock `SCRIPT.md`.

## Phase 4: pronunciation drill (15 min, optional)

`workflows/preproduction` (part B). Mark every word that trips the narrator, cut to ~8 (10 max), write
`work/drill_words.json`, then:
```bash
python3 $VSTUDIO/workflows/preproduction/scripts/make_drill.py work/drill_words.json -o work/pronunciation_drill --script SCRIPT.md
```
**Check:** every word is in the script; practise the drill 2–3 times before recording.

## Phase 5: slides (60 min)

`workflows/slides`.
1. Plan breakpoints: one slide per 6–10 s of narration (a 90 s short ≈ 10–14 slides). Slide 01 is the hook.
2. `cp $VSTUDIO/workflows/slides/templates/slides_vertical.template.html work/slides.html`, swap content per slide.
3. Preview in a browser; check every slide fits 1080×1080, nothing overflows, diagrams hold their geometry.
4. `python3 $VSTUDIO/workflows/slides/scripts/render_slides.py work/slides.html work/slides/`
5. For the 2–3 diagrams where motion is the explanation:
   `python3 $VSTUDIO/workflows/slides/scripts/record_slides.py work/slides.html work/slides/ 06_bars:3.4`

## Phase 6: record (45 min)

Vertical 9:16, face and shoulders framed so a slide can sit above or beside the speaker. One continuous raw take
if possible; restart a sentence rather than stopping the recording (the cleanup step removes restarts). Keep the
first second free of anything important (it becomes the cover). Record in a quiet room; loudness is fixed later,
noise is not.

## Phase 7: clean up the recording (15–30 min)

Remove 气口 (long pauses), fillers (嗯 / 呃 / um / uh), stutter repeats and restarts with the shared cleanup tool:
```bash
python -m vstudio.cleanup --help        # see the options; run it on the raw take
```
Only high-confidence cuts are automatic; the creator confirms everything else (semantic fillers such as 就是 /
那个 / like are often real words). Re-transcribe the cleaned file and check no content word was lost.
On the `workflows/talkinghead` V track the same job is built in (cut pass 1 + `strict_pass.py` with AUTO /
CONFIRM tiers and `verify`); use that if you edit there.

## Phase 8: edit (45 min)

`workflows/talkinghead` (V track). Slides go in as `BROLL` entries in the config: `mode="split"` (slide on top,
speaker below; captions follow the face box) or `mode="cut"` for a full-screen diagram. Pick the style
(记笔记 / 精剪 / 混合) and the hooks with the creator. Captions: read every line against the audio; fix recurring
term errors in persona `subtitles.term_fixes`.
**Check:** `compose.py config.py preview <t1>,<t2>,<t3>` stills at a hook, a split slide and the ending before
the full render.

## Phase 9: cover (30 min)

`workflows/cover`. Pattern **B** (face over four slides) builds recognition for a new channel; pattern **A**
(collage) shows content density once the channel is known; the talkinghead `cover.py` gives the 记笔记-style cover.
The headline is the script's hook sentence. Output `work/cover.png` (1080×1920) or the platform sizes.

## Phase 10: polish and export (5–10 min)

`workflows/polish`, then `vstudio.export` for the per-platform files:
```bash
python3 $VSTUDIO/workflows/polish/scripts/polish.py edit.mp4 -o master.mp4 --cover work/cover.png --speed 1.2 --check
python -m vstudio.export master.mp4 --platforms douyin,xiaohongshu:vertical,youtube-shorts --out exports/ --cover work/cover.png [--cues cues.json]
```
Propose 1.2× for shorts and ask before applying (above ~1.3× English speech starts to sound artificial; persona
`speed.cjk_max_intelligible` for Chinese). For several platforms, export a **caption-free** master and pass
`--cues` so each platform gets captions in its own caption box.
**Check:** frame 0 is the cover; loudness within ±1 LU of target, true peak ≤ -1 dBTP; resolution and fps equal
the source; `exports/manifest.json` has no unread warnings.

## Phase 11: publish (30 min)

Post copy: `workflows/talkinghead/scripts/caption.py config.py --title "..." --platform <name>` (title length,
chapter timeline in final-video time, tags), method in `workflows/talkinghead/references/publish_caption.md`;
from Python, `vstudio.publish.post_body` / `check_title`; or pass `--post post.json` ({title, hook, body,
chapters, links, tags}) to `python -m vstudio.export` to get a `<target>.post.md` per platform next to each file.

| Platform | Cover | Caption | Hashtags |
|---|---|---|---|
| YouTube Shorts | upload the cover as the custom thumbnail | hook line + one supporting sentence | 0–2 |
| TikTok / 抖音 | "select cover" → upload the cover | hook line | 3–5, niche-relevant |
| Instagram Reels | "cover" → add from camera roll | hook line | 3–5 |
| 小红书 | custom cover | hook title + body + chapter timeline | per persona `publish.tags` (most important first) |

**Check:** after upload, the published post really shows the custom cover (some platforms swap back to a frame),
and the Short is recognised as a Short (9:16, ≤ 180 s).

## Phase 12: next idea (10 min)

The minutes right after publishing carry the most momentum. Write three candidate topics, pick the strongest,
write its one-sentence premise, and book the Phase 1–2 session.

## Time budget

| Phase | Budget |
|---|---|
| 1 Premise | 15 min |
| 2 Draft | 45 min |
| 3 Read-aloud + lint | 15 min |
| 4 Drill | 15 min |
| 5 Slides | 60 min |
| 6 Record | 45 min |
| 7 Clean up | 15–30 min |
| 8 Edit | 45 min |
| 9 Cover | 30 min |
| 10 Polish + export | 5–10 min |
| 11 Publish | 30 min |
| 12 Next idea | 10 min |
| **Total** | **~4.5–5 h first time, ~2 h when fluent** |

## Failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| Final video feels boring | pace too slow, no motion, no music | music bed around -28 dB under the voice (`audio.mix_bed`), 1–2 animated slides, consider 1.1–1.2× |
| Quiet on a phone | loudness step skipped or wrong target | re-run polish; check the printed integrated LUFS |
| Cover looks off-brand | wrong template or accent | keep persona `cover.accent` = `slides.accent`; re-render |
| Captions out of sync | speed applied after captions were burned in | export a caption-free master, polish, then let `vstudio.export --cues` burn captions |
| A word disappeared | an aggressive filler cut | re-run the cleanup verify step; take that cut out |
| Platform shows a random frame as cover | custom cover not uploaded at publish time | edit the post, upload the cover again |
| Short not in the Shorts feed | over 180 s or not 9:16 | trim to ≤ 180 s, export 9:16 |

## Output contract

```
short_NNN_<topic-slug>/
├── SCRIPT.md                        # locked, linted
├── work/
│   ├── pronunciation_drill.{m4a,md} # optional
│   ├── slides/slide_NN_*.png        # + ≤3 slide_NN_*.mp4
│   └── cover.png                    # or cover.<platform>-<orientation>.png
├── edit.mp4                         # edited talking head (from talkinghead or another editor)
├── master.mp4                       # polished
└── exports/                         # one file + cover per platform, manifest.json
```
Published on at least two platforms within a day of the polish step.

## If you record or edit in Descript (or CapCut / 剪映)

The same phases apply; only 6–8 move into the editor. Use a 9:16 project with a split layout (e.g. Descript's
chapter-title split) and drop the square slide PNGs / MP4s into the slide region at their timestamps. Its built-in
filler-word removal replaces Phase 7 (still review every removal). Export 1080×1920, source frame rate, high quality,
AAC audio, and **without burned captions** if you will speed up or export to several platforms (otherwise captions
end up doubled or out of sync). Then continue at Phase 9 with `polish.py` on that export: it replaces the dead first
second (often a black title card) with the cover and brings the usually quiet export (around -20 LUFS) to target.
