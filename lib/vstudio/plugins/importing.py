"""Import a board: pick the importer, read it, turn it into Create shots.

    sniff(path) -> [{key, id, name, score}]                    best first (enabled importers only)
    read(path, importer=None) -> normalized board               (board.py)
    into_new_series(path, importer=None, fmt=None, lang="en")   -> {series, episode, board}
    into_episode(eid, path, importer=None, mode="replace")      -> {episode, board, n}

A new series from a board uses the format's template bible (no AI call) and the board's title / aspect / message;
the episode's shots are the board's shots, each keeping its ``source`` (e.g. plugin:hyperframes) and ``ref``.
"""
import os

from . import board as B, registry as R


def _err(code, **params):
    from vstudio.create.i18n import CreateError
    return CreateError(code, status=422, **params)


def sniff(path):
    p = os.path.abspath(os.path.expanduser(str(path)))
    if not os.path.exists(p):
        raise _err("import.unreadable", name=os.path.basename(p), error="not found")
    out = []
    for row in R.rows("importer", enabled_only=True):
        try:
            imp = R.instance(row["key"])
            score = float(imp.sniff(p) or 0)
        except Exception:  # noqa: BLE001  (one broken importer never blocks the others)
            continue
        if score > 0:
            out.append(dict(key=row["key"], id=row["id"], name=R.display_name(row), score=round(score, 2)))
    out.sort(key=lambda r: -r["score"])
    return out


def read(path, importer=None):
    p = os.path.abspath(os.path.expanduser(str(path)))
    if importer:
        rows = [dict(key=R.find(importer, "importer")["key"], id=importer)]
    else:
        rows = sniff(p)
    if not rows:
        raise _err("import.unknown-format", name=os.path.basename(p))
    last = None
    for r in rows:
        try:
            raw = R.instance(r["key"]).load(p)
            return B.normalize(raw, importer=r["id"], path=p)
        except B.BoardError as e:
            last = _err(e.code, **e.params)
        except R.PluginError as e:
            last = _err(e.code, **e.params)
        except Exception as e:  # noqa: BLE001
            last = _err("import.unreadable", name=os.path.basename(p), error=str(e)[:200])
    raise last


def _guess_format(board):
    from vstudio.create import formats as F
    if board.get("format") in F.IDS:
        return board["format"]
    return "product-spot"


def _write_shots(ep, shots, bible):
    from vstudio.create import storyboard
    ep["shots"] = shots
    ep["ladder"] = {}
    for k in ("run", "make", "estimates", "animatic"):
        ep.pop(k, None)
    storyboard.write_aivideo(ep, bible)


def into_new_series(path, importer=None, fmt=None, lang="en"):
    from vstudio.create import bible as BI, formats as F, jobs, store
    b = read(path, importer)
    fid = fmt or _guess_format(b)
    F.get(fid)
    draft = BI.plan_series(b["title"], fid, lang=lang, mode="template")
    draft["name"] = b["title"][:60]
    draft["source"] = "import"
    draft["ideas"] = []
    draft["episodes"] = 1
    draft["bible"]["aspect"] = b["aspect"]
    draft["bible"]["length_s"] = round(sum(s["dur"] for s in b["shots"]))
    if b.get("message"):
        draft["bible"]["engine"] = b["message"]
    sid = BI.create_series(draft)
    s = store.load_series_file(sid)
    s["spec"]["create"]["imported"] = dict(importer=b["source"].get("importer"), path=b["source"].get("path"))
    store.save_series_file(s)
    eid = store.new_eid(sid, 1)
    ep = dict(id=eid, series=sid, no=1, title=b["title"], logline=b.get("message") or "", idea={}, state="board",
              shots=[], estimates={}, takes={}, created=store.stamp(), imported=b["source"])
    ep["_dir"] = store.episode_dir(eid, sid)
    _write_shots(ep, B.to_shots(b), store.load_bible(sid))
    store.save_episode(ep)
    jobs.run_stills(eid)
    return dict(ok=True, series=sid, episode=eid, n=len(b["shots"]), importer=b["source"].get("importer"),
                title=b["title"])


def into_episode(eid, path, importer=None):
    """Replace the episode's storyboard with the board (takes already made stay on disk and in ``takes``)."""
    from vstudio.create import jobs, store
    store.need_eid(eid)
    b = read(path, importer)
    with jobs.lock(eid):
        ep = store.load_episode(eid)
        _write_shots(ep, B.to_shots(b), store.load_bible(ep["series"]))
        ep["imported"] = b["source"]
        if ep.get("takes"):                        # numbers change: keep the old takes aside, not on new shots
            ep.setdefault("takes_archive", []).append(dict(at=store.stamp(), takes=ep["takes"], picks=ep.get("picks")))
        ep["takes"], ep["picks"] = {}, {}
        store.save_episode(ep)
    jobs.run_stills(eid)
    return dict(ok=True, episode=eid, n=len(b["shots"]), importer=b["source"].get("importer"), title=b["title"])
