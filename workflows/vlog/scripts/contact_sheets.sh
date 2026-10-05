#!/usr/bin/env bash
# Make a thumbnail contact sheet per clip so you can SEE the footage and decide
# which windows are good (subject clearly framed, smooth move) vs bad (empty,
# shaky, approach/retreat tails, pocket shots).
#
# Usage:
#   contact_sheets.sh OUT_DIR EVERY_SEC CLIP1 [CLIP2 ...]
#   contact_sheets.sh work/sheets 4 footage/*.MP4
#
# One frame every EVERY_SEC seconds, tiled 5 across x 6 down (30 tiles = the first
# 30*EVERY_SEC seconds; raise EVERY_SEC for long takes). Read left->right,
# top->bottom: tile #1 ~= 0s, #2 ~= EVERY_SEC, ...  Portrait clips get portrait
# tiles. Many Homebrew ffmpeg builds lack drawtext, so timestamps are NOT burned
# in; if yours has it, append
#   ,drawtext=text='%{pts\:hms}':fontcolor=yellow:fontsize=20:x=5:y=5
# after the scale filter.
set -euo pipefail
if [ $# -lt 3 ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
  sed -n '2,16p' "$0"; exit 0
fi
OUT="$1"; EVERY="$2"; shift 2
mkdir -p "$OUT"
for f in "$@"; do
  base=$(basename "$f"); base="${base%.*}"
  echo "sheet: $base"
  # landscape tiles 400x224, portrait 224x400 (even sizes for yuv420) (phone clips); rotation metadata is honoured
  wh=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height:stream_side_data=rotation -of csv=p=0 "$f" | tr '\n' ',')
  w=$(echo "$wh" | cut -d, -f1); h=$(echo "$wh" | cut -d, -f2); rot=$(echo "$wh" | cut -d, -f3 | tr -d '-')
  if [ "${rot:-0}" = "90" ] || [ "${rot:-0}" = "270" ]; then t=$w; w=$h; h=$t; fi
  if [ "$h" -gt "$w" ]; then TW=224; TH=400; else TW=400; TH=224; fi
  ffmpeg -y -hide_banner -loglevel error -i "$f" \
    -vf "fps=1/${EVERY},scale=${TW}:${TH}:force_original_aspect_ratio=decrease,pad=${TW}:${TH}:(ow-iw)/2:(oh-ih)/2:color=black,tile=5x6:padding=4:color=black" \
    -frames:v 1 "$OUT/${base}_sheet.jpg" &
done
wait
echo "done -> $OUT"
