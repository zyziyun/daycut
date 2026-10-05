# ai-video - AI-generated dialogue shorts and series, from script to 投稿

**Use when:** the footage does not exist yet and will be generated with AI video models (Kling, Seedance/即梦,
MiniMax/Hailuo, Vidu...): a dialogue skit, a mock ad, a recurring two-character series, "make a video like this
reference but with my characters", or when finished AI shorts need to go out to several platforms as a series
(双语版 for Chinese platforms, English version for TikTok / Shorts / communities).
**Inputs → Outputs:** premise or script (+ optional reference video, own photos, own voice sample) →
approved transcript, character bible + scene masters, shot list with per-model prompts and a credit plan,
reviewed takes, a caption-free master + cues from the final audio, per-platform exports, covers, post copy,
and upload-ready packages per platform (actual upload only per post after `--confirm`).

Run from the project (video) folder. `$VSTUDIO` = repo root. Keep project files under `work/ai/`.
Background: [PROMPTING](references/PROMPTING.md) · [PROVIDERS](references/PROVIDERS.md) (prices, MCP setup,
what failed) · [JUDGE_RUBRIC](references/JUDGE_RUBRIC.md) · [PUBLISHING](references/PUBLISHING.md) ·
[LICENSING](references/LICENSING.md).

## Money rule
Every generation is charged. Nothing in this workflow spends credits unless the user approved the printed plan
and the command carries `--yes --budget N`. Plans are estimates from observed prices; the price the provider
shows before Generate wins. Never resubmit a failed or timed-out job automatically: check the provider's task
list first (a timeout may still have been charged), then ask.

## Pipeline

1. **Production contract** (ask only what blocks): premise / ending, duration, aspect (9:16 default), spoken
   language, caption languages, characters, platforms, provider budget. Consent for any face or voice that is
   not the user's own.
2. **Script.** If there is a reference video, break it down first (beats + timestamps, repeating device,
   payoff, on-screen text style): `vstudio.media.contact_sheet(ref.mp4, "ref_sheet.jpg", every=1.5)` + `vstudio.asr.transcribe`.
   Rewrite dialogue into natural speech, score it with an explicit rubric, iterate, and lock one transcript
   with line ids (see PROMPTING §1). Offer 2-3 premises with a recommendation; the creator picks.
3. **Bible + anchors.** Copy `templates/project.yaml` to `work/ai/project.yaml`. Fill `characters` (look
   string, neutral closed-mouth look sheet, voice) and `scenes` (one approved scene-master still each).
   Shrink uploads: `python3 $VSTUDIO/workflows/ai-video/scripts/generate.py prep-refs refs/*.jpg --out refs/upload`.
   Review all anchors together with the user once.
4. **Shot list → plan (dry run, free).** Fill `shots` (camera, action, lines, `unit:` groups for shared set-ups).
   ```bash
   python3 $VSTUDIO/workflows/ai-video/scripts/generate.py plan work/ai/project.yaml
   ```
   Prints units, snapped durations, per-model prompts, estimated credits (+ retry allowance) and warnings
   (prompt too long, too many refs, mixed scenes, oversized refs). Fix warnings in the plan, not at submit time.
   Show the plan; get a yes and a budget.
5. **Generate.**
   - API / MCP provider: hardest units first, then the rest.
     ```bash
     python3 $VSTUDIO/workflows/ai-video/scripts/generate.py run work/ai/project.yaml --only u04,u13 --budget 200 --yes
     python3 $VSTUDIO/workflows/ai-video/scripts/generate.py collect work/ai/project.yaml   # resume after a crash
     ```
     Kling: first frames (cheap images) → user approves → animate the approved frame. Inside Claude Code the
     `mcp__kling__*` tools can be called directly instead (same rules: list units + credits, wait for a yes).
   - Web-only tools (即梦/Seedance, Hailuo, Kling web): `provider: manual:jimeng`, then
     `generate.py sheets work/ai/project.yaml` → paste each one-line prompt, attach the listed refs, download
     as `<unit>_*.mp4`, `generate.py import work/ai/project.yaml downloads/<unit>_*.mp4`.
   - Draft resolution + local upscale instead of a paid upgrade:
     `python3 $VSTUDIO/workflows/ai-video/scripts/upscale.py takes/seg1_v1.mp4 takes/seg1_v1_1080.mp4 [--weights realesr-general-x4v3.pth]`.
