#!/usr/bin/env bash
# Render a promo-recut HyperFrames project and make it upload-ready:
#   HyperFrames render -> two-pass loudnorm to persona audio.loudness_lufs (default -14 LUFS, TP -1.5)
#   -> BT.709 colour tags written into the H.264 stream (no video re-encode) -> +faststart.
#
# Usage (from the project dir):
#   bash $VSTUDIO/workflows/promo-recut/scripts/export.sh promo my-promo.mp4 [draft|looks|delivery]
#   bash $VSTUDIO/workflows/promo-recut/scripts/export.sh --skip-render promo/renders/raw.mp4 my-promo.mp4
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB="$HERE/../../../lib"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -lt 2 ]]; then
  sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0
fi
command -v ffmpeg >/dev/null || { echo "ffmpeg not found"; exit 1; }

if [[ "$1" == "--skip-render" ]]; then
  RAW="$2"; OUT="$3"
else
  PROMO="$1"; OUT="$2"; Q="${3:-delivery}"
  command -v npx >/dev/null || { echo "npx (Node) not found"; exit 1; }
  mkdir -p "$PROMO/renders"
  RAW="$PROMO/renders/_raw.mp4"
  ( cd "$PROMO" && npx hyperframes render --quality "$Q" --output "renders/_raw.mp4" )
fi

LUFS=$(PYTHONPATH="$LIB" python3 -c "from vstudio.config import persona; print((persona().get('audio') or {}).get('loudness_lufs', -14))" 2>/dev/null || echo -14)
echo "loudnorm target: $LUFS LUFS"

# pass 1: measure
MEAS=$(ffmpeg -hide_banner -nostats -i "$RAW" -vn -af "loudnorm=I=$LUFS:TP=-1.5:LRA=11:print_format=json" -f null - 2>&1 | \
       python3 -c "import sys,re,json; t=sys.stdin.read(); print(json.dumps(json.loads(t[t.rindex('{'):t.rindex('}')+1])))")
read -r MI MTP MLRA MTH OFF < <(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d['input_i'], d['input_tp'], d['input_lra'], d['input_thresh'], d['target_offset'])" "$MEAS")

# pass 2: apply + bt709 tags (bitstream filter, video copied) + faststart
ffmpeg -y -v error -i "$RAW" \
  -map 0:v:0 -map 0:a:0 -c:v copy \
  -bsf:v "h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1:video_full_range_flag=0" \
  -af "loudnorm=I=$LUFS:TP=-1.5:LRA=11:measured_I=$MI:measured_TP=$MTP:measured_LRA=$MLRA:measured_thresh=$MTH:offset=$OFF:linear=true,aresample=48000" \
  -c:a aac -b:a 192k -ar 48000 -movflags +faststart "$OUT"

echo "-> $OUT"
ffprobe -v error -show_entries stream=codec_name,width,height,color_primaries,color_transfer,color_space,sample_rate \
  -show_entries format=duration -of compact "$OUT"
ffmpeg -hide_banner -nostats -i "$OUT" -vn -af ebur128=peak=true -f null - 2>&1 | grep -E "^\s+(I|True peak|Peak):" | head -3 || true
