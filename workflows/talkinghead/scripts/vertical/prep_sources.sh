#!/usr/bin/env bash
# Convert phone clips (iPhone HLG / Dolby Vision HDR, or plain SDR) to SDR 1080p H.264, extract audio,
# transcribe with word timestamps.
# usage: bash prep_sources.sh WORK_DIR clip1.MOV clip2.MOV ...   (clips are numbered 1..N in order)
# env PROMPT="术语 列表 ..."   whisper initial_prompt (fixes English terms in Chinese speech)
# env TONEMAP=avconvert|ffmpeg  force a tone-map backend (default: avconvert if present, else ffmpeg)
#
# Outputs per clip i: sdr$i.mp4, a48_$i.wav (48k stereo, for cutting), a$i.wav (16k mono), a$i.json (whisper)
set -euo pipefail
if [ $# -lt 2 ]; then sed -n '2,8p' "$0"; exit 1; fi
HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="$1"; shift; mkdir -p "$WORK"; i=0
BACKEND="${TONEMAP:-}"
if [ -z "$BACKEND" ]; then
  if command -v avconvert >/dev/null 2>&1; then BACKEND=avconvert; else BACKEND=ffmpeg; fi
fi

ffmpeg_sdr() {  # $1 src  $2 dst
  local trc vf fit
  trc=$(ffprobe -v error -select_streams v:0 -show_entries stream=color_transfer -of csv=p=0 "$1" || true)
  # fit inside 1080x1920 (portrait) or 1920x1080 (landscape); ffmpeg auto-applies the rotation tag first
  fit="scale='if(gt(iw,ih),1920,1080)':'if(gt(iw,ih),1080,1920)':force_original_aspect_ratio=decrease:force_divisible_by=2"
  if [ "$trc" = "arib-std-b67" ] || [ "$trc" = "smpte2084" ]; then
    if ffmpeg -hide_banner -filters 2>/dev/null | grep -q ' zscale '; then
      vf="zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p,$fit"
    elif ffmpeg -hide_banner -filters 2>/dev/null | grep -q ' libplacebo '; then
      vf="libplacebo=tonemapping=bt.2390:colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv:format=yuv420p,$fit"
    else
      echo "WARN: $1 is HDR ($trc) but this ffmpeg has neither zscale nor libplacebo; output will look washed out." >&2
      echo "      Install an ffmpeg built with --enable-libzimg, or run on macOS (avconvert)." >&2
      vf="format=yuv420p,$fit"
    fi
  else
    vf="format=yuv420p,$fit"
  fi
  ffmpeg -v error -y -i "$1" -vf "$vf" -c:v libx264 -crf 14 -preset medium \
    -color_primaries bt709 -color_trc bt709 -colorspace bt709 -c:a aac -b:a 256k "$2"
}

for SRC in "$@"; do
  i=$((i+1))
  if [ "$BACKEND" = "avconvert" ]; then
    # macOS: avconvert's H.264 preset tone-maps HLG/DV -> SDR correctly (and handles rotation)
    avconvert -s "$SRC" -p Preset1920x1080 -o "$WORK/sdr$i.mp4" --replace >/dev/null 2>&1
  else
    ffmpeg_sdr "$SRC" "$WORK/sdr$i.mp4"
  fi
  ffmpeg -v error -y -i "$WORK/sdr$i.mp4" -map 0:a:0 -ar 48000 -ac 2 "$WORK/a48_$i.wav"
  ffmpeg -v error -y -i "$WORK/sdr$i.mp4" -map 0:a:0 -ac 1 -ar 16000 "$WORK/a$i.wav"
  python3 "$HERE/../asr.py" "$WORK/a$i.wav" "$WORK/a$i.json" ${PROMPT:+--prompt "$PROMPT"}
  ffprobe -v error -show_entries stream=width,height,r_frame_rate -select_streams v -of compact "$WORK/sdr$i.mp4"
done
