"""Generic shot lists: JSON, CSV / TSV, Markdown (a table, ``## Shot`` sections or a numbered list).

Columns / keys (any case, these aliases): duration | dur | seconds | secs | length | 时长 ;  text | on_screen |
title | 字幕 ;  action | description | scene | visual | 画面 | 内容 ;  voiceover | vo | dialogue | line |
narration | 台词 | 旁白 ;  camera | angle | 机位 | 景别 ;  notes | note | 备注 ;  source ;  faces | cast | 角色.
JSON: a list of shots, or {title?, aspect?, shots: [...]} (a full board passes straight through).
Markdown list: ``1. (3s) Close-up of the cup — "Morning."``.
"""
import csv
import io
import json
import os
import re

from vstudio.plugins.contract import Importer

KEYS = {
    "dur": ("duration", "dur", "seconds", "secs", "sec", "length", "time", "时长", "秒"),
    "title": ("title", "name", "heading", "标题"),
    "text": ("text", "on_screen", "onscreen", "on-screen text", "caption", "字幕", "文字"),
    "action": ("action", "description", "scene", "visual", "visuals", "picture", "画面", "内容", "描述"),
    "voiceover": ("voiceover", "vo", "dialogue", "line", "lines", "narration", "script", "audio", "台词", "旁白", "口播"),
    "camera": ("camera", "angle", "framing", "机位", "景别"),
    "notes": ("notes", "note", "comment", "comments", "备注"),
    "source": ("source", "provider", "tool"),
    "faces": ("faces", "cast", "characters", "who", "角色"),
    "no": ("no", "#", "shot", "shot no", "number", "镜头", "镜号", "序号"),       # read, then renumbered
}
ALIAS = {a.lower(): k for k, al in KEYS.items() for a in al}


def _canon(row):
    out = {}
    for k, v in row.items():
        c = ALIAS.get(str(k or "").strip().lower().replace("_", " ").replace("  ", " ")) or \
            ALIAS.get(str(k or "").strip().lower())
        if c and v not in (None, ""):
            if c == "faces" and isinstance(v, str):
                v = [x.strip() for x in re.split(r"[,;/ ]+", v) if x.strip()]
            out.setdefault(c, v)
    return out


def from_rows(rows):
    return [_canon(r) for r in rows if isinstance(r, dict)]


def parse_json(text):
    d = json.loads(text)
    if isinstance(d, list):
        return dict(shots=from_rows(d))
    if isinstance(d, dict):
        shots = d.get("shots") or d.get("frames") or d.get("scenes") or []
        return dict({k: v for k, v in d.items() if k in ("title", "aspect", "fps", "message", "format")},
                    shots=from_rows(shots))
    return dict(shots=[])


def parse_csv(text):
    sample = text[:4000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
    except csv.Error:
        dialect = csv.excel_tab if "\t" in sample else csv.excel
    return dict(shots=from_rows(list(csv.DictReader(io.StringIO(text), dialect=dialect))))


LIST_RE = re.compile(r"^\s*(?:\d+[.)]|[-*])\s+(?:\(?\s*(\d+(?:\.\d+)?)\s*(?:s|sec|秒)\s*\)?\s*[:：—–-]?\s*)?(.+)$")
QUOTE_RE = re.compile(r"[\"“「](.+?)[\"”」]")


def parse_markdown(text):
    lines = text.splitlines()
    title = next((ln.lstrip("# ").strip() for ln in lines if re.match(r"^#\s+\S", ln)), None)
    table = [ln for ln in lines if ln.strip().startswith("|")]
    if len(table) >= 3 and re.match(r"^\s*\|?\s*:?-{2,}", table[1]):
        head = [h.strip() for h in table[0].strip().strip("|").split("|")]
        rows = []
        for ln in table[2:]:
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            rows.append(dict(zip(head, cells)))
        return dict(title=title, shots=from_rows(rows))
    shots, cur = [], None
    for ln in lines:
        m = re.match(r"^#{2,3}\s*(?:shot|镜头|scene|frame)\s*\d*\s*[—–:\-]*\s*(.*)$", ln.strip(), re.I)
        if m:
            cur = dict(title=m.group(1).strip())
            shots.append(cur)
            continue
        if cur is not None:
            b = re.match(r"^\s*[-*]\s*([\w 一-鿿-]{1,20})\s*[:：]\s*(.+)$", ln)
            if b:
                c = ALIAS.get(b.group(1).strip().lower())
                if c:
                    cur.setdefault(c, b.group(2).strip())
                    continue
            if ln.strip():
                cur["notes"] = (cur.get("notes", "") + "\n" + ln.strip()).strip()
    if shots:
        return dict(title=title, shots=shots)
    for ln in lines:
        m = LIST_RE.match(ln)
        if not m:
            continue
        body = m.group(2).strip()
        q = QUOTE_RE.search(body)
        sh = dict(action=QUOTE_RE.sub("", body).strip(" —–-:"))
        if m.group(1):
            sh["dur"] = float(m.group(1))
        if q:
            sh["voiceover"] = q.group(1)
        shots.append(sh)
    return dict(title=title, shots=shots)


class ShotListImporter(Importer):
    id = "shotlist"
    exts = (".json", ".csv", ".tsv", ".md", ".markdown", ".txt")

    def sniff(self, path):
        p = str(path)
        if os.path.isdir(p):
            return 0.0
        ext = os.path.splitext(p)[1].lower()
        if ext in (".json", ".csv", ".tsv"):
            return 0.6
        if ext in (".md", ".markdown", ".txt"):
            return 0.4
        return 0.0

    def load(self, path):
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            text = f.read()
        ext = os.path.splitext(str(path))[1].lower()
        if ext == ".json":
            b = parse_json(text)
        elif ext in (".csv", ".tsv"):
            b = parse_csv(text)
        else:
            b = parse_markdown(text)
        b.setdefault("title", None)
        b["title"] = b.get("title") or os.path.splitext(os.path.basename(str(path)))[0].replace("_", " ")
        return b
