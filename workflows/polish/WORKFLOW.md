# polish — make any exported edit publish-ready

**Use when:** an edit has been exported from any NLE (Descript, CapCut/剪映, Premiere, Resolve, Final Cut, a
HyperFrames render...) and needs the last-mile treatment before upload: the first frame is dead (black title card,
fade-in, idle face) and should become the cover, the audio is too quiet (exports often land around -20 LUFS), the
pacing wants a small pitch-preserved speed bump, and the file should carry correct colour tags and `faststart`.
**Inputs:** `export.mp4` (+ optional `cover.png` from `workflows/cover`). **Outputs:** `final.mp4` at the source
resolution and frame rate, source-matched bitrate, `persona.audio.loudness_lufs` integrated loudness, bt709 tags.

Run from the project (video) folder. `$VSTUDIO` = repo root.

## Pipeline

1. **Probe first, never blind-apply.**
   ```bash
   ffprobe -v error -show_entries stream=codec_name,width,height,bit_rate,r_frame_rate -show_entries format=duration -of default=nw=1 export.mp4
   ffmpeg -y -ss 1 -i export.mp4 -frames:v 1 /tmp/check.png   # ground-truth frame size (ffprobe metadata has lied before)
   ```
2. **One command does the rest:**
   ```bash
   python3 $VSTUDIO/workflows/polish/scripts/polish.py export.mp4 -o final.mp4 \
       --cover cover.png --speed body --keep work/polish --check
   ```
   - `--cover` replaces the first `--cover-sec` (1.0) seconds of *picture*; audio runs uninterrupted, total length
     unchanged. Cover is fitted to the source frame (`--cover-fit fill|fit`).
   - `--speed` takes a number (`1.2`) or a persona key (`hook`, `body`, `fast_body`...). Omit for 1.0.
   - Loudness target defaults to `persona.audio.loudness_lufs` (-14); override with `--lufs`. TP -1.5 dBTP, LRA 11.
   - `--keep DIR` keeps `01_cover.mp4`, `02_speed.mov`, `03_loud.mp4` for stage-by-stage debugging.
   - `--check` writes `final.first.png` so you can eyeball that frame 0 is the cover.
3. **Verify** (the script prints these; re-run any time):
   ```bash
   ffmpeg -i final.mp4 -af loudnorm=I=-14:print_format=summary -f null - 2>&1 | grep -E "Input Integrated|Input True Peak"
   ```

## Rules & gotchas (from real runs)

- **One stage per ffmpeg call.** Cover + speed + loudnorm in one filter graph is miserable to debug; intermediates are cheap.
- **Keep source resolution and frame rate.** Never downscale "to save bandwidth"; platforms re-encode anyway.
- **Match source bitrate when re-encoding** (`--bitrate match`, the default: `-b:v src -maxrate 1.15x -bufsize 2x`).
  Plain `-crf 18` on a ~28 Mbps phone/Descript export lands at 4–6 Mbps: fine for upload, not for an archive master.
  `--crf N` is available when you do want size over fidelity.
- **Two-pass loudnorm** (measure → `linear=true` apply with the measured values). Single-pass loudnorm runs in dynamic
  mode and audibly pumps speech. The loudness step (`vstudio.audio.loudnorm_2pass`) outputs 48 kHz **stereo**
  AAC (mono exports are up-mixed before measuring) and raises the LRA target to the measured LRA so loudnorm stays linear. Normalize once, at the end of the chain; don't normalize again afterwards (platforms
  do their own pass and a second one only costs headroom). `--skip-if-close` leaves gain alone within 1 LU.
- **Speed uses `atempo`, never `asetrate`** (pitch stays put). Factors outside 0.5–2.0 are chained automatically.
  Above ~1.3× speech starts to sound artificial; persona `speed.cjk_max_intelligible` (1.4) triggers a warning.
- **Speed before loudnorm.** The speed step keeps audio as 24-bit PCM so the loudness pass is the only lossy audio encode.
- **bt709 tags**: encodes are tagged at encode time; stream-copied H.264/HEVC are re-tagged with the
  `h264_metadata`/`hevc_metadata` bitstream filter (no re-encode). Untagged SDR files can shift colour on some players.
  HDR sources (iPhone HLG/Dolby Vision) need tone-mapping before this step, not just tags.
- **faststart** moves the moov atom to the front so the first frame shows before the full download.
- The cover-replacement assumes the first second of the export carries no important picture (a typical dead title
  card). If the first second has a hook shot, prepend a cover instead (concat a 0.5–1 s still + delay audio) or pick a
  frame from the hook as the cover.

## Self-check
- [ ] Output resolution and fps equal the source
- [ ] Video bitrate close to the source (or CRF chosen on purpose)
- [ ] Integrated loudness within ±1 LU of target, true peak ≤ -1.0 dBTP
- [ ] Frame 0 is the cover, not black
- [ ] Duration ≈ source ÷ speed (±0.5 s)
