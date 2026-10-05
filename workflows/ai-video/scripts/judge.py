#!/usr/bin/env python3
"""Review sheet + scorecard for one generated take (the "不要太 AI" gate before a take enters the edit).

    python3 judge.py sheet takes/u03_v1.mp4 --out work/ai/judge/          # 12-frame strip + 3 large frames + ASR
    python3 judge.py sheet takes/u13_v1.mp4 --dense                        # falls / collapses: a frame every 0.25 s
    python3 judge.py sheet takes/u03_v1.mp4 --expect "Morning coffee. Simple."   # line check vs approved transcript
    python3 judge.py card u03_v1 --out work/ai/judge/                      # blank scorecard JSON to fill in
    python3 judge.py verdict work/ai/judge/u03_v1.card.json                # pass / redo / fix-in-post

Rubric (references/JUDGE_RUBRIC.md): any HARD flaw -> redo; >= 3 SOFT flaws -> redo or fix in post;
per-take scores A identity, B continuity, C shot completeness on 1-5; a take passes at A >= 4 and B >= 4
with no hard flaw. Look at faces at FULL size next to the reference sheet - thumbnails hid a smiling
character and a wrong face in the sessions.
"""
import argparse
import json
import os
import re
import sys

import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))

HARD = {
    "identity_drift": "face/glasses/hair/outfit differs from the look sheet, or changes within the take; A/B swapped",
    "premise_missing": "the action or spatial relation this shot must establish is not on screen",
    "hands_limbs": "extra/fused fingers, hand shape morphing, limbs through objects",
    "physics": "objects pass through bodies, appear/vanish/duplicate, gliding instead of walking",
    "generated_text": "readable or garbled text on screens, signs, paper (all text is added in post)",
    "lipsync_or_line": "mouth does not match, wrong words, or the wrong character speaks the line",
    "body_integrity": "a body part hidden then revealed is gone; person merged into an object; half a body",
    "scene_master": "set, positions, props or screen direction differ from the scene master",
}
SOFT = {
    "plastic_skin": "no pores / fine lines at full size; waxy or over-smoothed",
    "symmetry_teeth": "perfectly symmetric face, one-block white teeth",
    "dead_eyes": "fixed stare or mechanical blinking",
    "helmet_hair": "hair moves as one block, no flyaways",
    "glasses_warp": "glasses deform or melt into skin when the head turns",
    "lighting_mismatch": "face light does not match the set; ad-perfect lighting in a gritty scene",
    "oversaturated": "colour too clean / saturated for the scene",
    "sound_mismatch": "studio-dry voice outdoors, odd breaths, music when none was asked",
    "template_camera": "generic 'AI epic' camera; no handheld, no imperfection",
    "over_acting": "open-mouth screaming, grinning, gurning, mugging at camera",
    "looks_at_camera": "someone looks into the lens or laughs in danger",
}


def verdict(card):
    """card: {"hard": {key: bool flaw}, "soft": {key: bool flaw}, "scores": {"A": 1-5, "B": 1-5, "C": 1-5}}.
    -> (decision, reasons). decision in {"pass", "redo", "fix-in-post"}."""
    hard = [k for k, v in (card.get("hard") or {}).items() if v]
    soft = [k for k, v in (card.get("soft") or {}).items() if v]
    sc = card.get("scores") or {}
    reasons = []
    if hard:
        return "redo", [f"hard: {k}" for k in hard]
    low = [k for k in ("A", "B") if sc.get(k) is not None and sc[k] < 4]
    if low:
        return "redo", [f"score {k}={sc[k]} < 4" for k in low]
    if len(soft) >= 3:
        return "fix-in-post", [f"{len(soft)} soft flaws: {', '.join(soft)} - grade/grain/trim or redo"]
    if any(sc.get(k) is None for k in ("A", "B")):
        reasons.append("scores A/B not filled in - look at full-size faces before passing")
        return "redo", reasons
    return "pass", [f"soft: {k}" for k in soft]


def blank_card(take):
    return {"take": take, "hard": {k: False for k in HARD}, "soft": {k: False for k in SOFT},
            "scores": {"A": None, "B": None, "C": None}, "notes": ""}


def _norm_words(s):
    return re.findall(r"[a-z0-9']+|[一-鿿]", s.lower().replace("’", "'"))


