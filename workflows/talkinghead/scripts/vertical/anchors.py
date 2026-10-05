"""Time anchors for configs. Import in a config: `from anchors import S, E, W, SPAN`.
All return seconds on the CURRENT body timeline (reads ./segs.json), so effect timings
survive any later re-cut as long as subtitle ids (sid) are kept."""
import sys, pathlib; sys.path[:0] = [str(pathlib.Path(__file__).resolve().parents[4] / "lib"), str(pathlib.Path(__file__).resolve().parents[1])]
import json
_D = json.load(open('segs.json'))
_SUB = {s['sid']: s for s in _D['subs']}
_WORDS = _D.get('words', [])

def S(sid, frac=0.0):
    """start of sentence `sid`, or a fraction into it (0.5 = halfway)."""
    s = _SUB[sid]; return round(s['start'] + frac * (s['end'] - s['start']), 3)

def E(sid):
    """end of sentence `sid`."""
    return round(_SUB[sid]['end'], 3)

def SPAN(a, b=None):
    """(start of sid a, end of sid b) as a hook/scene range."""
    return (S(a), E(b if b is not None else a))

def W(sid, text, end=False):
    """start (or end) of the first word in sentence `sid` whose text contains `text`.
    Needs `words` in segs.json (written by strict_pass.py)."""
    s = _SUB[sid]
    for w in _WORDS:
        if s['start'] - 0.05 <= w['b0'] < s['end'] and text.lower() in w['w'].lower():
            return round(w['b1'] if end else w['b0'], 3)
    raise KeyError(f'word {text!r} not found in sid {sid}')
