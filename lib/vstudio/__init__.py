"""vstudio: the shared library behind every video-studio workflow.

Import submodules directly (``from vstudio import media, cut``); this package imports nothing
itself, so heavy optional dependencies (cv2, mediapipe, whisper, TTS engines) load only when used.

Core (audio/video pipeline)
  config   fonts, models, creator persona (``font()``, ``model()``, ``persona()``, ``xhs_len()``)
  media    ffmpeg/ffprobe discovery, run, probe, extract_wav, grab_frame, contact_sheet,
           HDR->SDR, atempo_chain, delivery_args, retag_bt709
  audio    two-pass loudnorm, stems, RMS envelopes, silence spans, music bed ducking, pitch shift, SFX
  asr      cached whisper transcription with word timestamps (mlx -> faster -> OpenAI), term fixes
  cut      TimeMap, tighten (pause squeeze), find_cuts/split_window (disfluencies), suggest_fillers,
           cut_segments (frame-exact), xfade_assemble (muted-pad dissolves)
  subs     Cue, wrap_cjk / balanced_wrap, highlight markup, SRT/ASS writers, bilingual, retime
  tts      synth() via OpenAI / Kokoro / Edge with a content-addressed cache

Face and look
  face     MediaPipe landmarker + landmark index sets
  mls      rigid Moving-Least-Squares warp
  retouch  portrait retouch (slim, eyes, de-shine, skin, makeup, body)

Visual (overlays, covers, HTML render, publish copy) - see each module's docstring:
  draw, overlays, cover, render, publish
"""