6. **Review every take** before it enters the edit:
   ```bash
   python3 $VSTUDIO/workflows/ai-video/scripts/judge.py sheet work/ai/takes/u03_v1.mp4 --expect "approved line" --out work/ai/judge
   python3 $VSTUDIO/workflows/ai-video/scripts/judge.py sheet work/ai/takes/u13_v1.mp4 --dense      # falls/collapses
   python3 $VSTUDIO/workflows/ai-video/scripts/judge.py card u03_v1 --out work/ai/judge && $EDITOR work/ai/judge/u03_v1.card.json
   python3 $VSTUDIO/workflows/ai-video/scripts/judge.py verdict work/ai/judge/u03_v1.card.json
   ```
   Faces at full size next to the sheet. Redo only failed units; keep accepted takes; when speech differs
   from the transcript, regenerate or accept the performance and caption what is said.
7. **Lock the edit, then assemble.** Copy `templates/timeline.yaml` to `work/ai/timeline.yaml`: literal EDL of
   accepted takes with in/out (cut on line ends), stills for cards, grade (-10..15 % saturation, light grain),
   licensed music bed.
   ```bash
   python3 $VSTUDIO/workflows/ai-video/scripts/assemble.py work/ai/timeline.yaml --check
   python3 $VSTUDIO/workflows/ai-video/scripts/assemble.py work/ai/timeline.yaml     # master.mp4 + cues.json from the final audio
   ```
   Proofread `cues.json` (names, product terms - an ASR misspelling held one episode back). Bilingual: add
   `alt` per cue (`vstudio.subs.pair_bilingual` / `apply_translations`), translated line larger on top.
   On-screen text (labels, phone pop-ups, title cards) is deterministic post: render PNG cards with
   `vstudio.draw` / `vstudio.overlays` (or HyperFrames via `workflows/promo-recut`) and put their boxes in
   cues.json `keepouts` so captions move around them.
8. **Export per platform** (one master → many): 
   ```bash
   python3 -m vstudio.export work/ai/master.mp4 --platforms douyin,xiaohongshu:full,tiktok,youtube-shorts \
       --cues work/ai/cues.json --cover douyin=work/cover-9x16.png --cover xiaohongshu=work/cover-3x4.png --out exports/
   ```
   Covers: `workflows/cover` from clear approved frames, whole heads at the delivery ratio. Copy:
   `vstudio.publish.post_body` / `check_title`; for comedy lead with the contradiction, not a lesson.
9. **投稿 packages (default) and per-post upload.** Copy `templates/series.yaml` next to the exports, add the
   episode (`status: ready`, sources per caption variant, covers per ratio, zh/en title/hook/body, `publish_at`).
   ```bash
   python3 $VSTUDIO/workflows/ai-video/scripts/package.py build  series.yaml 3      # out/ep03/<platform>/...
   python3 $VSTUDIO/workflows/ai-video/scripts/package.py plan   series.yaml 3 douyin
   python3 $VSTUDIO/workflows/ai-video/scripts/package.py upload series.yaml 3 douyin --confirm <code from plan>
   python3 $VSTUDIO/workflows/ai-video/scripts/package.py status series.yaml
   ```
   Show the plan to the user; upload only with their yes, one platform at a time. Tick the AI label by hand
   wherever the plan says `manual`.

## Gotchas (each cost credits or a redo in the sessions)
- **One long brief for a whole film fails.** An all-in-one agent run lost the premise, swapped in the reference
  photo, turned a fall into a bird. Generate per shot/segment, assemble locally.
- **The look sheet's expression leaks** into every shot (a grinning sheet = grinning in danger). Use neutral sheets.
- **Extreme angles invent faces.** Top-down onto an upturned face gave a different person with different glasses.
- **Occluded body parts vanish** when revealed (legs "buried" in a pile disappeared as it collapsed). Ask for
  full bodies on top of things; check such shots every 0.25 s.
- **Generated text is always wrong somewhere.** Blank screens in generation, real text in post.
- **Prompt timecodes are not cut points** (Seedance). Cut on scene detection + word timestamps.
- **A newline in a web prompt box can submit** (paid). One line; check the price dialog before confirming.
- **Upgrading drafts costs ~7x**; local upscale was good enough for phones.
- **Captions from the final audio only.** Generated actors deliver lines differently (a scripted all-caps
  scream came out at normal volume; the caption was changed to match). Never lay the draft script over new speech.
- **Tokens expire mid-batch (401).** Persisted task ids let `collect` resume without paying twice.
- **Model music options may return only ambience** - score in post with a bed you have rights to.
- **Mixed models for one face read as a different person**; switch a whole character, not one shot.

## Checks before delivery
Resolution/aspect/duration per export, loudness in `exports/manifest.json`, captions inside the safe box,
every face whole on every cover, AI label plan per platform, credits spent vs budget (`generate.py status`).
