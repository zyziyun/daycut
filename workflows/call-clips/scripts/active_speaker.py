"""Active speaker per final-timeline moment, for layouts that give the talking person the big tile.

``speaker_timeline.py`` labels every sample (SOURCE seconds) with the tile whose mouth moves most,
or ``"both"`` when it cannot tell. Raw labels flip on short back-channel words ("对", "嗯"), so a
layout driven by them would jump around. ``smooth`` is offline (it may look ahead):

1. a centred majority vote over ``win`` seconds (unknown samples abstain);
2. runs shorter than ``min_run`` seconds are merged into the neighbour they interrupt, repeatedly,
   so the big tile only changes for a real turn;
3. unknown stretches keep the previous speaker (or the first known one, or ``default``).

``to_final`` maps a source-time timeline through the clip's ``vstudio.cut.TimeMap`` into a regular
final-time grid, so the renderer only ever indexes by frame time.
"""
from collections import Counter

STEP = 0.1


def load(path):
    """speaker_timeline.py JSON -> (times, labels)."""
    import json
    d = json.load(open(path))
    return [float(t) for t in d["times"]], list(d["labels"])


def label_at(times, labels, t):
    """Label of the sample nearest source second t (None outside the sampled range)."""
    import bisect
    if not times or t < times[0] - 1.0 or t > times[-1] + 1.0:
        return None
    k = bisect.bisect_left(times, t)
    if k == len(times) or (k and t - times[k - 1] < times[k] - t):
        k -= 1
    return labels[k]


def to_final(times, labels, timemap, total, step=STEP, valid=None):
    """Final-time grid of raw labels: [label | None] every ``step`` s over [0, total)."""
    out = []
    n = int(total / step + 0.5)
    for i in range(n):
        s = timemap.to_source(i * step)
        lab = label_at(times, labels, s) if s is not None else None
        out.append(lab if (lab is not None and (valid is None or lab in valid)) else None)
    return out


def smooth(raw, step=STEP, win=1.0, min_run=1.6, default=None):
    """Offline (lag-free) smoothing of raw labels (None = unknown) -> one label per sample."""
    n = len(raw)
    if not n:
        return []
    h = max(0, int(round(win / step / 2)))
    voted = []
    for i in range(n):
        c = Counter(x for x in raw[max(0, i - h):i + h + 1] if x is not None)
        if c:
            top = c.most_common()
            # a tie keeps the sample's own label when it is one of the leaders
            best = [k for k, v in top if v == top[0][1]]
            voted.append(raw[i] if raw[i] in best else best[0])
        else:
            voted.append(None)
    # fill unknowns from the previous known (or the next known at the start)
    first = next((x for x in voted if x is not None), default)
    cur, filled = first, []
    for x in voted:
        cur = x if x is not None else cur
        filled.append(cur)
    # merge short runs, shortest first, into the longer neighbour
    min_len = max(1, int(round(min_run / step)))
    runs = []
    for x in filled:
        if runs and runs[-1][0] == x:
            runs[-1][1] += 1
        else:
            runs.append([x, 1])
    while len(runs) > 1:
        k = min(range(len(runs)), key=lambda j: runs[j][1])
        if runs[k][1] >= min_len:
            break
        if k == 0:
            j = 1
        elif k == len(runs) - 1:
            j = k - 1
        else:
            j = k - 1 if runs[k - 1][1] >= runs[k + 1][1] else k + 1
        runs[j][1] += runs[k][1]
        del runs[k]
        # neighbours that now carry the same label become one run
        merged = []
        for r in runs:
            if merged and merged[-1][0] == r[0]:
                merged[-1][1] += r[1]
            else:
                merged.append(r)
        runs = merged
    out = []
    for x, c in runs:
        out += [x] * c
    return out


def switches(labels, step=STEP):
    """[(t, label)] at every change (t = 0 for the first)."""
    out = []
    for i, x in enumerate(labels):
        if not out or out[-1][1] != x:
            out.append((i * step, x))
    return out
