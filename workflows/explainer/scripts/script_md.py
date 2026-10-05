"""Parse an explainer SCRIPT.md (format in WORKFLOW.md §2) into lines.

    ## Line N — <label> (Frame N)
    **Delivery:** ...            (optional)
        spoken English, 4-space indented (may span several indented lines)
    ZH: 中文字幕原文

parse_script(path) -> [{"n", "label", "frame", "delivery", "en", "zh"}]   (en joined exactly like align_cues.py)
"""
import re


def parse_script(path):
    text = open(path, encoding="utf-8").read()
    out = []
    for b in re.split(r"\n## Line ", "\n" + text)[1:]:
        head = b.split("\n", 1)[0]
        m = re.match(r"(\d+)\s*(?:[—–-]+\s*(.*?))?\s*(?:\(Frame\s*(\d+)\))?\s*$", head)
        if not m:
            continue
        n = int(m.group(1))
        en = " ".join(ln.strip() for ln in b.split("\n") if ln.startswith("    "))
        zh = " ".join(ln[3:].strip() for ln in b.split("\n") if ln.startswith("ZH:"))
        dm = re.search(r"\*\*Delivery:\*\*\s*(.+)", b)
        out.append(dict(n=n, label=(m.group(2) or f"Line {n}").strip(), frame=int(m.group(3) or n),
                        delivery=dm.group(1).strip() if dm else "", en=en, zh=zh))
    return out


def slug(label, maxlen=18):
    s = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    if len(s) > maxlen:
        s = s[:maxlen].rsplit("-", 1)[0] or s[:maxlen]
    return s or "scene"
