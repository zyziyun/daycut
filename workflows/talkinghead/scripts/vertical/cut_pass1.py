#!/usr/bin/env python3
"""Pass 1: hand-written keep list -> one body, cleaned with the shared speech-cleanup tool (vstudio.cleanup).
usage (in WORK): python cut_pass1.py edit_list.py [--analyze-only]
  1. every range is snapped word-safe (cleanup.snap_range: the start backs off to before its first word's onset,
     the end runs over the last word's real tail, neither reaches a neighbour word of a<N>.json)
  2. cleanup.analyze on each RAW clip (sdr<N>.mp4 + a<N>.json, only the snapped ranges) -> cleanup.c<N>.json
     (the EDL; edit ids are unique across clips) + cleanup_review.md for the creator: 待确认 CONFIRM,
     自动删 AUTO, 气口 AUTO, 保留 KEEP. --analyze-only stops here.
  3. the 气口 edits (pause / breath / lead / tail: squeezed, never deleted) are applied now; the word edits
     (fillers, repeats, restarts, re-takes) wait for the creator's reply and are applied by strict_pass.py on
     the (retouched) body, so the expensive retouch is never redone.
  -> body_v.mp4 body_a.wav segs.json + segs.pass1.json (immutable root every later pass derives from; carries the
     raw -> body map). (reads a<N>.wav / a<N>.json and sdr<N>.mp4 from prep_sources.sh)
edit_list.py defines  E = [(clip_no, [(t0, t1), ...], "subtitle|with|manual breaks"), ...]
one entry per sentence; its index becomes the sentence id (sid) used everywhere later. Optional:
  PROFILE = "gentle" | "standard" | "tight"     (default persona cleanup.profile, else standard)
  CLEANUP = {"pause_min": 0.3, ...}              (cleanup setting overrides)
  REPLY = "保留 4"                                (气口 ids NOT to squeeze in pass 1, from cleanup_review.md)
  legacy MAXGAP / KEEPGAP -> cleanup pause_min / kept gap; TH is ignored (cleanup calibrates on the clip)."""
import sys, pathlib; sys.path[:0] = [str(pathlib.Path(__file__).resolve().parents[4] / "lib"), str(pathlib.Path(__file__).resolve().parents[1])]
if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"): print(__doc__); sys.exit(0)
import os, importlib.util
from vstudio import cleanup
from bodycut import F, PAUSE_KINDS, cleanup_overrides, cut_sources, edl_name, intersect, save_stage
spec = importlib.util.spec_from_file_location('el', sys.argv[1]); el = importlib.util.module_from_spec(spec); spec.loader.exec_module(el)
E = el.E
PROFILE = getattr(el, 'PROFILE', None); OV = cleanup_overrides(el)
REPLY = cleanup.parse_reply(getattr(el, 'REPLY', '') or '')
if hasattr(el, 'TH'): print('note: TH is ignored - vstudio.cleanup calibrates the voice threshold on each clip')
clips = sorted({e[0] for e in E})

# 1. word-safe snap of every hand-written range
rs = {}                                       # (sid, k) -> [clip, a, b]
for c in clips:
    if not os.path.exists(f'a{c}.json'):
        raise SystemExit(f'a{c}.json missing: run prep_sources.sh (whisper words are needed for the cleanup)')
    words = cleanup.load_words(f'a{c}.json')
    mine = [(sid, k, t0, t1) for sid, (cc, rr, _) in enumerate(E) if cc == c for k, (t0, t1) in enumerate(rr)]
    en = cleanup.energy_of(f'a{c}.wav', words, [(t0, t1) for _, _, t0, t1 in mine], PROFILE, OV)
    for sid, k, t0, t1 in mine:
        a, b = cleanup.snap_range(words, t0, t1, en)
        rs[(sid, k)] = [c, max(0.0, a), b]
    items = sorted((v for v in rs.values() if v[0] == c), key=lambda v: v[1])
    for p, n in zip(items, items[1:]):       # snapped neighbours overlap: split the overlap in the middle
        if p[2] > n[1]:
            m = round(max(p[1], min(n[2], (p[2] + n[1]) / 2)), 3)
            p[2], n[1] = m, m

