"""vstudio: the shared library behind every video-studio workflow.

Import submodules directly (``from vstudio import media, cut``); this package imports nothing
itself, so heavy optional dependencies (cv2, mediapipe, whisper, TTS engines) load only when used. The one
exception: with $VSTUDIO_H264_ENCODER (not libx264) / $VSTUDIO_FFMPEG / $VSTUDIO_FFPROBE set it installs the
small ``vstudio.h264`` subprocess hook (one encoder and ffmpeg for every script).

Core (audio/video pipeline)
  config   fonts, models, creator persona (``font()``, ``model()``, ``persona()``, ``xhs_len()``)
  media    ffmpeg/ffprobe discovery, run, probe, extract_wav, grab_frame, contact_sheet,
           HDR->SDR, atempo_chain, delivery_args, retag_bt709
  audio    two-pass loudnorm, stems, RMS envelopes, silence spans, music bed ducking, pitch shift, SFX
  asr      cached whisper transcription with word timestamps (mlx -> faster -> OpenAI | self-hosted server), term fixes
  cut      TimeMap, tighten (pause squeeze), find_cuts/split_window (disfluencies), suggest_fillers,
           cut_segments (frame-exact), xfade_assemble (muted-pad dissolves)
  subs     Cue, wrap_cjk / balanced_wrap, highlight markup, SRT/ASS writers, bilingual, retime
  tts      synth() via OpenAI / Kokoro / Edge / clone / self-hosted server / ElevenLabs, content-addressed cache
  llm      complete(): one LLM interface (API providers, local servers, Claude Code / Codex CLIs, none), routing,
           JSON repair, cost, fallback chains; ``python -m vstudio.llm providers`` (references/PROVIDERS.md)
  entities named-entity verification of transcripts (CLDR place names, glossary / model spellings)
  messages engine text as code + params + message / message_zh (references/MESSAGES.md)

Face and look
  face     MediaPipe landmarker + landmark index sets
  mls      rigid Moving-Least-Squares warp
  retouch  portrait retouch (slim, eyes, de-shine, skin, makeup, body)

Visual (overlays, covers, HTML render, publish copy) - see each module's docstring:
  draw, overlays, cover, render, publish

Lessons, interviews, bilingual captions
  lesson     teaching-point planner (phrase / vocab / concept / correction), recap, study notes (md / PDF)
  qa         speakers, question / answer pairs, tight answers, role labels
  bilingual  caption translation (llm task ``translate``, glossary), mono / bilingual / translated, SRT / VTT
  clipkit    planned clips -> masters per canvas (cards, header, term cards, layouts, masks) -> export + firstpass
  avsync     offset between two recordings of one session (screen share + camera)

Effects
  effects  declarative registry of every effect (engines, entry points, params + feel, energy,
           duration, max uses, pitfalls); generates references/EFFECTS.md (``--write-md``)
  xfade    cross-engine transition bridge: one name -> HyperFrames GSAP (``hf_transitions``),
           ffmpeg xfade (``ffmpeg_transition`` / ``ffmpeg_expr``), numpy per-frame (``blend``)
"""
__version__ = "0.2.0"

import os as _os

if _os.environ.get("VSTUDIO_H264_ENCODER") or _os.environ.get("VSTUDIO_FFMPEG") or _os.environ.get("VSTUDIO_FFPROBE"):
    from . import h264 as _h264      # one encoder / ffmpeg for every subprocess (see vstudio/h264.py)

    if _h264.wanted():
        _h264.install()
