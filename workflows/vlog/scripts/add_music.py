#!/usr/bin/env python3
"""Mux a music track onto a vlog master: loop to fill, fade in/out, normalize to
the delivery loudness (persona audio.loudness_lufs, default -14 LUFS), and
re-mux WITHOUT re-encoding the picture (fast, lossless video).

    python3 add_music.py vlog_master.mp4 music/Track.mp3 vlog_music.mp4
    python3 add_music.py vlog_master.mp4 music/Track.mp3 vlog_music.mp4 --fade 2 --ambient-db -12

--ambient-db keeps the master's own sound (built with "ambient_audio": true) under
the music at that gain (dB relative to the music bed) instead of replacing it.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json, subprocess

from vstudio.config import persona


def probe(path):
    d = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
                                  capture_output=True, text=True, check=True).stdout)
    return float(d["format"]["duration"]), any(s.get("codec_type") == "audio" for s in d["streams"])


def main():
    p = persona()
    ap = argparse.ArgumentParser(description="Loop/trim/fade/loudnorm a music bed onto a video (video stream copied).")
    ap.add_argument("video")
    ap.add_argument("track")
    ap.add_argument("out")
    ap.add_argument("--fade", type=float, default=2.0, help="fade-in and fade-out seconds (default 2)")
    ap.add_argument("--lufs", type=float, default=float((p.get("audio") or {}).get("loudness_lufs", -14)))
    ap.add_argument("--ambient-db", type=float, default=None,
                    help="mix the video's own audio under the music at this gain in dB (e.g. -12)")
    ap.add_argument("--track-start", type=float, default=0.0, help="skip this many seconds into the track")
    a = ap.parse_args()

    dur, has_audio = probe(a.video)
    fout = max(0.0, dur - a.fade)
    print(f"video={dur:.2f}s fade={a.fade}s fade_out_start={fout:.2f}s target={a.lufs} LUFS")
    tail = (f"loudnorm=I={a.lufs}:TP=-1.5:LRA=11,"
            f"afade=t=in:st=0:d={a.fade},afade=t=out:st={fout:.3f}:d={a.fade}")
    if a.ambient_db is not None and has_audio:
        fc = (f"[1:a]atrim=start={a.track_start},asetpts=PTS-STARTPTS[m];"
              f"[0:a]volume={a.ambient_db}dB[amb];"
              f"[m][amb]amix=inputs=2:duration=first:normalize=0,atrim=0:{dur:.3f},{tail}[aout]")
    else:
        if a.ambient_db is not None:
            print("[warn] video has no audio stream; --ambient-db ignored")
        fc = f"[1:a]atrim=start={a.track_start},asetpts=PTS-STARTPTS,atrim=0:{dur:.3f},{tail}[aout]"
    br = str((p.get("export") or {}).get("audio_bitrate", "192k"))
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-stats",
           "-i", a.video, "-stream_loop", "-1", "-i", a.track,
           "-filter_complex", fc, "-map", "0:v", "-map", "[aout]",
           "-c:v", "copy", "-c:a", "aac", "-b:a", br, "-shortest", "-movflags", "+faststart", a.out]
    subprocess.run(cmd, check=True)
    print(f"DONE -> {a.out}")


if __name__ == "__main__":
    main()
