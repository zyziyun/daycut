#!/usr/bin/env bash
# Render a promo-recut HyperFrames project and make it upload-ready (shell entry point for export.py):
#   HyperFrames render -> two-pass loudnorm to persona audio.loudness_lufs (default -14 LUFS, TP -1.5)
#   -> BT.709 colour tags written into the H.264/HEVC stream (no video re-encode) -> +faststart.
#
# Usage (from the project dir):
#   bash $VSTUDIO/workflows/promo-recut/scripts/export.sh promo my-promo.mp4 [draft|looks|delivery]
#   bash $VSTUDIO/workflows/promo-recut/scripts/export.sh --skip-render promo/renders/raw.mp4 my-promo.mp4
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -lt 2 ]]; then
  sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0
fi
exec python3 "$HERE/export.py" "$@"
