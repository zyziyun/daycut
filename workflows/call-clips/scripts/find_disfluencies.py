#!/usr/bin/env python3
"""Review sheet of the 气口 / fillers / stumbles auto-trim would cut from the keep-windows.

A thin front end of the shared tool: ``python -m vstudio.cleanup analyze <wav> --transcript <json>
--ranges <windows>`` (references/CLEANUP.md) with the call-clips profile names (classic = gentle,
word = standard; cut_profiles.py). Writes the EDL (default work/cleanup.json) and the creator's sheet
(work/cleanup_review.md): 待确认 CONFIRM, 自动删 AUTO, 气口 AUTO, 保留 KEEP, each numbered with context.

The creator replies (e.g. "确认 3,5 / 保留 7"); put the EDL and the reply into clips.json:
    "cleanup_edl": "work/cleanup.json", "cleanup_reply": "确认 3,5 / 保留 7"
and build_clips.py (with "auto_trim": true) cuts every window with exactly those decisions. Without
"cleanup_edl", build_clips runs ``cleanup.clean`` per window and applies only the AUTO edits.

Usage:
  find_disfluencies.py work/audio16k.wav work/audio16k.json --windows 124.58-410.3,527-560.9
  find_disfluencies.py ... --extra editor_cuts.json --json work/cuts.json [--profile word]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cut_profiles
from vstudio import cleanup


def main(argv=None):
    ap = argparse.ArgumentParser(description="Cleanup review sheet (vstudio.cleanup analyze --ranges) for keep-windows.")
    ap.add_argument("wav", help="16 kHz mono wav of the recording (or the source media)")
    ap.add_argument("whisper", help="whisper JSON with word timestamps")
    ap.add_argument("--windows", required=True, help="a-b,a-b in source seconds (or m:ss)")
    ap.add_argument("--extra", default=None, help="editor cuts JSON: [[from, to, why], ...] (shown word-safe)")
    ap.add_argument("--profile", default=None, choices=list(cut_profiles.PROFILES),
                    help="classic (= gentle, default) | word (= standard) | gentle | standard | tight")
    ap.add_argument("--out", default="work/cleanup.json", help="EDL path (review sheet next to it)")
    ap.add_argument("--force", action="store_true", help="overwrite an existing different EDL")
    ap.add_argument("--json", default=None, help="also write {window: [[a, b, why], ...]} (AUTO + editor cuts)")
    args = ap.parse_args(argv)
    ranges = cleanup.parse_ranges(args.windows)
    prof = cut_profiles.resolve(args.profile)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    review = os.path.splitext(args.out)[0] + "_review.md"
    edl = cleanup.analyze(args.wav, transcript=args.whisper, ranges=ranges, profile=prof, out=args.out,
                          review=review, force=args.force)
    print(cleanup.review_sheet(edl))
    extra = json.load(open(args.extra, encoding="utf-8")) if args.extra else None
    W = cleanup.load_words(edl["words"])
    en = cut_profiles.energy(args.wav, W, ranges, prof) if extra or args.json else None
    report, total, saved = {}, 0.0, 0.0
    for lo, hi in ranges:
        res = cut_profiles.window(W, en, lo, hi, extra, prof, edits=edl["edits"])
        report[f"{lo:g}-{hi:g}"] = res["cuts"]
        total += hi - lo
        saved += (hi - lo) - sum(b - a for a, b in res["keep"])
        for a, b, why in res["cuts"]:
            if why.startswith("edit"):
                print(f"{a:8.2f}-{b:8.2f} {b - a:5.2f}s  {why}")
    s = edl["stats"]
    print(f"windows {total:.0f}s: {s['auto']} auto, {s['confirm']} to confirm -> -{saved:.1f}s "
          f"({saved / max(total, 1e-6):.0%}) with AUTO{' + editor' if extra else ''} cuts; profile {prof}; "
          f"EDL {edl['_path']}")
    print(f'reply -> clips.json "cleanup_edl": "{args.out}", "cleanup_reply": "确认 N / 保留 M"')
    if args.json:
        json.dump(report, open(args.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
