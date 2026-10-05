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
# top->bottom: each tile is labelled with its source time (tile n = (n-1)*EVERY_SEC).
# Portrait clips get portrait tiles (rotation metadata honoured).
# Thin wrapper over vstudio.media.contact_sheet (PIL labels, no drawtext needed).
set -euo pipefail
if [ $# -lt 3 ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
  sed -n '2,14p' "$0"; exit 0
fi
LIB="$(cd "$(dirname "$0")/../../.." && pwd)/lib"
PYTHONPATH="$LIB${PYTHONPATH:+:$PYTHONPATH}" python3 - "$@" <<'PY'
import os, sys
from concurrent.futures import ThreadPoolExecutor
from vstudio import media

out, every, clips = sys.argv[1], float(sys.argv[2]), sys.argv[3:]
os.makedirs(out, exist_ok=True)

def sheet(f):
    i = media.probe(f)
    w, h = (i["h"], i["w"]) if abs(i["rotation"]) % 180 == 90 else (i["w"], i["h"])
    base = os.path.splitext(os.path.basename(f))[0]
    dst = os.path.join(out, f"{base}_sheet.jpg")
    media.contact_sheet(f, dst, every=every, cols=5, max_frames=30, start=0,
                        thumb_w=224 if h > w else 400)
    print(f"sheet: {base}", flush=True)

with ThreadPoolExecutor(max_workers=4) as ex:
    list(ex.map(sheet, clips))
print(f"done -> {out}")
PY