# 2. cleanup.analyze per raw clip; id_offset keeps the ids unique across clips (ONE reply for the video)
edls, off, review = {}, 0, []
for c in clips:
    rg = [(v[1], v[2]) for v in rs.values() if v[0] == c and v[2] > v[1]]
    src = f'sdr{c}.mp4' if os.path.exists(f'sdr{c}.mp4') else f'a{c}.wav'
    edl = cleanup.analyze(src, transcript=f'a{c}.json', ranges=rg, profile=PROFILE, overrides=OV, out=edl_name(c),
                          review=None, force=True, id_offset=off)
    edl.pop('_path', None)
    off += len(edl['edits'])
    edls[c] = edl
    review.append((f'# 片段 clip {c} (`{edl_name(c)}`)\n\n' if len(clips) > 1 else '') + cleanup.review_sheet(edl))
txt = '\n\n'.join(review)
with open('cleanup_review.md', 'w', encoding='utf-8') as f:
    f.write(txt + '\n')
print(txt)
known = {e['id'] for edl in edls.values() for e in edl['edits']}
bad = (REPLY['approve'] | REPLY['keep']) - known
if bad: raise SystemExit(f'REPLY names unknown edit ids {sorted(bad)}')
if '--analyze-only' in sys.argv[2:]:
    print('\ncleanup_review.md written (--analyze-only: no cut)'); sys.exit(0)

# 3. apply the 气口 edits only (auto, minus REPLY 保留), cut in edit-list order
keep, applied = {}, {}
for c, edl in edls.items():
    pe = [e for e in edl['edits'] if e['kind'] in PAUSE_KINDS]
    applied[str(c)] = cleanup.applied_ids(pe, REPLY['approve'], REPLY['keep'])
    keep[c] = cleanup.keep_segments(pe, edl['ranges'], REPLY['approve'], REPLY['keep'],
                                    words=cleanup.load_words(edl['words']))
segs = []
for sid, (c, ranges, text) in enumerate(E):
    for k in range(len(ranges)):
        _, a, b = rs[(sid, k)]
        for s, e in intersect(keep[c], a, b):
            fa, fb = round(s * F), round(e * F)
            if fb > fa: segs.append(dict(clip=c, t0=fa / F, t1=fb / F, sid=sid))
    if not any(s['sid'] == sid for s in segs): print('NO VOICE', sid, text)
# frame-exact cut + sample-exact audio from each clip's own a/v (vstudio.cut.cut_segments via bodycut)
T = cut_sources([(f"sdr{s['clip']}.mp4", s['t0'], s['t1']) for s in segs], 'body_v.mp4', 'body_a.wav', 'seg1')
t = 0.0; st = {}
for s in segs:
    s['b0'] = round(t, 4); t += round((s['t1'] - s['t0']) * F) / F; s['b1'] = round(t, 4)
    st.setdefault(s['sid'], [s['b0'], s['b1']])[1] = s['b1']
subs = [dict(sid=i, text=E[i][2], start=round(st[i][0], 3), end=round(st[i][1], 3)) for i in sorted(st)]
body_words = []                               # the raw words on the pass-1 body timeline (for strict / verify)
for c, edl in edls.items():
    for w in edl['words']:
        mid = (w['t'] + w['te']) / 2
        s = next((s for s in segs if s['clip'] == c and s['t0'] <= mid <= s['t1']), None)
        if s is None: continue
        b0 = min(max(s['b0'] + w['t'] - s['t0'], s['b0']), s['b1']); b1 = min(max(s['b0'] + w['te'] - s['t0'], b0), s['b1'])
        body_words.append(dict(w=w['w'], b0=round(b0, 3), b1=round(b1, 3), sid=s['sid'], clip=c, t=w['t']))
body_words.sort(key=lambda w: w['b0'])
save_stage('pass1', dict(subs=subs, total=T, segs=segs, body_words=body_words, applied=applied,
                         edls={str(c): edl_name(c) for c in clips},
                         language=next(iter(edls.values())).get('language')))   # segs.pass1.json (root) + segs.json
print(f'{len(segs)} segments -> body {T:.1f}s; 气口 applied: {sum(len(v) for v in applied.values())}. '
      'Word edits wait for the creator: reply on cleanup_review.md, then strict_pass.py apply.')
