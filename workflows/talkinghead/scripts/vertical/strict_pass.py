#!/usr/bin/env python3
"""Strict pass: apply the creator's decisions on the speech cleanup (vstudio.cleanup) to the existing body
(keeps the retouch, no re-render of it). The detection already ran on the RAW clips in cut_pass1
(cleanup.c<N>.json + cleanup_review.md: fillers, repeats, stammers, restarts, re-takes, 气口).
1) python strict_pass.py review            (old name: transcribe [body_a.wav] ["prompt"] - same thing, no ASR)
   -> prints cleanup_review.md and writes strict_draft.py with REPLY = "" and the CONFIRM list as comments.
2) the creator answers the sheet; copy strict_draft.py to strict.py and fill in:
       REPLY = "确认 3,5,9 / 保留 7"     # 确认 = also cut these (CONFIRM / KEEP rows), 保留 = do not cut (AUTO rows too)
       CUT = [(1, 12.30, 12.90)]          # optional extra editor cuts: (clip, raw t0, raw t1)
       TEXT = {3: "职业发展的初期|对于大家的习惯"}   # optional subtitle rewrites per sid
   (APPROVE = {3, 5}, KEEP = {7}, ALL_CONFIRM = True work too; a legacy DEL = {bw.json index} is still cut.)
   With REPLY = "" only the AUTO edits are applied: CONFIRM rows are never cut without the creator's yes.
3) python strict_pass.py apply strict.py IN_V IN_A OUT_V OUT_A
   -> segs.strict.json + segs.json (subs keep their sid, words carry new times) + <OUT_A stem>.cleanup.json
   (cleanup sidecar). Always derived from the immutable segs.pass1.json, so re-applying (another reply, or after
   a drop_pass) is idempotent; IN_A must be the pass-1 (retouched) body, anything else is refused.
4) python strict_pass.py verify strict.py OUT_A ["术语 prompt"] [--transcript got.json]
   = cleanup.verify: re-ASR the cut and compare with the words that should remain; lost content words ->
   exit 1, with the edit ids near each one (add 保留 N to REPLY and re-apply)."""
import sys, pathlib; sys.path[:0] = [str(pathlib.Path(__file__).resolve().parents[4] / "lib"), str(pathlib.Path(__file__).resolve().parents[1])]
if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"): print(__doc__); sys.exit(0)
import json, os, importlib.util
from bodycut import (F, body_spans, cut_body, load_edls, load_stage, on_body, pick_parent, q, raw_to_body,
                     save_stage, word_remap)
from vstudio import cleanup


def _mod(path):
    sys.path[:0] = [os.path.dirname(os.path.abspath(path)), os.getcwd()]
    from vstudio.config import load_py      # from source: a REPLY rewritten in the same second is never stale
    return load_py(path, 'st')


def _pass1():
    p1 = load_stage('pass1')
    if p1 is None or 'segs' not in p1:
        raise SystemExit('segs.pass1.json is missing or predates the shared cleanup (vstudio.cleanup): re-run cut_pass1.py')
    return p1


def decisions(st, known):
    """(approve, keep, all_confirm, extra {clip: [(a, b, why)]}) from a strict.py module."""
    r = cleanup.parse_reply(getattr(st, 'REPLY', '') or '')
    ap = set(r['approve']) | set(getattr(st, 'APPROVE', ()) or ())
    kp = set(r['keep']) | set(getattr(st, 'KEEP', ()) or ())
    allc = bool(r['all_confirm'] or getattr(st, 'ALL_CONFIRM', False))
    bad = (ap | kp) - known
    if bad: raise SystemExit(f'unknown edit ids {sorted(bad)} (see cleanup_review.md)')
    extra = {}
    for c, a, b in getattr(st, 'CUT', ()) or ():
        extra.setdefault(int(c), []).append((float(a), float(b), 'editor cut'))
    return ap, kp, allc, extra


if sys.argv[1] in ('review', 'transcribe'):
    p1 = _pass1(); edls = load_edls(p1)
    if sys.argv[1] == 'transcribe' and len(sys.argv) > 2:
        print('note: the cleanup analysed the raw clips in cut_pass1; no body transcription is needed\n')
    txt = open('cleanup_review.md', encoding='utf-8').read() if os.path.exists('cleanup_review.md') else \
        '\n\n'.join(cleanup.review_sheet(e) for e in edls.values())
    print(txt)
    conf = [e for edl in edls.values() for e in edl['edits'] if e['action'] == 'confirm']
    auto = [e for edl in edls.values() for e in edl['edits'] if e['action'] == 'auto']
    with open('strict_draft.py', 'w', encoding='utf-8') as f:
        f.write('"""strict_pass decisions. The creator answers cleanup_review.md before apply: AUTO rows are cut unless\n'
                'kept (保留 N), CONFIRM rows only after a yes (确认 N) - they are often real words."""\n')
        f.write('REPLY = ""        # e.g. "确认 3,5,9 / 保留 7"\n# CONFIRM (not applied unless named in REPLY):\n')
        for e in conf:
            f.write(f"#   {e['id']:>3}  {e['kind']:<13} '{e['text']}'  {e['reason']}\n")
        f.write('CUT = []          # extra editor cuts: (clip, raw t0, raw t1)\nTEXT = {}\n')
    print(f'\nstrict_draft.py: {len(auto)} auto edits (applied by default), {len(conf)} to confirm. '
          'Show the creator the sheet, put the reply in REPLY, copy to strict.py; after apply run `verify`.')
    sys.exit()

