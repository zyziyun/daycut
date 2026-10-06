"""Fake recipe ``test-v02`` for the v0.2 engine tests (job edit / rerun / deliver / metrics): the stage names and
outputs of the real speech recipes (asr transcript, compose / proofread cues, export files + posts, qc, preview),
no media. Every finished stage is logged to <batch>/calls.log ("<job> <stage>")."""
import json
import os

from vstudio.batch.edits import key_copy
from vstudio.batch.recipes import Recipe, Stage, register
from vstudio.batch.util import write_json

WORDS = ["今天", "我们", "讲", "RAG", "的", "检索", "流程", "。", "向量", "数据库", "很", "重要", "。",
         "最后", "总结", "一下", "。"]


def words_of(p):
    out, t = [], 1.0
    for w in p.get("words") or WORDS:
        if w == "。":
            t += 0.8
            continue
        out.append(dict(word=w, start=round(t, 3), end=round(t + 0.4, 3)))
        t += 0.5
    return out


def _log(ctx, name):
    with open(os.path.join(ctx.batch_dir, "calls.log"), "a") as f:
        f.write(f"{ctx.job['id']} {name}\n")


def probe(ctx):
    _log(ctx, "probe")
    return dict(sha1="fake-" + str(ctx.params.get("source")), files=[])


def asr(ctx):
    ws = words_of(ctx.params)
    tr = dict(language="zh", segments=[dict(start=ws[0]["start"], end=ws[-1]["end"], text="".join(w["word"] for w in ws),
                                            words=ws)])
    p = write_json(ctx.path("transcript.json"), tr)
    _log(ctx, "asr")
    return dict(transcript=p, files=[p])


def compose(ctx):
    cues = [dict(start=float(i * 2.0), end=float(i * 2.0 + 1.8), text=t)
            for i, t in enumerate(ctx.params.get("cues") or ["今天我们讲RAG的检索流程", "向量数据库很重要", "最后总结一下"])]
    p = write_json(ctx.path("cues.json"), dict(cues=cues))
    _log(ctx, "compose")
    return dict(cues=p, master=ctx.params.get("master_file"), duration=6.0, files=[p])


def proofread(ctx):
    d = json.load(open(ctx.inputs["compose"]["cues"], encoding="utf-8"))
    for c in d["cues"]:
        c["text"] = c["text"].replace("RAG", "RAG")
    p = write_json(ctx.path("cues.json"), d)
    r = write_json(ctx.path("proofread.json"), dict(provider="none", changes=[]))
    _log(ctx, "proofread")
    return dict(cues=p, report=r, files=[p, r])


def export(ctx):
    from vstudio.batch.stages import caption_cues
    cues = json.load(open(caption_cues(ctx), encoding="utf-8"))["cues"]
    exports, files = [], []
    p = ctx.params
    for t in p.get("platforms") or ["xiaohongshu:full"]:
        stem = t.replace(":", "-")
        v = ctx.path(stem + ".mp4")
        with open(v, "w", encoding="utf-8") as f:
            f.write("|".join(c["text"] for c in cues) + f"|cover={json.dumps(p.get('cover'), ensure_ascii=False)}")
        c = ctx.path(stem + ".cover.jpg")
        with open(c, "wb") as f:
            f.write(b"\xff\xd8fakejpg")
        post = ctx.path(stem + ".post.md")
        with open(post, "w", encoding="utf-8") as f:
            f.write(f"{p.get('title') or ''}\n\n{p.get('body') or ''}\n\n" + " ".join(f"#{x}" for x in p.get("tags") or [])
                    + " #persona\n")
        name, _, orient = t.partition(":")
        exports.append(dict(platform=name, orientation=orient or "full", file=v, cover=c, post=post, duration=42.0))
        files += [v, c]
    _log(ctx, "export")
    return dict(exports=exports, files=files)


def qc(ctx):
    _log(ctx, "qc")
    red = bool(ctx.params.get("red"))
    return dict(status="red" if red else "green", reasons=["forced"] if red else [], warnings=[], sample=False, files=[])


def preview(ctx):
    _log(ctx, "preview")
    return dict(files=[])


def expand(spec, rows):
    from vstudio.batch import spec as S
    out = []
    for r in rows:
        p = S.with_defaults(spec, r)
        p.setdefault("source", (spec.get("inputs") or {}).get("source") or "src-a")
        p["_src_dur"] = 60.0
        out.append(dict(item=r["id"], params=p))
    return out


register(Recipe(
    name="test-v02", expand=expand, description="fake speech-recipe stages for the v0.2 tests",
    stages=[
        Stage("probe", "io", probe, shared=True, params=lambda j, s: dict(src=j["params"].get("source"))),
        Stage("asr", "asr", asr, deps=("probe",), shared=True,
              params=lambda j, s: dict(src=j["params"].get("source"), w=j["params"].get("words"))),
        Stage("compose", "cpu-render", compose, deps=("asr",),
              params=lambda j, s: dict(range=j["params"].get("range"), hook=j["params"].get("hook"),
                                       cues=j["params"].get("cues"),
                                       **{k: key_copy(j["params"], k) for k in ("title", "body", "tags")})),
        Stage("proofread", "cpu", proofread, deps=("compose",)),
        Stage("export", "cpu-render", export, deps=("compose", "proofread"),
              params=lambda j, s: dict({k: j["params"].get(k) for k in ("platforms", "cover")},
                                       **({"caption_overrides": j["params"]["caption_overrides"]}
                                          if j["params"].get("caption_overrides") else {}))),
        Stage("qc", "cpu", qc, deps=("export",),
              params=lambda j, s: dict(title=j["params"].get("title"), red=j["params"].get("red"))),
        Stage("preview", "cpu", preview, deps=("export",)),
    ]))


def calls(batch_dir):
    p = os.path.join(batch_dir, "calls.log")
    if not os.path.exists(p):
        return []
    with open(p) as f:
        return [tuple(ln.split()) for ln in f if ln.strip()]
