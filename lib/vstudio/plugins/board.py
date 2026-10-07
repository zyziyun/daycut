"""The neutral board every importer returns, and turning it into Create shots.

Board (schema "reelfold.board/1"):
    {title, aspect "9:16", fps?, message?, format? (a Create format id hint), source {importer, path},
     shots: [{dur (s), title?, text? (on-screen text), action? (what we see), voiceover?, camera?, notes?,
              transition?, faces? [cast ids], source? (a Create source: plugin:hyperframes, agent:claude-code,
              card, record ...), ref? {kind, project, src, ...} (what a provider needs to make it)}]}

``normalize(board)`` cleans one up (numbers, lengths, unknown keys dropped) and raises ``import.empty`` when there
is nothing to make. ``to_shots(board)`` -> Create shot dicts (no, beat, dur, faces, camera, action, lines, card,
notes, source?, ref?).
"""
import math
import re

SCHEMA = "reelfold.board/1"
MAX_SHOTS = 300
TEXT = 2000


class BoardError(ValueError):
    def __init__(self, code, **params):
        self.code = code if code.startswith("create.") else f"create.{code}"
        self.params = params
        super().__init__(f"{self.code} {params}")


def _s(v, hi=TEXT):
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        v = " ".join(str(x) for x in v if x is not None)
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(v)).strip()[:hi]


def seconds(v, default=None):
    """'12s' | '~12 s' | '0:12' | '00:00:12:05@25' | 12 | '1.5' -> float seconds (None when unreadable)."""
    if v is None or v == "":
        return default
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v) if math.isfinite(v) and v >= 0 else default
    t = str(v).strip().lower().lstrip("~≈").strip()
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(s|sec|secs|seconds?|秒)?$", t)
    if m:
        return float(m.group(1))
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(ms)$", t)
    if m:
        return float(m.group(1)) / 1000
    m = re.match(r"^(\d+):(\d{1,2})(?:\.(\d+))?$", t)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2)) + float("0." + (m.group(3) or "0"))
    return default


def aspect_of(fmt):
    """'1080x1920' | '9:16' | '1920×1080' -> '9:16' / '16:9' / '1:1' / 'W:H'."""
    t = str(fmt or "").strip()
    m = re.match(r"^(\d+)\s*[x×:]\s*(\d+)", t)
    if not m:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    if not w or not h:
        return None
    g = math.gcd(w, h)
    return f"{w // g}:{h // g}"


def normalize(board, importer=None, path=None):
    if not isinstance(board, dict):
        raise BoardError("import.unknown-format")
    shots = []
    for raw in (board.get("shots") or [])[:MAX_SHOTS]:
        if not isinstance(raw, dict):
            continue
        dur = seconds(raw.get("dur"), None)
        if dur is None:
            dur = seconds(raw.get("duration"), 3.0)
        sh = dict(dur=round(max(0.2, min(dur, 600.0)), 2))
        for k in ("title", "text", "action", "voiceover", "camera", "notes", "transition"):
            v = _s(raw.get(k))
            if v:
                sh[k] = v
        faces = [str(x)[:8] for x in raw.get("faces") or [] if str(x).strip()]
        if faces:
            sh["faces"] = faces[:6]
        if isinstance(raw.get("source"), str) and raw["source"].strip():
            sh["source"] = raw["source"].strip()[:120]
        if isinstance(raw.get("ref"), dict):
            sh["ref"] = {str(k)[:40]: (v if isinstance(v, (int, float, bool)) or v is None else _s(v, 1000))
                         for k, v in list(raw["ref"].items())[:20]}
        if any(sh.get(k) for k in ("title", "text", "action", "voiceover", "notes", "ref")):
            shots.append(sh)
    if not shots:
        raise BoardError("import.empty")
    src = dict(board.get("source") or {})
    if importer:
        src["importer"] = importer
    if path:
        src["path"] = str(path)
    return dict(schema=SCHEMA, title=_s(board.get("title"), 80) or "Imported board",
                aspect=aspect_of(board.get("aspect")) or "9:16", fps=board.get("fps"),
                message=_s(board.get("message"), 500), format=board.get("format"), source=src, shots=shots)


def to_shots(board):
    out = []
    for i, s in enumerate(board["shots"]):
        no = f"{i + 1:02d}"
        action = s.get("action") or s.get("title") or s.get("text") or ""
        line = s.get("voiceover")
        notes = "\n".join(x for x in (s.get("notes"), s.get("text") and f"On screen: {s['text']}",
                                       s.get("transition") and f"Transition in: {s['transition']}") if x)
        sh = dict(no=no, beat=s.get("title") or f"shot-{no}", dur=float(s["dur"]), faces=list(s.get("faces") or []),
                  camera=s.get("camera", ""), action=action, lines=[dict(who="VO", text=line)] if line else [],
                  card=None, notes=notes)
        if s.get("source"):
            sh["source"] = s["source"]
        if s.get("ref"):
            sh["ref"] = s["ref"]
        out.append(sh)
    return out
