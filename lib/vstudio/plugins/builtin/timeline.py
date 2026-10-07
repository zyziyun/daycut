"""Editor timelines as boards: CMX 3600 EDL, OpenTimelineIO (.otio JSON), Premiere / Final Cut 7 XML (xmeml) and
Final Cut Pro X (.fcpxml). One shot per clip on the first video track: duration from the record in/out (EDL) or the
clip range, the clip / reel name as the action, EDL ``* FROM CLIP NAME`` / ``* COMMENT`` and markers as notes."""
import json
import os
import re
import xml.etree.ElementTree as ET
from fractions import Fraction

from vstudio.plugins.contract import Importer

TC_RE = re.compile(r"^(\d{1,2}):(\d{2}):(\d{2})[:;.](\d{2,3})$")
EV_RE = re.compile(r"^(\d{3,6})\s+(\S+)\s+(\S+)\s+(\S+)(?:\s+\d+)?\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$")


def tc_seconds(tc, fps):
    m = TC_RE.match(tc.strip())
    if not m:
        return None
    h, mi, s, f = (int(x) for x in m.groups())
    return h * 3600 + mi * 60 + s + f / float(fps)


def parse_edl(text, fps=25.0):
    title, shots, cur = None, [], None
    fm = re.search(r"^\s*FCM:\s*(.+)$", text, re.M)
    if re.search(r"^TITLE:\s*(.+)$", text, re.M):
        title = re.search(r"^TITLE:\s*(.+)$", text, re.M).group(1).strip()
    m = re.search(r"(\d{2}(?:\.\d+)?)\s*fps", text, re.I)
    if m:
        fps = float(m.group(1))
    elif fm and "DROP" in fm.group(1).upper() and "NON" not in fm.group(1).upper():
        fps = 29.97
    for ln in text.splitlines():
        e = EV_RE.match(ln.strip())
        if e and e.group(3).upper().startswith(("V", "B")):
            rin, rout = tc_seconds(e.group(7), fps), tc_seconds(e.group(8), fps)
            if rin is None or rout is None:
                continue
            cur = dict(dur=round(max(0.04, rout - rin), 3), action=e.group(2) if e.group(2) not in ("AX", "BL") else "",
                       notes="")
            shots.append(cur)
            continue
        if cur is None:
            continue
        c = re.match(r"^\*\s*(FROM CLIP NAME|CLIP NAME|COMMENT|LOC)\s*:?\s*(.+)$", ln.strip(), re.I)
        if c:
            if c.group(1).upper().endswith("CLIP NAME"):
                cur["action"] = c.group(2).strip()
            else:
                cur["notes"] = (cur["notes"] + "\n" + c.group(2).strip()).strip()
    return dict(title=title, fps=fps, shots=shots)


def _rt(v):
    """OTIO RationalTime {value, rate} -> seconds."""
    try:
        return float(v["value"]) / float(v["rate"] or 1)
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def parse_otio(text):
    d = json.loads(text)
    title = d.get("name")
    tracks = ((d.get("tracks") or {}).get("children") or []) if isinstance(d.get("tracks"), dict) else []
    video = [t for t in tracks if (t.get("kind") or "Video") == "Video"] or tracks
    shots = []
    for item in (video[0].get("children") or []) if video else []:
        schema = str(item.get("OTIO_SCHEMA") or "")
        sr = item.get("source_range") or {}
        dur = _rt(sr.get("duration") or {}) if sr else None
        if schema.startswith("Gap"):
            continue
        if not schema.startswith("Clip") or dur is None:
            continue
        notes = "\n".join(str((m.get("name") or "") + (": " + m["comment"] if m.get("comment") else ""))
                          for m in item.get("markers") or [] if isinstance(m, dict))
        shots.append(dict(dur=round(dur, 3), action=item.get("name") or "", notes=notes.strip()))
    return dict(title=title, shots=shots)


def _frac(s):
    """FCPX time '1001/30000s' | '5s' -> seconds."""
    s = str(s or "").strip().rstrip("s")
    try:
        return float(Fraction(s)) if s else None
    except (ValueError, ZeroDivisionError):
        return None


def parse_xml(text):
    root = ET.fromstring(text)
    shots, title = [], None
    if root.tag == "xmeml":
        seq = root.find(".//sequence")
        title = seq.findtext("name") if seq is not None else None
        tb = float((seq.findtext("rate/timebase") if seq is not None else None) or 25)
        track = root.find(".//media/video/track")
        for ci in (track.findall("clipitem") if track is not None else []):
            try:
                st, en = float(ci.findtext("start")), float(ci.findtext("end"))
            except (TypeError, ValueError):
                continue
            if st < 0 or en <= st:
                continue
            rate = float(ci.findtext("rate/timebase") or tb)
            shots.append(dict(dur=round((en - st) / rate, 3), action=ci.findtext("name") or "",
                              notes=" ".join(m.findtext("comment") or m.findtext("name") or ""
                                             for m in ci.findall("marker")).strip()))
    elif root.tag == "fcpxml":
        proj = root.find(".//project")
        title = proj.get("name") if proj is not None else None
        spine = root.find(".//spine")
        for el in list(spine) if spine is not None else []:
            if el.tag not in ("asset-clip", "clip", "video", "ref-clip", "mc-clip", "sync-clip", "title"):
                continue
            dur = _frac(el.get("duration"))
            if not dur:
                continue
            shots.append(dict(dur=round(dur, 3), action=el.get("name") or "",
                              notes=" ".join(m.get("value") or "" for m in el.findall("marker")).strip()))
    return dict(title=title, shots=shots)


class TimelineImporter(Importer):
    id = "timeline"
    exts = (".edl", ".otio", ".xml", ".fcpxml")

    def sniff(self, path):
        p = str(path)
        if os.path.isdir(p):
            return 0.0
        ext = os.path.splitext(p)[1].lower()
        if ext in (".edl", ".otio", ".fcpxml"):
            return 0.9
        if ext == ".xml":
            try:
                with open(p, encoding="utf-8", errors="replace") as f:
                    head = f.read(4000)
            except OSError:
                return 0.0
            return 0.85 if ("<xmeml" in head or "<fcpxml" in head) else 0.0
        return 0.0

    def load(self, path):
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            text = f.read()
        ext = os.path.splitext(str(path))[1].lower()
        b = parse_edl(text) if ext == ".edl" else parse_otio(text) if ext == ".otio" else parse_xml(text)
        b["title"] = b.get("title") or os.path.splitext(os.path.basename(str(path)))[0]
        b["aspect"] = "16:9"
        return b
