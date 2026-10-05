#!/usr/bin/env python3
"""Notes-board 小红书 cover: face visible, mini 记笔记 panels mirroring video panels + fun sticky,
rotated with shadow, kept inside the 4:3 center-crop safe area x[240,1680]. Also writes cover43.png preview.
Rendering is vstudio.cover.notes_cover (burned-subtitle bands covered SOLIDLY, panels in the persona
panel theme); the frame is grabbed frame-accurately with vstudio.media.grab_frame.
Per platform (--platform, repeatable; else config PLATFORM, else persona default horizontal): the 16:9 design is
re-fitted to platform.cover_size (YouTube 1280x720, B站 1146x717 16:10, ...) as <COVER_OUT stem>.<platform>.jpg,
with a .feed.jpg centre-crop preview where the feed crops (小红书 4:3). The default 小红书 horizontal writes
COVER_OUT + work/cover43.png exactly as before.
Usage: python3 make_cover.py work/config.py [--platform youtube --platform bilibili]"""
import sys, pathlib; sys.path[:0] = [str(pathlib.Path(__file__).resolve().parents[3] / "lib"), str(pathlib.Path(__file__).resolve().parent / "vertical")]
if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"): print(__doc__); sys.exit(0)
import importlib.util, os
from vstudio import cover, media
from vstudio import platform as P
from vstudio.export import fit_cover
from layout import resolve_profile

plats = []
while "--platform" in sys.argv:
    i = sys.argv.index("--platform"); plats.append(sys.argv[i + 1]); del sys.argv[i:i + 2]

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
for sp in plats or ([C.PLATFORM] if getattr(C, "PLATFORM", None) else []):
    prof = resolve_profile(sp, natural="horizontal"); size = P.cover_size(prof)
    if prof.h > prof.w:
        print(f"{prof.key}: vertical cover - use scripts/vertical/cover.py or workflows/cover (3:4 / 9:16 split cover)"); continue
    if size == img.size and prof.cover.get("feed_crop") == "4:3":
        continue                                  # the default 小红书 cover written above
    out = f"{os.path.splitext(OUT)[0]}.{prof.name}-{prof.orientation}.jpg"
    im = fit_cover(img, size)
    q = 92
    im.save(out, quality=q)
    while prof.cover.get("max_bytes") and os.path.getsize(out) > prof.cover["max_bytes"] and q > 60:
        q -= 8; im.save(out, quality=q)
    fc = prof.cover.get("feed_crop"); note = ""
    if fc:
        x0, y0, x1, y1 = P.cover_title_safe(prof)
        aw, ah = (float(v) for v in fc.split(":")); W_, H_ = size
        cw = min(W_, H_ * aw / ah); im.crop((int((W_ - cw) / 2), 0, int((W_ + cw) / 2), H_)).save(out[:-4] + ".feed.jpg", quality=90)
        note = f" + {fc} feed preview"
    print(f"{prof.key}: {size[0]}x{size[1]} -> {out}{note}")
