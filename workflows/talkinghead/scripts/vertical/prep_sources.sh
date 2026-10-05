#!/usr/bin/env bash
# Convert phone clips (iPhone HLG / Dolby Vision HDR, or plain SDR) to SDR 1080p H.264, extract audio,
# transcribe with word timestamps.
# usage: bash prep_sources.sh WORK_DIR clip1.MOV clip2.MOV ...   (clips are numbered 1..N in order)
# env PROMPT="术语 列表 ..."   whisper initial_prompt (fixes English terms in Chinese speech)
# env TONEMAP=avconvert|ffmpeg  force a tone-map backend (default: avconvert for HDR clips when present, else ffmpeg)
# env KEEP_LANDSCAPE=1           keep a landscape clip as is (default: crop 9:16 around the face, scale to 1080x1920)
#
# Outputs per clip i: sdr$i.mp4 (picture + sound cut_pass1 cuts from), a$i.wav (16k mono), a$i.json (whisper)
# Built on vstudio.media.to_sdr (avconvert, else ffmpeg zscale/tonemap=hable, else libplacebo, else a warned
# approximation), media.extract_wav and vstudio.asr (via ../asr.py).
set -euo pipefail
export VSTUDIO_LIB="$(cd "$(dirname "$0")/../../../../lib" && pwd)"
if [ $# -lt 2 ]; then sed -n '2,10p' "$0"; exit 1; fi
HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="$1"; shift; mkdir -p "$WORK"; i=0
for SRC in "$@"; do
  i=$((i+1))
  python3 - "$SRC" "$WORK/sdr$i.mp4" "$WORK/a$i.wav" "${TONEMAP:-auto}" <<'PY'
import os, sys; sys.path.insert(0, os.environ["VSTUDIO_LIB"])
from vstudio import media
src, sdr, a16, backend = sys.argv[1:5]
# fit inside 1080x1920 (portrait) or 1920x1080 (landscape); ffmpeg auto-applies the rotation tag first
fit = "scale='if(gt(iw,ih),1920,1080)':'if(gt(iw,ih),1080,1920)':force_original_aspect_ratio=decrease:force_divisible_by=2"
media.to_sdr(src, sdr, backend=backend, fit=fit, crf=14)
info = media.probe(sdr)
if info['w'] > info['h'] and os.environ.get('KEEP_LANDSCAPE') != '1':
    # The V track composes a 1080x1920 frame. A landscape clip (webcam, Zoom) is cropped to 9:16 around
    # the speaker's median face x and scaled up; compose.py would otherwise read garbage frames.
    import cv2, numpy as np
    from vstudio import face as VF
    cap = cv2.VideoCapture(sdr); n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)); lm = VF.landmarker(1); xs = []
    for k in range(15):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * (k + .5) / 15)); ok, img = cap.read()
        f = VF.main_face(VF.detect(lm, img)) if ok else None
        if f is not None: xs.append(float(f['pts'][:, 0].mean()))
    cap.release()
    cw = int(info['h'] * 9 / 16) // 2 * 2
    cx = float(np.median(xs)) if xs else info['w'] / 2
    x0 = int(min(max(0, cx - cw / 2), info['w'] - cw)) // 2 * 2
    tmp = sdr[:-4] + '.land.mp4'; os.replace(sdr, tmp)
    media.run(['ffmpeg', '-y', '-i', tmp, '-vf', f'crop={cw}:{info["h"]}:{x0}:0,scale=1080:1920:flags=lanczos,setsar=1',
               '-c:v', 'libx264', '-crf', '14', '-preset', 'medium', *media.BT709, '-c:a', 'copy', sdr])
    os.remove(tmp)
    print(f"landscape source: cropped {cw}x{info['h']} at x={x0} (face x~{cx:.0f}) and scaled to 1080x1920"
          f"{' (x%.2f upscale: soft)' % (1920 / info['h']) if info['h'] < 1920 else ''}; KEEP_LANDSCAPE=1 to skip")
media.extract_wav(sdr, a16, sr=16000, channels=1)
info = media.probe(sdr); print(f"{os.path.basename(sdr)}: {info['w']}x{info['h']} {info['fps']:.3f} fps {info['duration']:.1f}s")
PY
  python3 "$HERE/../asr.py" "$WORK/a$i.wav" "$WORK/a$i.json" ${PROMPT:+--prompt "$PROMPT"}
done
