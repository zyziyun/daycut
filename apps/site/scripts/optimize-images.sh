#!/usr/bin/env bash
# Re-generate optimised WebP + AVIF images in public/img from assets/demos/*.jpg.
# Needs ImageMagick (magick), cwebp and avifenc (brew install imagemagick webp libavif).
# Output is committed, so you only need to run this when the source images change.
set -euo pipefail
cd "$(dirname "$0")/.."
SRC=assets/demos
OUT=public/img
mkdir -p "$OUT"
tmp=$(mktemp -d)

enc() { # $1 = input png/jpg, $2 = output basename (no ext)
  cwebp -quiet -q 78 -m 6 "$1" -o "$OUT/$2.webp"
  avifenc -q 55 -s 4 "$1" "$OUT/$2.avif" >/dev/null
}

# Contact sheets: 800 and 1600 px wide.
for name in talkinghead longform-slices explainer-vertical; do
  for w in 800 1600; do
    magick "$SRC/$name.jpg" -resize "${w}x>" -strip "$tmp/$name-$w.png"
    enc "$tmp/$name-$w.png" "$name-$w"
  done
done

# The six-frame strip, cut into one tile per frame (proof grid, hero, board thumbnails).
for i in 0 1 2 3 4 5; do
  magick "$SRC/strip.jpg" -crop "196x256+$((i*200+2))+0" +repage -strip "$tmp/frame-$((i+1)).png"
  enc "$tmp/frame-$((i+1)).png" "frame-$((i+1))"
done

# Open Graph image (public/img/og.png): scripts/brand.mjs

rm -rf "$tmp"
ls -la "$OUT" | awk '{print $5, $9}'
