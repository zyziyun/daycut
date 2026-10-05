#!/usr/bin/env python3
"""Draft STORYBOARD.md + scenes.config.json from SCRIPT.md, so you edit a storyboard instead of writing one.

Usage:  python3 storyboard_from_script.py [--project .] [--platform xiaohongshu:full] [--mode short]
                                          [--wpm 175] [--force]
Reads   <project>/SCRIPT.md; for timing, the best of: audio/scene_cues.json + audio/scenes.json (real, after the
        voice exists) > subtitles/cues.txt (or cues.draft.txt) chunks timed at --wpm > SCRIPT clauses at --wpm;
        subtitles/display_rules.json (spoken -> display form for the hints)
Writes  <project>/STORYBOARD.md and scenes.config.json — or STORYBOARD.draft.md / scenes.config.draft.json
        when those exist (--force overwrites; "platform" / "mode" of an existing scenes.config.json are kept)

One scene per SCRIPT line: id fNN-<label-slug>, a transition (none for the first; a varied cycle after it,
fast ones in short mode), and a time-coded shot sequence with ONE beat per cue — scene-local seconds and the
words that trigger it, plus a hint (numbers to reveal, an equation to build, a question to pose, a contrast,
a numbered step). Every hint ends in "TODO": decide the actual visual. Re-run with --force after
scene_windows.py so the times are the real ones (and keep your edited "shots" text: --keep-shots).
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json, os, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from canvas import add_platform_arg, resolve
from display_en import display, load_rules
from pair_cues import en_clauses
from script_md import parse_script, slug

TRANS_LONG = [["blur", 0.8], ["fade", 0.6], ["push", 0.7], ["iris", 0.8], ["focus", 0.7], ["vpush", 0.7]]
TRANS_SHORT = [["push", 0.35], ["fade", 0.3], ["vpush", 0.35], ["zoom", 0.4]]
OPS = re.compile(r"\b(divided by|times|plus|minus|equals|over|round(?:ed|s|ing)?|multipl\w+|add\w*|subtract\w*)\b", re.I)
CONTRAST = re.compile(r"\b(but|instead|versus|vs|whereas|unlike|however|on the other hand)\b", re.I)
STEP = re.compile(r"\b(first|second|third|step|next|then|finally)\b", re.I)


def hint(en_disp):
    nums = re.findall(r"[−-]?\d[\d.,]*\s*(?:%|GB|MB|bits?|B\b)?", en_disp)
    nums = [n.strip().rstrip(".,") for n in nums if n.strip().rstrip(".,")]
    h = []
    if nums:
        h.append("reveal " + ", ".join(dict.fromkeys(nums[:4])) + " (mono; count up or pop on the word)")
    if OPS.search(en_disp) or re.search(r"[=÷×]", en_disp):
        h.append("build the equation term by term, symbols in their role colours")
    if en_disp.rstrip().endswith("?"):
        h.append("pose it as an italic question line")
    if CONTRAST.search(en_disp):
        h.append("contrast: dim what came before, light up the new idea")
    if STEP.search(en_disp) and not h:
        h.append("numbered step label")
    return "; ".join(h) + " — TODO" if h else "TODO: what appears (one visual per idea)"


def motion_tags(hints):
    tags = []
    if "reveal" in hints:
        tags.append("dataviz-countup")
    if "equation" in hints:
        tags.append("kinetic-type-beats")
    if "contrast" in hints:
        tags.append("focus-dim")
    tags.append("svg-path-draw")
    return " + ".join(dict.fromkeys(tags)) + " (suggested)"


def key_phrase(s, n=6):
    w = s.split()
    return " ".join(w[:n]) + ("…" if len(w) > n else "")


def read_cues_txt(path):
    groups, cur = {}, None
    for ln in open(path, encoding="utf-8"):
        ln = re.sub(r"\s+# check:.*$", "", ln.rstrip("\n"))
        if ln.startswith("## "):
            cur = int(ln[3:].split()[0]); groups[cur] = []
        elif "||" in ln and cur is not None:
            groups[cur].append([x.strip() for x in ln.split("||")][:2])
    return groups


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n", 2)[2])
    ap.add_argument("--project", "-C", default=".", help="project dir (default: current dir)")
    ap.add_argument("--mode", choices=["long", "short"], default=None,
                    help="short = 60-120 s vertical explainer pacing (default: config mode, else short on a vertical canvas)")
    ap.add_argument("--wpm", type=float, default=175.0, help="speaking rate for estimated timing (measure from a sample)")
    ap.add_argument("--gap", type=float, default=0.7, help="pause between lines (concat_vo.py --gap)")
    ap.add_argument("--force", action="store_true", help="overwrite STORYBOARD.md / scenes.config.json")
    ap.add_argument("--keep-shots", action="store_true",
                    help="with --force: keep each scene's existing id, transition and 'shots' text (STORYBOARD.md timing refreshed)")
    add_platform_arg(ap)
    a = ap.parse_args()
    root = pathlib.Path(a.project)
    old = {}
    if (root / "scenes.config.json").exists():
        old = json.load(open(root / "scenes.config.json"))
    platform = a.platform or old.get("platform")
    cv = resolve(root, platform)
    mode = a.mode or old.get("mode") or ("long" if cv["legacy"] else "short")
    short = mode == "short"
    rules = load_rules(str(root))
    lines = parse_script(root / "SCRIPT.md")
    if not lines:
        sys.exit("no '## Line N' blocks in SCRIPT.md")

    # ---- timing: real (scene_cues) > cues.txt chunks at wpm > script clauses at wpm
    sc_p, sw_p = root / "audio/scene_cues.json", root / "audio/scenes.json"
    real = sc_p.exists() and sw_p.exists()
    if real:
        SC = json.load(open(sc_p)); SW = {w["frame"]: w for w in json.load(open(sw_p))["scenes"]}
        timing = "real cue times (audio/scene_cues.json)"
    else:
        ct = next((p for p in (root / "subtitles/cues.txt", root / "subtitles/cues.draft.txt") if p.exists()), None)
        groups = read_cues_txt(ct) if ct else {}
        timing = f"ESTIMATED at {a.wpm:g} wpm from {ct.relative_to(root) if ct else 'SCRIPT clauses'} — re-run with --force after scene_windows.py"
    sec = lambda s: len(s.split()) * 60.0 / a.wpm

    scenes, frames, total = [], [], 0.0
    oldsc = {s.get("id"): s for s in old.get("scenes", [])}
    oldsc_by_n = {k + 1: s for k, s in enumerate(old.get("scenes", []))}
    for k, L in enumerate(lines):
        n = L["n"]
        if real:
            cues = [(c["t"], c["en"]) for c in SC.get(str(n), [])]
            dur = SW[n]["duration"] if n in SW else (cues[-1][0] + 2 if cues else 5)
        else:
            chunks = [e for e, _ in groups.get(n, [])] or en_clauses(L["en"], 64 if short else 90)
            t, cues = (0.35 if k else 0.0), []
            for ch in chunks:
                cues.append((round(t, 2), display(ch, n, rules)))
                t += sec(ch)
            dur = round(t + a.gap + (1.2 if k == len(lines) - 1 and short else 2.5 if k == len(lines) - 1 else 0), 2)
        total += dur
        fid = f"f{n:02d}-{slug(L['label'])}"
        beats = []
        if k == 0 and short:
            beats.append("HOOK: the first visual is already on screen by 0.3 s (no title fade); the hook number / "
                         "question is readable by 1.5 s.")
        elif short:
            beats.append("Scene title (eyebrow) snaps in at 0.1s.")
        else:
            beats.append("Scene title fades in at 0.2s.")
        for t, en in cues:
            beats.append(f"- {t:.1f}s (\"{key_phrase(en)}\"): {hint(en)}")
        beats.append("Ambient: main group drifts up ≤ 4px." if short else "Ambient: whole group drifts up 6px over the scene.")
        shots = "\n".join(beats)
        prev = oldsc.get(fid) or oldsc_by_n.get(n) or {}
        if a.keep_shots and prev.get("shots"):
            shots = prev["shots"]
        tr = None if k == 0 else (TRANS_SHORT if short else TRANS_LONG)[(k - 1) % len(TRANS_SHORT if short else TRANS_LONG)]
        if a.keep_shots and "transition" in prev:
            tr = prev["transition"]
        if a.keep_shots and prev.get("id"):
            fid = prev["id"]
        scenes.append({"id": fid, "transition": tr, "shots": shots})
        frames.append((n, L, fid, dur, tr, cues))

    cfg = {}
    if platform:
        cfg["platform"] = platform
    if mode == "short" or old.get("mode"):
        cfg["mode"] = mode
    cfg["scenes"] = scenes

    # ---- STORYBOARD.md
    hook_s = sec(re.split(r"(?<=[.?!])\s", lines[0]["en"])[0])
    sb = ["---", f"format: {cv['W']}x{cv['H']}" + ("" if cv["legacy"] else f"  # {cv['key']}"),
          f"mode: {mode}", f"duration: ~{total:.0f}s ({len(lines)} scenes)",
          'message: "TODO: the one sentence the viewer should remember"',
          "arc: " + " → ".join(L["label"] for L in lines),
          f"timing: {timing}",
          ("safe_zone: math in the frame.md math area; captions own " +
           (f"the band y {cv['caption'][1]}–{cv['caption'][3]}" if not cv["legacy"] else "y > 840")),
          "---", "",
          "Drafted by storyboard_from_script.py — edit the motion, the shots (scenes.config.json) and the sketches; "
          "every TODO is a decision for you.", ""]
    for n, L, fid, dur, tr, cues in frames:
        sb += [f"## Frame {n} — {L['label']}", "",
               f"- duration: {dur:.0f}s" + ("" if real else " (estimated)"),
               f"- transition_in: {tr[0] + ' ' + str(tr[1]) + 's' if tr else 'cut'}",
               "- status: draft", f"- src: compositions/{fid}.html",
               f"- motion: {motion_tags(' '.join(hint(e) for _, e in cues))}",
               f"- sketch: storyboard/sketches/f{n:02d}.svg",
               f"- voiceover: \"{L['en'][:90]}{'…' if len(L['en']) > 90 else ''}\"",
               f"- beats: {len(cues)} cues → {len(cues)} reveals (see scenes.config.json shots)", ""]

    warn = []
    if short:
        if not 4 <= len(lines) <= 10:
            warn.append(f"short mode: {len(lines)} scenes (aim for 5-8)")
        if total > 125:
            warn.append(f"short mode: ~{total:.0f}s total (aim for 60-120 s)")
        if hook_s > 2.2:
            warn.append(f"short mode: the first sentence takes ~{hook_s:.1f}s to say — the hook should land in 2 s")
        long_sc = [f"f{n:02d}" for n, _, _, d, _, _ in frames if d > 14]
        if long_sc:
            warn.append(f"short mode: scenes over 14 s: {', '.join(long_sc)} (split the line)")
    if cv.get("profile") is not None:
        from vstudio import platform as PF
        warn += PF.check_length(cv["profile"], total)

    def target(name, draft):
        p = root / name
        return p if (a.force or not p.exists()) else root / draft
    p_sb, p_cfg = target("STORYBOARD.md", "STORYBOARD.draft.md"), target("scenes.config.json", "scenes.config.draft.json")
    p_sb.write_text("\n".join(sb), encoding="utf-8")
    p_cfg.write_text(json.dumps(cfg, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{p_sb.name} + {p_cfg.name}: {len(lines)} scenes, ~{total:.0f}s, mode {mode}, canvas {cv['W']}x{cv['H']}; timing: {timing}")
    for w in warn:
        print("warning:", w)


if __name__ == "__main__":
    main()
