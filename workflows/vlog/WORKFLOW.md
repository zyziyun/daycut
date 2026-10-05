# vlog: B-roll clips -> short vlog (calm or fun / fast-paced)

**Use when:** Edit a pile of silent or ambient B-roll clips (drone/DJI aerials, phone travel or walking clips, nature, city, action cam) into one short polished vlog - inspect the footage, cut the good windows out of long takes, colour grade (HDR phone clips tone-mapped), speed-adjust per shot, crossfade with a clean non-black opening and a fade-out ending, build a scrapbook torn-paper cover, and add CC-BY or catalog music. Use when someone hands over several clips and wants them "剪成一个vlog / 合并 / 去掉不好的部分 / 加转场 / 调色 / 配乐 / 做封面", even if they mention only one piece, or to tweak one stage of an already-built vlog (re-cut, re-grade, speed, music swap, cover, smaller upload file).

**Use when** the footage carries the story without narration: drone flights, walks, trips, nature,
city wandering, a day of phone clips. The raw material is long takes, slow moves, dim or HDR light,
dead tails, and no (or only ambient) sound. The craft is choosing good windows, tightening pace,
lifting the light, and giving it a soundtrack and a cover. A few clips of the creator talking to the
camera while travelling are fine (speech clips, fun style); a video that is mostly one person talking
belongs in `talkinghead`.

**Inputs ->** a folder of clips (MP4/MOV, any size, landscape or portrait, SDR or HLG/PQ, 24-120 fps),
optional still photos (JPG/PNG/HEIC) and, for the fun style, a music track.
**Outputs ->** `work/edit.json` (reusable edit list), `work/vlog_master.mp4` (graded, crossfaded),
`work/vlog_music.mp4`, `work/cover.png` (+ `cover_1920.jpg`), `music/*.mp3` + `music/ATTRIBUTION.txt`.
Fun style: `work/fun_vlog.mp4` (+ `.nomusic.mp4`, `.report.json`, `.cues.json`/`.srt`, `.clean.mp4`).

## Choose a style: calm or fun
Ask once ("calm & cinematic, or fun & fast, cut to the beat?") and recommend from the footage + platform:

| | **calm** (default, `build_vlog.py`) | **fun** (`"style": "fun"`, `build_fun.py`) |
|---|---|---|
| feel | slow crossfades, long holds, ambience, music laid on after | cut to the beat of the track, speed ramps, whips, text pops, SFX |
| footage | drone / nature / walks, long smooth takes, little action | trips with many places, people, food, action, 60/120 fps clips, photos |
| sound | silent or ambient master, music muxed by `add_music.py` | music-led: bed + SFX + talking-to-camera speech (ducked, captioned) |
| length | 1-5 min, horizontal 4K is common | 20-90 s short, vertical first (小红书 / 抖音 / Shorts / Reels), also YouTube |
| pick when the user says | "安静 / 治愈 / cinematic / 慢一点 / 空镜" | "卡点 / 快节奏 / 有趣 / 旅行vlog / fun / fast / travel reel" |

Both read the same `edit.json` shape (`clips`, `src_dir`, `grade`, `hdr`, `platform`); `build_vlog.py` hands a
`"style": "fun"` config to `build_fun.py`, so one command works for both.

