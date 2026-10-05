#!/usr/bin/env python3
"""Record animated slides (?export=<key>&animate=1) to H.264 MP4 with Playwright.

  python3 record_slides.py work/slides.html work/slides/ 06_bars:3.4 09_attn:4.0 13_stack:4.2 [--size 1080x1080]

Each shot is KEY:SECONDS (how long to record). Output: <out>/slide_<key>.mp4 (yuv420p, CRF from
persona export.crf, faststart). Needs `pip install playwright && playwright install chromium`.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import argparse
import asyncio
import shutil
import subprocess
import tempfile

from render_html import inject_persona, stage_fonts
from vstudio.config import persona


async def record_one(p, url, key, dur, w, h, tmp, out, crf, fps):
    work = tmp / key
    shutil.rmtree(work, ignore_errors=True); work.mkdir(parents=True)
    browser = await p.chromium.launch()
    ctx = await browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=1,
                                    record_video_dir=str(work), record_video_size={"width": w, "height": h})
    page = await ctx.new_page()
    await page.goto(f"{url}?export={key}&animate=1")
    await page.wait_for_timeout(int(dur * 1000))
    await ctx.close(); await browser.close()
    webms = list(work.glob("*.webm"))
    if not webms:
        print(f"  !! no recording for {key}"); return None
    mp4 = out / f"slide_{key}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(webms[0]), "-r", str(fps),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", str(crf), "-preset", "slow",
                    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                    "-movflags", "+faststart", str(mp4)], check=True)
    print(f"  {mp4.name}  ({mp4.stat().st_size // 1024} KB)")
    return mp4


async def run(a):
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise SystemExit("pip install playwright && playwright install chromium")
    w, h = (int(x) for x in a.size.lower().split("x"))
    html = pathlib.Path(a.html).resolve()
    stage_fonts(html.parent)
    page_file = html if a.no_persona else inject_persona(html)
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    crf = persona().get("export", {}).get("crf", 18)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="slide_rec_"))
    try:
        async with async_playwright() as p:
            for shot in a.shots:
                key, _, dur = shot.partition(":")
                print(f"recording {key} for {dur or 4}s")
                await record_one(p, page_file.as_uri(), key, float(dur or 4), w, h, tmp, out, crf, a.fps)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        if page_file != html:
            page_file.unlink(missing_ok=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("html"); ap.add_argument("out")
    ap.add_argument("shots", nargs="+", help="KEY:SECONDS, e.g. 06_bars:3.4")
    ap.add_argument("--size", default="1080x1080")
    ap.add_argument("--fps", type=int, default=25, help="output fps (Playwright records ~25)")
    ap.add_argument("--no-persona", action="store_true")
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