def line_match(expected, heard):
    """Fraction of expected words heard in order-insensitive bag terms (0..1). <0.8 = check the take by ear."""
    e, h = _norm_words(expected), _norm_words(heard)
    if not e:
        return 1.0
    pool = list(h)
    hit = 0
    for w in e:
        if w in pool:
            pool.remove(w)
            hit += 1
    return round(hit / len(e), 3)


def sample_times(dur, n=12, dense=False, step=0.25):
    if dense:
        k = max(1, int(dur / step))
        return [round(min(dur - 0.02, (i + 0.5) * step), 3) for i in range(k)]
    return [round(dur * (i + 0.5) / n, 3) for i in range(n)]


def sheet(video, out_dir, dense=False, expect=None, language=None, asr=True):
    from PIL import Image
    from vstudio import media
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(video))[0]
    dur = media.duration(video)
    times = sample_times(dur, dense=dense)
    tw = 150
    strip = []
    for i, t in enumerate(times):
        p = os.path.join(out_dir, f".{stem}_s{i}.jpg")
        media.grab_frame(video, t, p, vf=f"scale={tw}:-2")
        strip.append(Image.open(p).convert("RGB"))
    big = []
    for i, fr in enumerate((0.2, 0.5, 0.85)):
        p = os.path.join(out_dir, f".{stem}_b{i}.jpg")
        media.grab_frame(video, dur * fr, p, vf="scale=600:-2")
        big.append(Image.open(p).convert("RGB"))
    cols = min(len(strip), 12)
    rows = (len(strip) + cols - 1) // cols
    sh, bh = strip[0].height, big[0].height
    W = max(cols * tw, 1800)
    canvas = Image.new("RGB", (W, rows * sh + bh), "white")
    for i, im in enumerate(strip):
        canvas.paste(im, ((i % cols) * tw, (i // cols) * sh))
    for i, im in enumerate(big):
        canvas.paste(im, (i * 600, rows * sh))
    out = os.path.join(out_dir, f"{stem}.sheet.jpg")
    canvas.save(out, quality=85)
    for f in os.listdir(out_dir):
        if f.startswith(f".{stem}_"):
            os.remove(os.path.join(out_dir, f))
    heard, score = "", None
    if asr:
        try:
            from vstudio import asr as A
            tr = A.transcribe(video, language=language)
            heard = " ".join(s.get("text", "").strip() for s in tr.get("segments", []))
        except Exception as e:                     # no whisper backend installed: the sheet is still useful
            heard = f"(asr unavailable: {e.__class__.__name__})"
        if expect:
            score = line_match(expect, heard)
    info = {"take": stem, "duration": round(dur, 2), "frames": len(times), "dense": dense, "sheet": out,
            "heard": heard, "expected": expect, "line_match": score}
    with open(os.path.join(out_dir, f"{stem}.sheet.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=1)
    return info


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n\n", 1)[1])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sheet")
    s.add_argument("video")
    s.add_argument("--out", default="work/ai/judge")
    s.add_argument("--dense", action="store_true", help="a frame every 0.25 s (falls, collapses, dissolves)")
    s.add_argument("--expect", help="approved line(s) for this take")
    s.add_argument("--language")
    s.add_argument("--no-asr", action="store_true")
    c = sub.add_parser("card")
    c.add_argument("take")
    c.add_argument("--out", default="work/ai/judge")
    v = sub.add_parser("verdict")
    v.add_argument("card")
    a = ap.parse_args(argv)
    if a.cmd == "sheet":
        info = sheet(a.video, a.out, a.dense, a.expect, a.language, asr=not a.no_asr)
        print(json.dumps(info, ensure_ascii=False, indent=1))
        if info["line_match"] is not None and info["line_match"] < 0.8:
            print("WARNING: spoken words differ from the approved line - regenerate, or accept the performance "
                  "and caption what is actually said (never caption the old script over new speech).")
    elif a.cmd == "card":
        os.makedirs(a.out, exist_ok=True)
        p = os.path.join(a.out, f"{a.take}.card.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(blank_card(a.take), f, indent=1)
        print(p)
    else:
        with open(a.card, encoding="utf-8") as f:
            d, why = verdict(json.load(f))
        print(d)
        for r in why:
            print(" -", r)
        return 0 if d == "pass" else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
