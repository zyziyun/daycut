#!/usr/bin/env bash
# video-studio installer: Python deps + open-licensed fonts and models into ~/.cache/video-studio.
# Re-runnable; skips files that already exist. Override the location with VSTUDIO_CACHE.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
CACHE="${VSTUDIO_CACHE:-$HOME/.cache/video-studio}"
mkdir -p "$CACHE/fonts" "$CACHE/models"

fetch() {  # url dest
  if [ -s "$2" ]; then echo "  ✓ $(basename "$2")"; return; fi
  echo "  ↓ $(basename "$2")"; curl -fsSL "$1" -o "$2.part" && mv "$2.part" "$2"
}

echo "fonts (OFL) -> $CACHE/fonts"
fetch https://github.com/notofonts/noto-cjk/raw/main/Sans/SubsetOTF/SC/NotoSansSC-Regular.otf "$CACHE/fonts/NotoSansSC-Regular.otf"
fetch https://github.com/notofonts/noto-cjk/raw/main/Sans/SubsetOTF/SC/NotoSansSC-Bold.otf "$CACHE/fonts/NotoSansSC-Bold.otf"
fetch "https://github.com/google/fonts/raw/main/ofl/stixtwotext/STIXTwoText%5Bwght%5D.ttf" "$CACHE/fonts/STIXTwoText-Regular.ttf"
fetch "https://github.com/google/fonts/raw/main/ofl/stixtwotext/STIXTwoText-Italic%5Bwght%5D.ttf" "$CACHE/fonts/STIXTwoText-Italic.ttf"
fetch https://github.com/JetBrains/JetBrainsMono/raw/master/fonts/ttf/JetBrainsMono-Regular.ttf "$CACHE/fonts/JetBrainsMono-Regular.ttf"
fetch https://github.com/JetBrains/JetBrainsMono/raw/master/fonts/ttf/JetBrainsMono-Bold.ttf "$CACHE/fonts/JetBrainsMono-Bold.ttf"

echo "models (Apache-2.0, MediaPipe) -> $CACHE/models"
fetch https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task "$CACHE/models/face_landmarker.task"
fetch https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_segmenter/float16/latest/selfie_segmenter.tflite "$CACHE/models/selfie_segmenter.tflite"

if [ "${SKIP_PIP:-0}" != "1" ]; then
  echo "python deps"
  python3 -m pip install -q -r "$HERE/requirements.txt"
  # Apple Silicon gets the fast local whisper; elsewhere faster-whisper is used.
  if [ "$(uname -s)-$(uname -m)" = "Darwin-arm64" ]; then python3 -m pip install -q mlx-whisper; else python3 -m pip install -q faster-whisper; fi
fi

command -v ffmpeg >/dev/null || echo "!! ffmpeg not found - install it (brew install ffmpeg / apt install ffmpeg)"
command -v npx >/dev/null || echo "!! node/npx not found - HyperFrames workflows (explainer, promo-recut) need Node 18+"
[ -f "$HERE/persona.local.yaml" ] || echo "tip: cp persona.example.yaml persona.local.yaml and fill in your brand/voice"
echo "done. export PYTHONPATH=\"$HERE/lib:\$PYTHONPATH\"   (or: pip install -e $HERE)"
