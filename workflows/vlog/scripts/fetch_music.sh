#!/usr/bin/env bash
# Download CC-BY 4.0 music (Kevin MacLeod / incompetech.com) by exact track title,
# and write the credit lines you MUST paste into the post description to
# OUT_DIR/ATTRIBUTION.txt (one line per downloaded track, de-duplicated).
#
# Why Incompetech: it serves static MP3 URLs that curl can fetch headlessly
# (Pixabay audio is JS-loaded and cannot be curl'd).
# Alternative (no attribution file needed if the catalog licence says so - check it):
#   npx hyperframes media-use resolve --type bgm     (HyperFrames / HeyGen catalog; see WORKFLOW.md)
#
# Usage:
#   fetch_music.sh OUT_DIR "Track Name" ["Another Track" ...]
#   fetch_music.sh music "Atlantean Twilight" "Pamgaea"
#
# Vibe -> track cheatsheet (verified direct-downloadable at time of writing):
#   cheerful / playful 欢快      : Carefree, Ukulele, Sunday Plans
#   adventurous / free 自由      : Pamgaea, Ascending the Vale, Rynos Theme
#   cinematic uplift 上扬电影感  : Atlantean Twilight, Constance, Heartwarming
#   epic / passionate 激情史诗   : Inspired, Crossing the Chasm, Rising Tide
#   calm / ambient 安静          : Dreamer, Meditation Impromptu 02, Healing
# Browse more at https://incompetech.com/music/royalty-free/music.html
set -euo pipefail
if [ $# -lt 2 ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
  sed -n '2,22p' "$0"; exit 0
fi
OUT="$1"; shift
mkdir -p "$OUT"
ATTR="$OUT/ATTRIBUTION.txt"
touch "$ATTR"
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
fail=0
for name in "$@"; do
  enc=$(printf '%s' "$name" | sed 's/ /%20/g')
  safe=$(printf '%s' "$name" | tr ' ' '_')
  url="https://incompetech.com/music/royalty-free/mp3-royaltyfree/${enc}.mp3"
  out="$OUT/${safe}_KevinMacLeod.mp3"
  code=$(curl -s -A "$UA" -L -o "$out" -w "%{http_code} %{size_download}" "$url" || echo "000 0")
  http=${code%% *}; size=${code##* }; size=${size%.*}
  if [ "$http" = "200" ] && [ "${size:-0}" -gt 100000 ]; then
    echo "OK   $name -> $out (${size} bytes)"
    line="Music: \"$name\" by Kevin MacLeod (incompetech.com), licensed under CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)"
    grep -qxF "$line" "$ATTR" || echo "$line" >> "$ATTR"
  else
    echo "FAIL $name (http $http, $size bytes) - check the exact title/spelling"
    rm -f "$out"; fail=1
  fi
done
echo "credits -> $ATTR (paste into the post description)"
exit $fail
