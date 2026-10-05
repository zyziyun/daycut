#!/usr/bin/env python3
"""Rank cover-frame candidates: big smile, eyes open, face centered
(vstudio.cover.score_frames: score = mouthSmile - 1.5*eyeBlink - |cx-0.5|, every 5th frame, picks >= 2 s apart).
usage: python3 pick_cover_frame.py body3_rt.mp4 [top_n]  -> prints times + writes cover_candidates.jpg"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4] / "lib"))
if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"): print(__doc__); sys.exit(0)
from vstudio import cover
src = sys.argv[1]; top = int(sys.argv[2]) if len(sys.argv) > 2 else 6
picks = cover.score_frames(src, top_n=top)
for p in picks:
    print(f"t={p['t']:.3f}  frame={p['frame']}  score={p['score']:.3f}")
tiles = [p['image'][200:1640] for p in picks if p['image'] is not None]   # the 3:4 cover band of a 1080x1920 frame
if tiles:
    cover.contact_sheet(tiles, labels=[f"{p['t']:.2f}" for p in picks], cols=len(tiles), tile_w=270, bgr=True).save('cover_candidates.jpg', quality=88)
    print('wrote cover_candidates.jpg (use frame-index seek, not -ss, for the exact frame)')
else:
    print('no face found')
