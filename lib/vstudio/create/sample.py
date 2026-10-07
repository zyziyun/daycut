"""Open the sample series (samples/if-ads.yaml): bible, ideas and one storyboarded episode. Nothing is generated
or charged; the frames are placeholder cards."""
import os

import yaml

from . import bible as BI, formats as F, jobs, store, storyboard

HERE = os.path.dirname(os.path.abspath(__file__))


def open_sample(lang="en"):
    with open(os.path.join(HERE, "samples", "if-ads.yaml"), encoding="utf-8") as f:
        d = yaml.safe_load(f)
    tx = lambda v: F.text(v, lang)  # noqa: E731
    for sid in store.list_series_ids():
        if store.create_meta(store.load_series_file(sid)).get("sample"):
            eps = store.list_episodes(sid)
            return dict(ok=True, series=sid, episode=eps[0]["id"] if eps else None, existing=True)
    fmt = F.get(d["format"])
    draft = dict(format=fmt["id"], recipe=fmt["recipe"], name=tx(d["name"]), lang=lang, budget_cny=d["budget_cny"],
                 episodes=6, platforms=["youtube-shorts", "tiktok", "xiaohongshu:full", "douyin"], sample=True,
                 prompt="", bible=dict(engine=tx(d["engine"]), beats=F.expand_beats(fmt, lang),
                                       cast=[dict(id=c["id"], name=tx(c["name"]), essence=tx(c["essence"]),
                                                  look=c["look"], own=False, face_locked="kling-mcp",
                                                  voice=dict(engine="qwen3-tts" if c["id"] == "B" else "own"))
                                             for c in d["cast"]],
                                       rules=dict(always=[F.text(r, lang) for r in fmt["rules"]["always"]],
                                                  never=[F.text(r, lang) for r in fmt["rules"]["never"]]),
                                       gags=[], hooks=[], languages=d["languages"], aspect="9:16", length_s=48,
                                       ai_generated=True),
                 ideas=[dict(id=f"i{i + 5}", title=f"Ep. {i + 5} · {tx(x['title'])}" if not lang.startswith("zh")
                             else f"第 {i + 5} 集 · {tx(x['title'])}", logline=tx(x["logline"]), notes="",
                             est_cny=[45, 38, 60, 30][i], picked=bool(x.get("picked"))) for i, x in enumerate(d["ideas"])])
    sid = BI.create_series(draft)
    e = d["episode"]
    eid = store.new_eid(sid, e["no"])
    ep = dict(id=eid, series=sid, no=e["no"], title=tx(e["title"]), logline=tx(e["logline"]), idea={},
              state="boarded", estimates={}, takes={}, created=store.stamp(),
              script=dict(beats=[], source="sample"),
              ladder=dict(stills="todo", animatic="todo", drafts="todo", finals="todo", assemble="todo"),
              shots=[dict(no=s["no"], beat=s["beat"], dur=float(s["dur"]), faces=s.get("faces") or [],
                          camera=s.get("camera", ""), action=s.get("action", ""), lines=s.get("lines") or [],
                          card=s.get("card")) for s in e["shots"]])
    ep["_dir"] = store.episode_dir(eid, sid)
    storyboard.write_aivideo(ep, store.load_bible(sid))
    store.save_episode(ep)
    jobs.run_stills(eid)
    return dict(ok=True, series=sid, episode=eid)
