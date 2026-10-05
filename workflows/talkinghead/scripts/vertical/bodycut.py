"""Shared helper: keep a list of (start, end) ranges of a body video+audio, frame-exact."""
import sys, pathlib; sys.path[:0] = [str(pathlib.Path(__file__).resolve().parents[4] / "lib"), str(pathlib.Path(__file__).resolve().parents[1])]
import os, subprocess, numpy as np, soundfile as sf
from concurrent.futures import ThreadPoolExecutor
F = 30
def q(t): return round(t * F) / F
def remap(keep):
    """returns f(old_t) -> new_t for a sorted list of kept (s, e) ranges."""
    def m(t):
        acc = 0.0
        for s, e in keep:
            if t < s: return round(acc, 3)
            if t < e: return round(acc + t - s, 3)
            acc += e - s
        return round(acc, 3)
    return m
def cut_body(in_v, in_a, keep, out_v, out_a, tmp='segtmp'):
    os.makedirs(tmp, exist_ok=True)
    def job(k_ab):
        k, (s, e) = k_ab; a = round(s * F); n = round(e * F) - a; out = f'{tmp}/{k:04d}.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', in_v, '-an', '-vf', f"trim=start_frame={a}:end_frame={a+n},setpts=PTS-STARTPTS",
                        '-c:v', 'libx264', '-crf', '12', '-preset', 'fast', '-pix_fmt', 'yuv420p', '-video_track_timescale', '30000', out], check=True)
        return out
    with ThreadPoolExecutor(6) as ex: outs = list(ex.map(job, enumerate(keep)))
    open(f'{tmp}/list.txt', 'w').write(''.join(f"file '{os.path.basename(o)}'\n" for o in outs))
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', f'{tmp}/list.txt', '-c', 'copy', out_v], check=True)
    x, sr = sf.read(in_a); parts = []; fd = int(0.01 * sr)
    for s, e in keep:
        y = x[round(s * F) * sr // F:round(e * F) * sr // F].copy(); r = np.linspace(0, 1, fd)[:, None]
        y[:fd] *= r; y[-fd:] *= r[::-1]; parts.append(y)
    sf.write(out_a, np.concatenate(parts), sr, subtype='PCM_16')
    return sum(e - s for s, e in keep)