Tools: `ffmpeg`/`ffprobe`, Python 3, Chrome/Chromium or Playwright (cover), `curl` (music).
Everything runs from the PROJECT dir (the user's video folder); `$VSTUDIO` = repo root.
Read `references/recipes.md` before writing edit.json or hand-rolling any filter chain.

## Entry points
- "merge / 剪个vlog / 去掉不好的部分" -> full pipeline (calm), after asking calm vs fun.
- "卡点 / 快节奏 / fun travel vlog / reel / 有我说话的片段" -> Fun style section (`build_fun.py`).
- "for 小红书 / 抖音 / YouTube / Shorts" -> Platforms section (`platform` / `--platform`).
- "make a cover / 封面 / 剪贴报" -> step 6.
- "add music / 配乐 / 换首曲子" -> step 7.
- "higher quality / 高清一点" -> set `res` to source 4K, re-run step 5 (see Export variants).
- "too dark / 太暗" -> raise `grade.brightness` or per-segment `bright`, never add a vignette; re-run step 5.
- "too shaky" -> `"stabilize": true` on those segments; re-run step 5.

## Pipeline

1. **Probe and confirm scope.**
   ```bash
   python3 $VSTUDIO/workflows/vlog/scripts/probe.py footage/*.MP4 footage/*.MOV
   ```
   Note size, fps, duration, audio and HDR per clip. If the user named a subset, edit only those.
   Confirm the subset and target (16:9 4K master? vertical 1080x1920?) before any long render.

2. **SEE the footage (never edit blind).**
   ```bash
   bash $VSTUDIO/workflows/vlog/scripts/contact_sheets.sh work/sheets 4 footage/*
   ```
   Read every `work/sheets/*_sheet.jpg`: one tile per 4 s, 5 across, left->right top->bottom,
   each labelled with its source time (tile n = (n-1)*4 s). Mark windows where the subject is clearly framed and the move is smooth;
   skip approach/retreat tails, pocket shots, shaky stretches.

3. **Write the edit list.**
   ```bash
   python3 $VSTUDIO/workflows/vlog/scripts/probe.py footage/* --init work/edit.json
   ```
   then replace the placeholder `segments` with `{clip,start,dur}` windows (optional `speed`,
   `kind:"empty"`, `bright`, `stabilize`). Order them into a small arc: wide establishing ->
   reveal -> intimate subject moments -> calm closing shot. Keep most segments 8-22 s of source.
   Schema + example: `references/recipes.md`, `examples/edit.example.json`.

4. **(optional) Draft first.** Copy edit.json with `res` at 1080p (or `--max-res 1920` on `--init`)
   and `"out": "draft.mp4"`; render, watch, adjust windows.

5. **Render the master.**
   ```bash
   python3 $VSTUDIO/workflows/vlog/scripts/build_vlog.py work/edit.json          # --dry-run to inspect
   ```
   Renders segments in parallel (HDR tone-map -> fit -> grade -> speed -> fps), then crossfades into
   one master with NO black first frame and a fade-out at the end. A true-4K pass is slow: run it in
   the background and report when done. `"ambient_audio": true` keeps each clip's own sound
   (tempo-matched, crossfaded) instead of a silent master. A segment where someone talks to camera can
   get the shared 气口 / filler / repeat cleanup before assembly (opt-in in calm, `references/CLEANUP.md`):
   `"cleanup": true | "gentle" | "standard" | "tight" | "pauses" | {"profile", "reply": "确认 3 / 保留 5"}` on the
   segment (or `"speech": true` on the segment + a top-level `"cleanup"`). `build_vlog.clean_speech` runs
   `analyze --ranges start-(start+dur)` -> `apply` (auto edits + the creator's reply) and the segment then plays
   the cleaned clip; EDL + review sheet in `<out dir>/clips/cleanup/`. Needs `"ambient_audio": true`; transcript
   from the segment's `words`, `<clip>.words.json`, else ASR.

6. **Build the cover** (scrapbook torn-paper collage, full-bleed, no text by default).
   Extract 5-6 frames where the subject reads clearly plus one wide frame for the darkened backing:
   ```bash
   mkdir -p work/frames
   ffmpeg -ss 3 -i footage/CLIP.MP4 -frames:v 1 -vf "scale=1400:-1,eq=saturation=1.18" work/frames/a.jpg
   python3 $VSTUDIO/workflows/vlog/scripts/make_cover.py --out work/cover.png \
     --hero work/frames/hero.jpg --frames work/frames/{a,b,c,d}.jpg --base work/frames/wide.jpg
   ffmpeg -i work/cover.png -vf scale=1920:1080 -q:v 2 work/cover_1920.jpg
   ```
   Vertical: `--size 1080x1920`. Optional label: `--title "..."` (vstudio font roles, staged into
   `work/assets/fonts/`). The auto layout centres each piece on its largest face (`vstudio.face`, else OpenCV;
   `--no-faces` keeps the fixed focus points) and writes exactly `--size` px (`--scale 2` for a 2x render; the
   log prints the real pixel size). Read `cover.png`; if a piece crops the subject, copy
   `examples/cover.example.json`, adjust `bgpos`/`bgsize`/`left/top`, and re-run with `--config`.
   For HDR phone clips pull frames from the master, not the source.

7. **Add music.** Ask for the vibe in the user's words, map it to the cheatsheet inside
   `fetch_music.sh`, fetch, mux:
   ```bash
   bash $VSTUDIO/workflows/vlog/scripts/fetch_music.sh music "Atlantean Twilight"
   python3 $VSTUDIO/workflows/vlog/scripts/add_music.py work/vlog_master.mp4 \
     music/Atlantean_Twilight_KevinMacLeod.mp3 work/vlog_music.mp4 --fade 2
   ```
   `add_music.py` loops the track to fill, fades it in/out, two-pass normalizes to persona
   `audio.loudness_lufs` (-14), and copies the video stream (fast). With an ambient master add
   `--ambient-db -12` to keep the place's sound 12 dB under the music bed (`vstudio.audio.mix_bed`).
   **Attribution:** these tracks are CC BY 4.0. `music/ATTRIBUTION.txt` holds the credit line(s);
   give them to the user to paste into the post description.
   **Catalog alternative:** `npx hyperframes media-use resolve --type bgm` (HyperFrames / HeyGen
   catalog via the `media-use` skill) returns a frozen local track; use it with `add_music.py` the
   same way, and record whatever credit its licence requires in `music/ATTRIBUTION.txt`.
   Music taste is subjective: deliver one, offer named swaps from a different cheatsheet row
   ("too cheerful" / "too epic" -> change family, not track).

8. **Deliver.** A native-4K master is large (~1.8 GB per ~3 min). Offer a smaller visually-lossless
   4K or high-bitrate 1080p (commands in recipes.md). State duration, resolution, file size, and list
   the files produced. `work/clips/seg_*.mp4` are safe to delete.

## Fun style (fast-paced travel vlog)

Pipeline (from the project dir):
```bash
python3 $VSTUDIO/workflows/vlog/scripts/probe.py footage/* --init work/edit.json --style fun \
    --music music/track.mp3 --platform xiaohongshu:full          # starter: every clip once, auto windows
bash $VSTUDIO/workflows/vlog/scripts/contact_sheets.sh work/sheets 4 footage/*   # SEE the footage
# edit work/edit.json: order shots by place/day, add place/day/date, speech, ramp, photos, title, map...
python3 $VSTUDIO/workflows/vlog/scripts/build_fun.py work/edit.json --dry-run    # plan: read the report
python3 $VSTUDIO/workflows/vlog/scripts/build_fun.py work/edit.json              # render
```
Read `work/fun_vlog.report.json` before showing the video: every cut with its beat check (`verify`, must be
`ok`), transitions and full-frame hits, sections, overlays with their boxes, the SFX cue sheet, loudness
and warnings. Snapshot the busiest frames (title, map, a whip mid-frame, a caption) and look at them.
Example: `examples/edit.fun.example.json` (synthetic names).

**How it cuts.** Music first: `vstudio.beats.analyze` (grid fit, downbeats, sections, strong hits;
saved to `work/fun_cache/beats.json`). Video t=0 is a downbeat (`music_start: "auto"`). Every shot boundary
is a whole beat, so cuts land within 1 frame of the beat after rounding (`beats.verify` in the report).
`beats.energy_arc(T, "travel-fun")` sets the pattern: **hook** (best 3-5 windows of the whole trip,
`cut_plan(..., "accelerate")` into the first bar line) -> **intro** (title pop on the bar, flash) ->
**body** (your shots in order; montage = 1 beat per shot, breather = 1 bar; a new place/day starts on a bar
line with a whip, the 3rd change a glitch; a music drop gets a cut exactly on it with a zoom punch +
impact) -> **finale** (best windows again, accelerating; riser -> impact -> sparkle) -> **outro** (slow
wide shot at 0.8x, end card). At > 143 BPM one "unit" is 2 beats.

**Shot keys** (each item of `shots`): `clip` (file in `src_dir`, or an id from `clips`) or `photo` (in
`photo_dir`; JPG/PNG/HEIC - HEIC via pillow-heif or macOS `sips`). Optional: `start`/`dur` (source s; omit
= auto-pick the best window: sharpness + moderate motion + exposure + face, per second), `beats` (shot
length), `speed`, `ramp` (`"slowmo"` = true slow-mo at 30/source-fps, e.g. 0.25x on 120 fps;
`"slow-fast"`, `"fast-slow"`, `"fast-slow-fast"`, or `[[u, rate], ...]` keys over the shot, smoothstep
between keys), `freeze` (`true` = last 2 beats freeze into a photo card with a shutter), `place`, `day`
(+ `day_label`), `date` (camcorder stamp), `pop` (a word that pops on the shot), `speech` (`"auto"` /
`true`), `cleanup` (see Speech clips), `tighten`, `words` (transcript file), `fit` (`face` / `pad-blur` / `center` / `crop`),
`transition` (into this shot: `cut whip zoom flash leak glitch`), `style` (photo: `card` / `full`),
`bright`, `keep_audio` (`true` / dB: keep a non-speech clip's own sound as an accent, see Sound).

**Top-level knobs**: `platform`, `music`, `music_start` (`"auto"` or seconds, snapped to a bar), `drops`
(music seconds; default from the analysis' section jumps), `pace` (`fast` | `relaxed` = double length),
`speed` (default 1.0), `title` (`{text, sub, hold}`), `map` (`{places: [{name, lat, lon} | {name, xy:
[0-1, 0-1]}], beats: 8, after, title}` - its own breather slot over a blurred clip, after the title),
`word_pops` (words placed on bar lines of montage shots), `end_card` (`{text, sub}`), `hook` / `finale`
(false to skip, or an explicit list of 1-6 items: clip ids / file names, photo file names, `{clip, start, speed}`,
`{photo, style}` - photos play as full-frame Ken Burns; a clip without `start` gets its best window), `outro` (false,
or `{clip, start, speed, beats}` / `{photo, beats}`), `outro_beats` (8), `pool_photos` (true: when fewer than 3
silent clips exist the auto hook / finale use the photos), `max_leaks` (4) / `leak_gap` (16 beats),
`keep_audio` (default for every shot), `speech_min_words` (4), `captions`, `cleanup`, `tighten`,
`max_speech` (12 s), `asr` (false = never run whisper), `language`, `sfx`, `music_lufs` (-19 bed before
the final loudnorm), `duck_db` (-12), `music_fade` (1.5), `max_hits` (3), `grade` (fun default: brightness
0.02, contrast 1.08, saturation 1.2), `warm`, `sharpen`, `hdr`, `reframe` (`face`), `reframe_fallback`
(`pad-blur` or `center`), `photo_style` (`card`), `blend_slowmo` (true), `fps`, `res` (overrides the
profile canvas), `preset` (x264), `face_score` (true).

**Speech clips (talking to camera while travelling).** `speech: "auto"` keeps a clip's own audio when it
has speech, `true` forces it. Words come from `words` / `<clip>.words.json` (`[{w, t, te}]` or whisper JSON;
trusted as given), else `vstudio.asr.transcribe` (cached), else loudness only (contrast >= 15 dB; no captions;
warned). **ASR words are only trusted when** the transcript survives `asr.drop_hallucinations` (whisper's
"字幕志愿者…" / "请不吝点赞订阅…" / "Thanks for watching" over music), still has >= `speech_min_words` (4) words
(`asr.has_speech`), AND the clip's loudness backs them up (envelope contrast >= 10 dB and >= 50 % of the words
inside voiced runs). Otherwise `"auto"` = no speech (music bed only, no captions) and `true` = audio kept,
captions off. The starter from `probe.py --init --style fun` sets `"auto"` on clips with audio, which is now
safe on PhotoPass / ride clips with template music. Every decision is printed (`[fun] speech clip: SPEECH /
no speech (why)`) and listed in the report's `speech` array (source, word counts, contrast, overlap, reason). The window never cuts a sentence: a given `start`/`dur` grows to whole
sentences; without one it takes the first sentences up to `max_speech`. The shot ends on the next beat
after the speech (room tone fills the gap).
**气口 / filler / repeat cleanup (the shared tool, `references/CLEANUP.md`).** Every speech shot with words is
run through `vstudio.cleanup` before the timeline is built (`analyze --ranges <window>` on that clip): profile
`gentle` by default (pauses > 0.8 s squeezed, hesitations 嗯/呃/um only, breaths kept), **auto edits only**. The EDL
and review sheet land in `<cache>/cleanup/<clip>_<a>-<b>.cleanup.json` / `.review.md`, the decision is printed and
in the report's `speech[].cleanup` (profile, applied ids, ids waiting for confirmation, seconds before / after).
To cut more, read the sheet to the creator and put their reply on the shot:
`"cleanup": {"profile": "gentle", "reply": "确认 3,5 / 保留 7"}` (or `approve` / `keep` lists, `all_confirm`).
Knob, top level and / or per shot (the shot wins): `false` (off), `true` / `"gentle"`, `"standard"`, `"tight"`,
`"pauses"` (气口 only, no word edits), or the dict. Legacy `tighten: true` = `"standard"`. Captions follow the kept
pieces (`cleanup.timemap` + `cleanup.remap_words`), so cut words never get a caption. Loudness-only speech (no words)
is not cleaned. The speech gate above runs first: a rejected transcript is never cleaned.
Speech plays at 1x; the music bed ducks `duck_db` under it (`audio.mix_bed`, measured dip in the report);
captions (`subs.cues_from_words`) are burned in the profile's caption box (`export.caption_overlay`).

**Transitions** (one per cut, frames borrowed half from each neighbour, dropped to a hard cut when a
neighbour is too short): whip (directional translate + motion blur, peak >= 300 px/frame), zoom punch, flash
(white hidden cut), light leak (warm screen-blend sweep), glitch-lite (RGB split + band shifts), straight
cut on the beat (default - the drums carry it). Flash and zoom are full-frame hits: at most 3, >= 16 beats
apart (extra ones become light leaks). Photos: hard cut by default (the shutter SFX carries it); the first photo
gets a flash, a video -> photo entry may get a light leak, consecutive photos cut. Auto light leaks (photos,
demoted hits) are capped at `max_leaks` (4) and >= `leak_gap` (16) beats apart, extras become hard cuts; the
outro leak and any `transition` you request always stay (A5).

**Text & graphics** (PIL per frame, brand colours from persona `brand`, fonts via `vstudio.draw`, all inside
the platform safe box): title pop (scale-bounce, holds >= 1.2 s), location tag (pin + name, slides in),
DAY n stamp, date/time stamp, word pops, route map card (dots + arcs drawn progressively, pins tick),
end card. Tags never stack: the previous one leaves before the next lands; tags / DAY stamps / date stamps of
different kinds that are on screen together never overlap either (`gfx.resolve_collisions` moves the later one
below the other inside the safe box, or delays it; the report's element `note` says so). The route map never
drops a label: labels try 16 spots around the pin, avoiding pins, other labels and the line; the route finishes
>= 1.25 s before the card leaves so the last pin and label hold >= 1 s.

**Sound**: `loop_bed` (music from the analysed downbeat, crossfaded loops, fade at the end) ->
`mix_bed` (music at `music_lufs`, voice at persona `audio.voice_lufs`, ducking) -> `cue_sheet_for(kind=
"travel-fun")` SFX (whoosh/whip on whips, impact on drops and the title hit, riser -> impact -> sparkle into
the finale, shutter on photos and freezes, stamp on DAY stamps, pops on tags/words, ticks on map pins) ->
true-peak limiter (`audio.limit`) -> two-pass loudnorm to the profile. A `.nomusic.mp4` (voice + accents + SFX,
the SAME gain as the music mix) ships too (A13): it is a stem for re-scoring, so with no speech it is SFX only
and measures far below the target (e.g. -17 LUFS against -14) - do not upload it as is.
Native sound of non-speech clips is dropped unless `keep_audio` is set (per shot, or top-level for all):
`true` = each piece at persona `audio.voice_lufs` - 8 dB, a number = that offset (e.g. `-12`), 30 ms fades,
under the music bed (the bed does not duck for it). Constant-speed shots only (0.5-2x); ramped shots are
skipped with a warning; a freeze is silent. Good for a ride scream or a cheer as an accent.
**Looped music:** the report warns when the timeline is longer than the track after `music_start`. The bed then
crossfade-loops and cuts past the track end follow the extrapolated grid. Fix it, in order: pick a longer track,
trim shots / `beats`, use `pace: "fast"`, or start earlier (`music_start`). A loop shorter than ~5 s at the very
end is usually inaudible under the outro fade; check by listening to the last 10 s.

**Aesthetic rules applied** (`$VSTUDIO/references/AESTHETICS.md`): A1 title and tags hold >= 1 s; A2 hook and
finale accelerate, breathers rest; A4 <= 3 full-frame hits on bar lines >= 16 beats apart; A5 one
transition per cut, borrowed frames, hard cut by default, styled ones only at place/day changes; A6 text >=
5 % (title) / 3 % (tags, dates) of frame height; A7 glitch used once; A8 the hook opens on the single
best shot for 2 units; A10 finale = best shots again + riser -> impact -> sparkle; A11/A12 SFX by genre,
alternating and stepping down (`cue_sheet_for`); A13 with- and without-music versions; A14 `beats.verify`
in the report. Still check A3 (first version too fast? use `pace: "relaxed"`) and A9 by watching.

**Tweaks.** "too fast" -> `pace: "relaxed"` or `beats` per shot; "wrong moment" -> give `start`/`dur`;
"music starts wrong" -> `music_start` (seconds into the track); "cut on the drop" -> `drops: [s]`;
"less text" -> drop `word_pops`/`date`/`map`; "no SFX" -> `sfx: false`; "too loud music" -> `music_lufs:
-22`; "speech too quiet" -> `duck_db: -16`.

## Platforms
`platform` in edit.json (or `--platform` on `build_vlog.py` / `build_fun.py` / `add_music.py` /
`make_cover.py`): `xiaohongshu:full`, `xiaohongshu:vertical` (3:4), `douyin`, `tiktok`, `youtube`,
`youtube-shorts`, `bilibili:horizontal`... (`python3 -m vstudio.platform` lists them).
- **calm**: when `res` is absent the canvas and fps come from the profile, the length check is printed;
  `add_music.py --platform P` normalises to the profile loudness; `make_cover.py --platform P` sizes the cover
  (`platform.cover_size`) and prints the title-safe box. With `res` set nothing changes (old configs).
- **fun**: default = persona `platforms.default` in its full-screen vertical orientation. The profile sets
  canvas, fps, safe box (every overlay), caption box + caption size/char limits, loudness (LUFS / true
  peak), encode guidance, length check (warning in the report). Off-aspect clips are reframed with
  `vstudio.reframe` (face mode keeps the face in the safe box; faceless scenery falls back to `pad-blur`, or
  `"reframe_fallback": "center"` / per-shot `"fit": "crop"` for a centre crop).
- **Several platforms from one edit**: re-run `build_fun.py --platform X` per target (layouts, captions and
  reframes are native to each canvas; cached analysis makes reruns cheap). Or render once with
  `--clean-master` (caption-free `<out>.clean.mp4` + `<out>.cues.json`) and
  `python -m vstudio.export work/fun_vlog.clean.mp4 --platforms douyin,youtube-shorts --cues
  work/fun_vlog.cues.json --cover work/cover.png --out exports/` (same-aspect targets keep the graphics
  placement; other aspects are reframed, so prefer re-running for those).

## Scripts
- `scripts/probe.py` - per-clip size/fps/duration/audio/HDR; `--init` writes a starter edit.json (`--style fun`).
- `scripts/build_fun.py` - fun style: beat analysis, plan, render, mix, report (`funvlog/`: `score` auto
  windows, `plan` beat-grid timeline + budgets, `frames` decode/ramps/reframe/photos/transitions, `gfx`
  title/tags/stamps/map/end card, `mix` speech/bed/ducking/SFX/loudness).
- `scripts/contact_sheets.sh` - time-labelled thumbnail grids per clip (wraps `vstudio.media.contact_sheet`).
- `scripts/build_vlog.py` - config-driven HDR tone-map + fit + grade + speed + stabilize + crossfade master.
- `scripts/make_cover.py` - torn-paper scrapbook cover, any size, optional title; Chrome/Chromium/Playwright.
- `scripts/fetch_music.sh` - CC-BY Incompetech tracks by title + `ATTRIBUTION.txt`.
- `scripts/add_music.py` - loop/fade/two-pass-loudnorm music mux (optional ambient bed), video copied.

## Persona keys (all optional)
`vlog.speed_subject` (1.2), `vlog.speed_empty` (1.3), `vlog.grade` ({brightness, contrast,
saturation, gamma}), `vlog.cover_tape` (title label underline colour), `vlog.fun_grade` (fun-style grade),
`vlog.fun_music_lufs` (-19); `brand.*` colours for the fun graphics; `platforms.default`; plus existing
`audio.loudness_lufs`, `audio.music_lufs` (bed level before the final loudnorm), `audio.voice_lufs`,
`export.audio_bitrate`.

## Tests
`python3 -m pytest $VSTUDIO/workflows/vlog/tests -q` (synthetic lavfi clips incl. 120 fps and a sine
"speech" clip, a 120 BPM drum track, generated photos + HEIC; ~6 min): fun renders for xiaohongshu:full and
youtube (beats, spikes, transitions, loudness, caption box, SFX peaks, ducking, slow-mo), calm output
identical to git HEAD, calm platform wiring. `VLOG_TEST_DIR=/tmp/vt` keeps media and renders between runs.