st = _mod(sys.argv[2])
p1 = _pass1(); edls = load_edls(p1)
known = {e['id'] for edl in edls.values() for e in edl['edits']}
AP, KP, ALLC, EXTRA = decisions(st, known)

if sys.argv[1] == 'verify':
    args = sys.argv[3:]; tr = None
    if '--transcript' in args:
        i = args.index('--transcript'); tr = args[i + 1]; args = args[:i] + args[i + 2:]
    out_a = args[0]; prompt = args[1] if len(args) > 1 else None
    rep = cleanup.verify(out_a, got=tr, prompt=prompt)
    for x in rep['leftovers']:
        print(f"  leftover @{x['t_out']:.2f}s '{x['text']}': {x['why']}")
    segs = p1['segs']
    for fl in rep['missing']:          # map back to the applied edits near the loss so 保留 N is easy to find
        near = []
        for c, edl in edls.items():
            for e in edl['edits']:
                if e['id'] in cleanup.applied_ids(edl['edits'], AP, KP, ALLC):
                    b = raw_to_body(segs, c, e['t0'])
                    if b is not None and abs(b - fl['t_src']) < 1.0: near.append(e['id'])
        print(f"  '{fl['text']}' @body {fl['t_src']:.2f}s: applied edits near it {near} -> add 保留 N to REPLY, re-apply")
    sys.exit(0 if rep['ok'] else 1)

IN_V, IN_A, OUT_V, OUT_A = sys.argv[3:7]
TEXT = getattr(st, 'TEXT', {})
_, prev = pick_parent(IN_A, ['pass1'])   # never segs.json: it may already be cut
segs = prev['segs']; total0 = prev['total']
keep_raw, applied = {}, {}
for c, edl in edls.items():
    ids = cleanup.applied_ids(edl['edits'], AP, KP, ALLC)
    lost = sorted(set(prev['applied'].get(str(c), [])) - set(ids))
    if lost:
        raise SystemExit(f'保留 {lost}: those 气口 were already squeezed in pass 1. Put REPLY = "保留 '
                         f'{",".join(map(str, lost))}" in edit_list.py and re-run cut_pass1.py (then retouch again).')
    applied[str(c)] = ids
    keep_raw[c] = cleanup.keep_segments(edl['edits'], edl['ranges'], AP, KP, ALLC, EXTRA.get(c, ()),
                                        edl['settings'].get('min_piece'), words=cleanup.load_words(edl['words']))
keep = body_spans(segs, keep_raw)
words0 = prev.get('body_words', [])
DEL = set(getattr(st, 'DEL', ()) or ())
if DEL:                                  # legacy: bw.json word indices on the pass-1 body
    bw = json.load(open('bw.json'))
    cuts = sorted((bw[i]['b0'], bw[i]['b1']) for i in DEL if i < len(bw))
    out = []
    for a, b in keep:
        for ca, cb in cuts:
            if cb <= a or ca >= b: continue
            if ca > a: out.append((a, ca))
            a = max(a, cb)
        if b > a: out.append((a, b))
    keep = out
merged = []
for a, b in ((q(a), q(b)) for a, b in keep):
    if merged and a <= merged[-1][1] + 1e-6: merged[-1][1] = max(merged[-1][1], b)
    elif b - a > 0.05: merged.append([a, b])
keep = [tuple(k) for k in merged]
if not keep: raise SystemExit('nothing left to keep')
T = cut_body(IN_V, IN_A, keep, OUT_V, OUT_A, 'seg_strict')
words = word_remap(words0, keep)
first = {}
for w in words: first.setdefault(w['sid'], w['b0'])
sids = [s['sid'] for s in prev['subs'] if s['sid'] in first]; subs = []
for k, sid in enumerate(sids):
    st0 = 0.0 if k == 0 else subs[-1]['end']; en = first[sids[k + 1]] if k + 1 < len(sids) else T
    old = next(s['text'] for s in prev['subs'] if s['sid'] == sid)
    subs.append(dict(sid=sid, text=TEXT.get(sid, old), start=round(st0, 3), end=round(en, 3)))
reply = getattr(st, 'REPLY', '') or ''
side = cleanup.write_sidecar(OUT_A, IN_A, keep, on_body(words0), prev.get('language'), fps=F, applied=applied,
                             approve=sorted(AP), keep_ids=sorted(KP), all_confirm=ALLC, reply=reply,
                             legacy_del=sorted(DEL))
save_stage('strict', dict(subs=subs, words=words, total=T, keep=keep, applied=applied, reply=reply,
                          approve=sorted(AP), keep_ids=sorted(KP), all_confirm=ALLC, DEL=sorted(DEL), sidecar=side,
                          language=prev.get('language')),
           parent='pass1')
n = sum(len(v) for v in applied.values()) - sum(len(v) for v in prev['applied'].values())
print(f'{n} word edits applied ({len(keep)} ranges), body {total0:.1f}s -> {T:.1f}s. Re-read every subtitle against the audio:')
for s in subs:
    print(s['sid'], ''.join(w['w'] for w in words if w['sid'] == s['sid']), ' || ', s['text'])
print(f'next: python strict_pass.py verify {sys.argv[2]} {OUT_A}')
