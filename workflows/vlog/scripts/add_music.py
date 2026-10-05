#!/usr/bin/env python3
"""Mux a music track onto a vlog master: loop to fill, fade in/out, two-pass normalize to
the delivery loudness (persona audio.loudness_lufs, default -14 LUFS), and re-mux
WITHOUT re-encoding the picture (fast, lossless video).

    python3 add_music.py vlog_master.mp4 music/Track.mp3 vlog_music.mp4
    python3 add_music.py vlog_master.mp4 music/Track.mp3 vlog_music.mp4 --fade 2 --ambient-db -12

--ambient-db keeps the master's own sound (built with "ambient_audio": true) under
the music: the ambience is set to (music bed loudness + AMBIENT_DB) LUFS, so -12 means
"12 dB under the music" whatever the raw levels. Fades shape the music; the ambience
already fades out with the master.

Built on vstudio.audio.mix_bed (loop + fades + stem levels) and audio.loudnorm_2pass
(linear two-pass loudnorm, via mix_bed's ``lufs``).
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, math, os, tempfile

from vstudio import audio, media
from vstudio.config import persona


def main():
    p = persona()
    ap = argparse.ArgumentParser(description="Loop/trim/fade/loudnorm a music bed onto a video (video stream copied).")
    ap.add_argument("video")
    ap.add_argument("track")
    ap.add_argument("out")
    ap.add_argument("--fade", type=float, default=2.0, help="music fade-in and fade-out seconds (default 2)")
    ap.add_argument("--lufs", type=float, default=None,
                    help="target loudness (default: --platform profile, else persona audio.loudness_lufs, -14)")
    ap.add_argument("--platform", help="platform[:orientation]: loudness target + length check from vstudio.platform")
    ap.add_argument("--ambient-db", type=float, default=None,
                    help="keep the video's own audio this many dB under the music bed (e.g. -12)")
    ap.add_argument("--track-start", type=float, default=0.0, help="skip this many seconds into the track")
    a = ap.parse_args()
    if a.lufs is None:
        if a.platform:
            from vstudio import platform as P
            prof = P.profile(a.platform)
            a.lufs = float(prof.loudness["lufs"])
            for w in P.check_length(prof, media.probe(a.video)["duration"]):
                print("[warn]", w)
        else:
            a.lufs = float((p.get("audio") or {}).get("loudness_lufs", -14))

    info = media.probe(a.video)
    dur = info["duration"]
    print(f"video={dur:.2f}s fade={a.fade}s target={a.lufs} LUFS")
    with tempfile.TemporaryDirectory(prefix="vlog_music_") as tmp:
        bed_src, amb_gain = a.video, None
        if a.ambient_db is not None and info["has_audio"]:
            music_lufs = float((p.get("audio") or {}).get("music_lufs", -30))
            m = audio.measure_loudness(a.video)
            amb_gain = (music_lufs + a.ambient_db - m["input_i"]) if math.isfinite(m["input_i"]) else 0.0
        else:
            if a.ambient_db is not None:
                print("[warn] video has no audio stream; --ambient-db ignored")
            # music only: a silent "voice" of the video's length sets the bed length; gain 0 = no ducking
            bed_src = audio.silence(dur, os.path.join(tmp, "silence.wav"))
            amb_gain = 0.0
        mix = os.path.join(tmp, "mix.wav")
        audio.mix_bed(bed_src, a.track, mix, ambient_db=amb_gain, fade_in=a.fade, fade_out=a.fade,
                      music_start=a.track_start, lufs=a.lufs)
        br = str((p.get("export") or {}).get("audio_bitrate", "192k"))
        media.run(["ffmpeg", "-y", "-i", a.video, "-i", mix, "-map", "0:v:0", "-map", "1:a:0",
                   "-c:v", "copy", "-c:a", "aac", "-b:a", br, "-ar", str(audio.SR), "-ac", "2",
                   "-t", f"{dur:.3f}", "-movflags", "+faststart", a.out])
    print(f"DONE -> {a.out}")


if __name__ == "__main__":
    main()
