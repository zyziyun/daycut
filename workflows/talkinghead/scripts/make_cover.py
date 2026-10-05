#!/usr/bin/env python3
"""Notes-board 小红书 cover: face visible, mini 记笔记 panels mirroring video panels + fun sticky,
rotated with shadow, kept inside the 4:3 center-crop safe area x[240,1680]. Also writes cover43.png preview.
Rendering is vstudio.cover.notes_cover (burned-subtitle bands covered SOLIDLY, panels in the persona
panel theme); the frame is grabbed frame-accurately with vstudio.media.grab_frame.
Usage: python3 make_cover.py work/config.py"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"): print(__doc__); sys.exit(0)
import importlib.util
from vstudio import cover, media

cfg = sys.argv[1] if len(sys.argv) > 1 else "config.py"
spec = importlib.util.spec_from_file_location("config", cfg); C = importlib.util.module_from_spec(spec); spec.loader.exec_module(C)
WORK, SRC, OUT = C.WORK, C.SRC, C.COVER_OUT

# COVER_EQ: optional ffmpeg eq on the grabbed frame. The cards are near-black, so a frame that
# looked fine in the video often reads as a dark cover once they are pasted on. Lift it here.
frame = media.grab_frame(SRC, float(C.COVER_FRAME_T), f"{WORK}/cover_frame.png", vf=getattr(C, "COVER_EQ", None))
# COVER_MUTE_BOTTOM=0 skips the solid band when the frame carries no burned-in sub; COVER_MUTE_TOP for 剪映
# exports that burn subtitles at the top. COVER_HEAD_X (detect_head.py) is a placement note for COVER_SPOTS.
img, img43 = cover.notes_cover(frame, panels=C.COVER_PANELS, fun=getattr(C, "COVER_FUN", None), kicker=getattr(C, "COVER_KICKER", None),
                               mute_bottom=getattr(C, "COVER_MUTE_BOTTOM", 150), mute_top=getattr(C, "COVER_MUTE_TOP", 0),
                               spots=getattr(C, "COVER_SPOTS", None))
img.save(OUT, quality=93)
img43.save(f"{WORK}/cover43.png")   # 4:3 center-crop preview (what 小红书 shows)
print(f"cover -> {OUT}  | 4:3 preview -> {WORK}/cover43.png (check the crop, not the full frame)")
