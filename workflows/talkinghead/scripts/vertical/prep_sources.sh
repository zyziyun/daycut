#!/usr/bin/env bash
# Convert phone clips (iPhone HLG / Dolby Vision HDR, or plain SDR) to SDR 1080p H.264, extract audio,
# transcribe with word timestamps.
# usage: bash prep_sources.sh WORK_DIR clip1.MOV clip2.MOV ...   (clips are numbered 1..N in order)
# env PROMPT="术语 列表 ..."   whisper initial_prompt (fixes English terms in Chinese speech)
# env TONEMAP=avconvert|ffmpeg  force a tone-map backend (default: avconvert for HDR clips when present, else ffmpeg)
# env ORIENT=vertical|horizontal   body orientation to build (default vertical). A landscape clip (webcam, camera,
#                                Zoom) for a vertical body is reframed to 9:16 with vstudio.reframe face mode: the
#                                face is tracked (One Euro smoothed virtual camera, dead zone, eased pans, cut-aware),
#                                kept in the platform safe box; no face -> pad-blur. ORIENT=horizontal keeps 16:9
#                                (for compose --platform youtube / bilibili; vertical clips are then left as they are).
# env KEEP_LANDSCAPE=1           same as ORIENT=horizontal (old flag)
# env PLATFORM=douyin            safe box used by the reframe (default persona platforms.default, 9:16)
# env REFRAME_MODE=face|pad-blur|center   override the reframe mode
#
# Outputs per clip i: sdr$i.mp4 (picture + sound cut_pass1 cuts from), a$i.wav (16k mono), a$i.json (whisper),
# sdr$i.crop.json (reframe plan, landscape -> vertical only); prep.json collects per clip: size, mode, face hit
# rate and the picture UPSCALE factor (compose.py caps the punch-in with it so an upscaled crop doesn't go soft).
# Built on vstudio.media.to_sdr (avconvert, else ffmpeg zscale/tonemap=hable, else libplacebo, else a warned
# approximation), vstudio.reframe, media.extract_wav and vstudio.asr (via ../asr.py).
set -euo pipefail
export VSTUDIO_LIB="$(cd "$(dirname "$0")/../../../../lib" && pwd)"
export VSTUDIO_HERE="$(cd "$(dirname "$0")" && pwd)"
if [ $# -lt 2 ]; then sed -n '2,22p' "$0"; exit 1; fi
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
try:
    _si = media.probe(src); up0 = max(1.0, info['w'] / max(1, min(_si['display_w'], _si['display_h']) if info['w'] < info['h'] else _si['display_w']))
except Exception:
    up0 = 1.0                                        # the fit step may already have enlarged a small source
orient = 'horizontal' if os.environ.get('KEEP_LANDSCAPE') == '1' else os.environ.get('ORIENT', 'vertical')
rec = dict(src=os.path.basename(src), w=info['w'], h=info['h'], mode='as-is', upscale=round(up0, 3))
if info['w'] > info['h'] and orient != 'horizontal':
    # Landscape clip -> 9:16 body: face-tracked virtual camera (vstudio.reframe), pad-blur when no face.
    import json, sys as _s
    _s.path.insert(0, os.environ["VSTUDIO_HERE"])
    from layout import resolve_profile
    from vstudio import reframe as R, platform as P
    prof = resolve_profile(os.environ.get('PLATFORM') or None)
    if prof.h < prof.w or (prof.w, prof.h) != (1080, 1920):
        prof = resolve_profile(None)                 # the body is always 1080x1920; 3:4 is derived in compose
    tmp = sdr[:-4] + '.land.mp4'; os.replace(sdr, tmp)
    pl = R.plan(tmp, 1080, 1920, mode=os.environ.get('REFRAME_MODE', 'face'), safe=P.safe_box(prof), fallback='pad-blur')
    R.render(tmp, sdr, pl, encode_args=['-c:v', 'libx264', '-crf', '14', '-preset', 'medium', '-pix_fmt', 'yuv420p',
                                         *media.BT709, '-c:a', 'aac', '-b:a', '256k'])
    json.dump(pl, open(sdr[:-4] + '.crop.json', 'w')); os.remove(tmp)
    cw = pl.get('crop_w') if pl['mode_used'] in ('face', 'center') else None
    up = (1080 / cw if cw else 1.0) * up0
    rec.update(mode=pl['mode_used'], hit_rate=pl.get('hit_rate'), upscale=round(up, 3), stats=pl.get('stats'))
    print(f"landscape source -> 9:16 via reframe {pl['mode_used']} (face hit rate {pl.get('hit_rate')}, "
          f"crop {cw and round(cw)}px wide, x{up:.2f} upscale{': soft, compose caps the punch-in' if up > 1.3 else ''}); "
          "ORIENT=horizontal keeps it 16:9")
elif info['w'] < info['h'] and orient == 'horizontal':
    print("vertical source kept vertical; compose --platform youtube puts it on a blurred 16:9 fill")
import json
pj = os.path.join(os.path.dirname(os.path.abspath(sdr)), 'prep.json')
allp = json.load(open(pj)) if os.path.exists(pj) else {}
allp[os.path.basename(sdr)] = rec; json.dump(allp, open(pj, 'w'), indent=1)
media.extract_wav(sdr, a16, sr=16000, channels=1)
info = media.probe(sdr); print(f"{os.path.basename(sdr)}: {info['w']}x{info['h']} {info['fps']:.3f} fps {info['duration']:.1f}s")
PY
  python3 "$HERE/../asr.py" "$WORK/a$i.wav" "$WORK/a$i.json" ${PROMPT:+--prompt "$PROMPT"}
done
