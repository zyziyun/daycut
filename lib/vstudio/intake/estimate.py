"""Rough cost / time per planned sub-project, from the vstudio.batch bench table (measured on this machine when a
batch has run here, else the built-in guesses) plus a small table for render-heavy / paid steps.

Numbers are for a plan card, not a quote: ``measured`` says whether any stage time came from this machine.
"""
from vstudio import llm as LLM

# stage -> what its unit counts: "src" (seconds of source media, once per source), "out" (seconds of output, per
# platform for export), "job" (once per item)
SPEECH_STAGES = [("probe", "job"), ("extract", "src"), ("asr", "src"), ("cleanup", "out"), ("apply", "out"),
                 ("compose", "out"), ("export", "out*p"), ("verify", "out"), ("qc", "out"), ("preview", "job")]
EXTRA = {
    "longform-to-short": [("geometry", "src")],
    "longform-course": [("geometry", "src")],
}
# seconds of machine time per output second for render-heavy recipes (no bench rows for these yet)
RENDER_S_PER_OUT = {"explainer": 6.0, "photo-story": 2.0, "vlog": 1.5, "promo-recut": 4.0, "slides": 0.5,
                    "cover": 0.0, "preproduction": 0.0, "ai-video": 1.0}
DEFAULT_OUT_S = {"explainer": {"short": 60, "long": 300}, "photo-story": 75, "vlog": 90, "ai-video": 60,
                 "promo-recut": 120, "slides": 45}
TTS_USD_PER_MIN = 0.015          # gpt-4o-mini-tts, about
LLM_USD_PER_SOURCE_MIN = 0.01    # plan-segments + proofread + glossary on an API model, about
SPEECH_RECIPES = {"talkinghead", "longform-to-short", "call-clips", "longform-course", "promo-recut", "batch", "polish",
                  "lesson-clips", "interview-qa"}


def _bench():
    try:
        from vstudio.batch import estimate as E
        return E.bench_table(None), E.FALLBACK
    except Exception:  # noqa: BLE001
        return {}, dict(sec_per_unit=0.5, bytes_per_unit=1e5)


def _paid_llm(tasks, client_cfg=None):
    """True when any of these LLM tasks routes to a paid API (subscription CLIs / local / none are free here)."""
    for t in tasks:
        try:
            p = LLM.route(t, config=client_cfg).provider
        except Exception:  # noqa: BLE001
            continue
        if p not in ("none", "claude-code", "codex") and p not in getattr(LLM, "LOCAL", ()):
            return True
    return False


def project(p, src_s, out_s, n_items, n_platforms, client_cfg=None):
    """-> {machine_min, wall_min, storage_mb, api_usd, credits, measured, basis, paid_steps}"""
    bench, fb = _bench()
    rid = p["recipe"]
    machine, storage, measured = 0.0, 0.0, False
    paid = []
    if rid in SPEECH_RECIPES:
        for st, unit in SPEECH_STAGES + EXTRA.get(rid, []):
            b = bench.get(st) or dict(fb, measured=False)
            u = {"src": src_s, "out": out_s, "out*p": out_s * max(1, n_platforms), "job": n_items}[unit]
            machine += b["sec_per_unit"] * u
            storage += b.get("bytes_per_unit", 0) * u
            measured = measured or bool(b.get("measured"))
    machine += RENDER_S_PER_OUT.get(rid, 0.0) * out_s * (max(1, n_platforms) if rid not in SPEECH_RECIPES else 0)
    if rid not in SPEECH_RECIPES:
        storage += out_s * max(1, n_platforms) * 1.0e6
    api = 0.0
    if rid in SPEECH_RECIPES and _paid_llm(("segment_plan", "proofread", "glossary"), client_cfg):
        api += LLM_USD_PER_SOURCE_MIN * src_s / 60
        paid.append("LLM（选段 / 字幕校对）")
    params = p.get("params") or {}
    if rid == "explainer" and (params.get("tts_engine") or "openai") == "openai":
        api += TTS_USD_PER_MIN * out_s / 60
        paid.append("配音 TTS")
    if rid == "photo-story" and params.get("mode", "narration") == "narration" and \
            (params.get("tts_engine") or "openai") == "openai":
        api += TTS_USD_PER_MIN * out_s / 60 * 0.8
        paid.append("旁白 TTS")
    credits = None
    if rid == "ai-video":
        credits = "按镜头计费：生成前在预算检查点报价"
        paid.append("AI 视频生成积分")
    wall_min = machine / 2.0 / 60 + (5 * n_items if rid == "ai-video" else 0)   # 2 lanes; AIGC queues ~5 min / ep
    return dict(machine_min=round(machine / 60, 1), wall_min=round(wall_min, 1),
                storage_mb=round(storage / 1e6), api_usd=round(api, 2), credits=credits, measured=measured,
                paid_steps=paid, basis=dict(source_s=round(src_s), output_s=round(out_s), items=n_items,
                                            platforms=n_platforms))


def total(projects):
    t = dict(machine_min=0.0, wall_min=0.0, storage_mb=0, api_usd=0.0, paid_steps=[], measured=False)
    for p in projects:
        e = p.get("estimate") or {}
        t["machine_min"] = round(t["machine_min"] + e.get("machine_min", 0), 1)
        t["wall_min"] = round(max(t["wall_min"], e.get("wall_min", 0)), 1)      # sub-projects run side by side
        t["storage_mb"] += e.get("storage_mb", 0)
        t["api_usd"] = round(t["api_usd"] + e.get("api_usd", 0), 2)
        t["paid_steps"] += [x for x in e.get("paid_steps") or [] if x not in t["paid_steps"]]
        t["measured"] = t["measured"] or bool(e.get("measured"))
        if e.get("credits"):
            t["credits"] = e["credits"]
    return t
