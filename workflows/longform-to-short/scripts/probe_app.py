#!/usr/bin/env python3
"""Optional step 4a: probe the live demo app before re-recording it.

Screenshots config.demo.url and lists candidate input / button selectors so you can set
demo.input_selector and demo.submit_text. Needs `pip install playwright && playwright install chromium`.

Usage: python3 probe_app.py work/config.py
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import _lfc

cfg, _ = _lfc.load(description=__doc__)
url = cfg.get("demo.url") or sys.exit("config.demo.url is not set")
vw, vh = cfg.get("demo.viewport", [1856, 1016])
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("pip install playwright && python3 -m playwright install chromium")

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": vw, "height": vh})
    pg.goto(url, wait_until="networkidle", timeout=60000)
    pg.wait_for_timeout(2000)
    pg.screenshot(path="probe_app.png")
    for sel in ["textarea", "input[type=text]", "input:not([type])", "button"]:
        for el in pg.query_selector_all(sel):
            print(sel, "|", (el.get_attribute("placeholder") or "")[:60], "|",
                  (el.inner_text() or "")[:40].replace("\n", " "))
    b.close()
print("probe_app.png written")
