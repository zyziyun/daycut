#!/usr/bin/env python3
"""Optional step 4b: re-record a live web demo (Playwright native video) to replace a stale
or low-res screen-grab. The original narration audio is kept; only the demo video is swapped
(build_timeline uses demo.rec for the keep-list segments listed in demo.keep_idx).

Pacing: page intro -> visible typing of demo.prompt -> click demo.submit_text -> follow the
streaming output -> wait until the page text stops growing -> slow scroll through the result
to fill ~demo.target_seconds -> hold. Timestamped marks are printed for aligning cuts.

Config: demo.url, demo.prompt, demo.input_selector (textarea), demo.submit_text (Ask),
demo.done_markers ([...lowercase strings]), demo.viewport [w,h], demo.target_seconds.
Set demo.rec to the printed VIDEO path afterwards.

Usage: python3 record_demo.py work/config.py
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import time

import _lfc
from vstudio import media

cfg, _ = _lfc.load(description=__doc__)
URL = cfg.get("demo.url") or sys.exit("config.demo.url is not set")
PROMPT = cfg.get("demo.prompt", "")
SEL = cfg.get("demo.input_selector", "textarea")
SUBMIT = cfg.get("demo.submit_text", "Ask")
MARKERS = [m.lower() for m in cfg.get("demo.done_markers", ["token", "summary"])]
W, H = cfg.get("demo.viewport", [1856, 1016])
TARGET = cfg.get("demo.target_seconds", 100)
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("pip install playwright && python3 -m playwright install chromium")

t0 = time.time()


def mark(msg):
    print(f"[{time.time() - t0:6.1f}s] {msg}", flush=True)


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": W, "height": H}, record_video_dir="demo_video",
                        record_video_size={"width": W, "height": H})
    pg = ctx.new_page()
    pg.goto(URL, wait_until="networkidle", timeout=60000)
    mark("page loaded")
    pg.wait_for_timeout(4000)
    if PROMPT:
        box = pg.locator(SEL).first
        box.click()
        pg.wait_for_timeout(800)
        box.type(PROMPT, delay=45)
        mark("prompt typed")
        pg.wait_for_timeout(1500)
        pg.locator("button", has_text=SUBMIT).first.click()
        mark("submitted")
        for _ in range(240):  # up to 120 s
            pg.wait_for_timeout(500)
            pg.mouse.wheel(0, 250)
            if any(k in pg.inner_text("body").lower() for k in MARKERS):
                break
        mark("completion marker seen")
        prev_len, stable = 0, 0
        for _ in range(120):
            pg.wait_for_timeout(1000)
            cur = len(pg.inner_text("body"))
            stable = stable + 1 if cur == prev_len else 0
            prev_len = cur
            if stable >= 3:
                break
        mark("output stable")
    pg.mouse.wheel(0, -20000)
    pg.wait_for_timeout(2500)
    mark("scrolled to top")
    pace = max(20.0, TARGET - (time.time() - t0))
    for _ in range(26):
        pg.mouse.wheel(0, 400)
        pg.wait_for_timeout(int(pace * 1000 / 26))
    mark("slow scroll done, holding")
    pg.wait_for_timeout(8000)
    mark("recording end")
    video = pg.video
    ctx.close()
    path = video.path()
    b.close()
print("VIDEO:", path, f"(set demo.rec to it; duration {media.duration(path):.2f}s)")
