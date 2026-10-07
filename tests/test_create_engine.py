"""vstudio.create: formats, planning (fake LLM + rule fallback), routing, estimates, the spend gate (confirm codes,
budget / cap, unknown rates, price changes, zero resubmits), hardest-first + early stop, ledger, Making view,
hand-off into a normal work folder, Veo request shapes. Fake services only - nothing is ever spent."""
import json
import os
import time

import pytest

from _create_helpers import ROOT, home, needs_ffmpeg, sample_episode  # noqa: F401

from vstudio.create import bible as BI, costs, formats as F, handoff as HO, jobs, providers as PR, routing, store, views
from vstudio.create.i18n import CreateError
import create_fake as fake


# ------------------------------------------------------------------------------------------- formats
def test_formats_load_and_validate():
    fs = F.load_all()
    assert [f["id"] for f in fs] == list(F.IDS)
    for f in fs:
        assert F.label(f, "zh-CN") and F.label(f, "fr") and F.label(f, "en")
        assert F.expand_beats(f, "en")
    assert not any("anime" in (json.dumps(f["labels"]) + json.dumps(f["blurb"])).lower() for f in fs)   # no anime formats
    sa = F.get("series-ad")
    labels = [b["label"] for b in F.expand_beats(sa, "en")]
    assert labels.count("Slogan") == 3


def test_format_label_fallback_and_unknown():
    assert F.text({"en": "Hi"}, "fr") == "Hi"
    assert F.text({"en": "Hi", "zh": "你好"}, "zh-CN") == "你好"
    with pytest.raises(CreateError):
        F.get("anime-drama")


# ------------------------------------------------------------------------------------------- planning
def test_plan_series_with_the_test_ai(home):
    d = BI.plan_series("5-episode series ad for my matcha brand, office comedy, 30 s each, Chinese + English")
    assert d["format"] == "series-ad" and d["source"] == "ai" and fake.ASKED[-1] == "plan_series"
    assert d["episodes"] == 5 and d["bible"]["length_s"] == 30
    assert d["bible"]["languages"] == ["zh", "en"]
    assert len(d["ideas"]) == 4 and d["ideas"][0]["picked"]
    assert d["bible"]["cast"] and d["bible"]["rules"]["never"]


def test_plan_series_with_fake_llm(home, monkeypatch):
    from vstudio import llm
    monkeypatch.setenv("VSTUDIO_LLM_SCRIPT_PROVIDER", "codex")
    fake.real_ai()
    seen = {}

    def fake_complete(task, system, prompt, schema=None, **kw):
        seen["task"], seen["schema"] = task, schema
        return dict(json=dict(format="sketch", name="Office rules", engine="One absurd office rule, escalated.",
                              cast=[dict(id="A", name="Mia", essence="believer", look="green cardigan")],
                              always=["same office set"], never=["no brands"],
                              ideas=[dict(title="The quiet hour", logline="Nobody may speak.")]))
    monkeypatch.setattr(llm, "complete", fake_complete)
    d = BI.plan_series("a comedy sketch series about office rules")
    assert d["source"] == "ai" and d["format"] == "sketch" and d["name"] == "Office rules"
    assert seen["task"] == "script" and "ideas" in seen["schema"]["properties"]


def test_plan_series_llm_failure_is_a_clear_error_then_template_works(home, monkeypatch):
    from vstudio import llm
    monkeypatch.setenv("VSTUDIO_LLM_SCRIPT_PROVIDER", "claude-code")
    fake.real_ai()
    monkeypatch.setattr(llm, "complete", lambda *a, **k: (_ for _ in ()).throw(llm.LLMError("claude CLI: 401 expired")))
    with pytest.raises(CreateError) as ei:
        BI.plan_series("脱口秀段子，讲副业")
    assert ei.value.code == "create.ai-failed" and ei.value.params["reason"] == "auth-expired"
    assert ei.value.params["provider"] == "claude-code"
    d = BI.plan_series("脱口秀段子，讲副业", mode="template")                    # "Start from the template"
    assert d["format"] == "talk-show" and d["source"] == "template" and d["lang"] == "zh"


def test_plan_series_no_ai_set_up_is_a_clear_error_never_a_silent_swap(home, monkeypatch):
    from vstudio import llm
    fake.real_ai()
    called = []
    monkeypatch.setattr(llm, "complete", lambda *a, **k: called.append(1))
    monkeypatch.setattr(llm, "route", lambda *a, **k: llm.Route("none", None, {}, "legacy-auto"))
    steps = []
    with pytest.raises(CreateError) as ei:
        BI.plan_series("", "series-ad", budget=60, lang="zh", on_event=steps.append)
    assert ei.value.params["reason"] == "not-set-up" and not called
    assert [s["step"] for s in steps] == ["read", "ai-failed"]
    steps.clear()
    d = BI.plan_series("", "series-ad", budget=60, platforms=["douyin", "xiaohongshu:full", "tiktok", "youtube-shorts"],
                       lang="zh", mode="template", on_event=steps.append)
    assert not called and d["source"] == "template" and d["format"] == "series-ad"
    assert [s["step"] for s in steps] == ["read", "template"]
    assert d["name"] and len(d["ideas"]) == 4 and all(c["look"] for c in d["bible"]["cast"])
    assert d["budget_cny"] == 60 and len(d["platforms"]) == 4
    with pytest.raises(CreateError):
        BI.plan_series("", "series-ad", mode="rules")


def test_plan_series_hanging_ai_times_out_with_steps(home, monkeypatch):
    """Her bug: Claude Code (expired login) never answers -> Plan spun forever. Now: bounded, steps, clear error."""
    import threading
    from vstudio import llm
    monkeypatch.setenv("VSTUDIO_LLM_SCRIPT_PROVIDER", "claude-code")
    monkeypatch.setenv("VSTUDIO_CREATE_AI_TIMEOUT", "0.2")
    monkeypatch.setenv("VSTUDIO_CREATE_AI_DEADLINE", "0.6")
    fake.real_ai()
    gate = threading.Event()
    seen = {}

    def hang(task, system, prompt, **kw):
        seen.update(kw)
        kw["on_fallback"]({"from": "claude-code", "to": "codex", "code": "timeout", "error": "timed out"})
        gate.wait(5)
    monkeypatch.setattr(llm, "complete", hang)
    steps = []
    t0 = time.time()
    with pytest.raises(CreateError) as ei:
        BI.plan_series("", "series-ad", budget=60, lang="zh", on_event=steps.append)
    gate.set()
    assert time.time() - t0 < 3
    assert ei.value.params["reason"] == "timeout"
    assert seen["cli_timeout"] == 0.2 and seen["timeout"] == 0.2              # each CLI attempt is capped
    names = [s["step"] for s in steps]
    assert names[:2] == ["read", "bible"] and "fallback" in names and names[-1] == "ai-failed"
    assert next(s for s in steps if s["step"] == "fallback")["to"] == "codex"


def test_plan_cli_template_mode_and_events(home, capsys):
    from vstudio.create import cli
    assert cli.main(["--json-events", "plan", "--format", "series-ad", "--budget", "60", "--platforms",
                     "douyin,xiaohongshu:full", "--lang", "zh", "--mode", "template"]) == 0
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]
    assert [x["step"] for x in lines if x.get("event") == "create.step"] == ["read", "template"]
    assert lines[-1]["result"]["draft"]["source"] == "template"


def test_create_series_writes_files_without_secrets(home, monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-should-never-be-written")
    d = BI.plan_series("product spot for a water bottle", budget=60, platforms=["douyin"])
    sid = BI.create_series(d)
    sdir = store.series_dir(sid)
    for f in ("series.yaml", "bible.yaml", "ideas.yaml"):
        assert os.path.exists(os.path.join(sdir, f))
    s = store.load_series_file(sid)
    assert s["spec"]["create"]["format"] == "product-spot" and s["spec"]["create"]["budget_cny"] == 60
    blob = "".join(open(os.path.join(r, f), encoding="utf-8").read() for r, _, fs in os.walk(sdir) for f in fs)
    assert "sk-should-never-be-written" not in blob and "API_KEY" not in blob
    with pytest.raises(ValueError):
        store.write_yaml(os.path.join(sdir, "x.yaml"), {"api_key": "sk-123"})


def test_bible_revise_rules_and_ideas(home):
    sid = BI.create_series(BI.plan_series("series ad for umbrellas"))
    b = BI.revise_bible(sid, "never show real logos")
    assert "never show real logos" in b["rules"]["never"]
    b = BI.revise_bible(sid, "make B more stubborn")
    assert "make B more stubborn" in b["rules"]["always"]
    new = BI.more_ideas(sid, 2)
    assert len(new) == 2 and new[0]["id"] == "i5"


def test_bible_ideas_and_scripts_never_fall_back_to_rules(home, monkeypatch):
    """No AI answer -> a clear create.ai-failed with the reason: never rules made up in its place (no-mock rule)."""
    from vstudio import llm
    from vstudio.create import script
    sid = BI.create_series(BI.plan_series("series ad for umbrellas"))
    fake.real_ai()
    monkeypatch.setenv("VSTUDIO_LLM_SCRIPT_PROVIDER", "claude-code")
    monkeypatch.setattr(llm, "complete", lambda *a, **k: (_ for _ in ()).throw(llm.LLMError("claude CLI: 401 expired")))
    before, ideas = store.load_bible(sid), store.load_ideas(sid)
    for call in (lambda: BI.revise_bible(sid, "never show real logos"), lambda: BI.more_ideas(sid, 2),
                 lambda: script.add_episodes(sid, ["i1"])):
        with pytest.raises(CreateError) as ei:
            call()
        assert ei.value.code == "create.ai-failed" and ei.value.params["reason"] == "auth-expired"
    assert store.load_bible(sid) == before and store.load_ideas(sid) == ideas and store.list_episodes(sid) == []
    monkeypatch.setattr(llm, "route", lambda *a, **k: llm.Route("none", None, {}, "legacy-auto"))
    with pytest.raises(CreateError) as ei:
        script.add_episodes(sid, ["i1"])
    assert ei.value.params["reason"] == "not-set-up"


def test_episodes_add_writes_script_board_stills(home):
    from vstudio.create import script
    sid = BI.create_series(BI.plan_series("comedy sketch about a robot barista"))
    eps = script.add_episodes(sid, ["i1", "i2"])
    assert len(eps) == 2
    ep = store.load_episode(eps[0]["id"])
    assert ep["shots"] and ep["script"]["beats"] and ep["state"] == "boarded"
    assert os.path.exists(os.path.join(ep["_dir"], "work", "ai", "project.yaml"))
    assert abs(sum(s["dur"] for s in ep["shots"]) - store.load_bible(sid)["length_s"]) < 12
    jobs.run_stills(ep["id"])
    assert all(os.path.exists(s["still"]) for s in store.load_episode(ep["id"])["shots"])


# ------------------------------------------------------------------------------------------- routing
def test_routing_policy_override_and_cheapest(home):
    sid, eid = sample_episode()
    ep, s, fmt, _ = jobs.context(eid)
    routes, warns = routing.resolve(ep, s, fmt, connected=["kling-mcp", "minimax"])
    by = {r["no"]: r for r in routes}
    assert by["02"]["provider"] == "kling-mcp"          # faces -> Kling (character lock)
    assert by["08"]["kind"] == "card"                   # text cards are made in post
    assert by["01"]["provider"] == "minimax"            # no faces -> cheapest CONNECTED (Veo not connected)
    routes2, _ = routing.resolve(ep, s, fmt, connected=["kling-mcp", "minimax", "veo"])
    assert {r["no"]: r for r in routes2}["01"]["provider"] == "veo"   # Veo Lite 4 s is cheaper once connected
    jobs.set_source(eid, "01", "cloud:kling-mcp/kling-video-v3_0_omni")
    ep = store.load_episode(eid)
    by = {r["no"]: r for r in routing.resolve(ep, s, fmt, ["minimax"])[0]}
    assert by["01"]["provider"] == "kling-mcp" and by["01"]["why"] == "create.route.override"
    with pytest.raises(CreateError):
        jobs.set_source(eid, "01", "http://evil")


def test_character_lock_warning(home):
    sid, eid = sample_episode()
    jobs.set_source(eid, "07", "cloud:veo/veo-3.1-fast")
    ep, s, fmt, _ = jobs.context(eid)
    _, warns = routing.resolve(ep, s, fmt, ["kling-mcp", "veo"])
    w = [x for x in warns if x["code"] == "create.route.character-split"]
    assert w and w[0]["params"]["cast"] == "B" and w[0]["params"]["shots"] == ["07"]


def test_units_match_aivideo_compile_units(home):
    from vstudio.create.providers.aivideo import plan_module
    PL = plan_module()
    import yaml
    cfg = yaml.safe_load((ROOT / "workflows" / "ai-video" / "templates" / "project.yaml").read_text())
    shots = [dict(no=str(s["id"]).zfill(2) if str(s["id"]).isdigit() else str(s["id"]), dur=s.get("dur", 2),
                  faces=s.get("chars") or [], unit=s.get("unit")) for s in cfg["shots"]]
    ep = dict(id="x", shots=shots)
    routes = [dict(no=s["no"], source="cloud:kling-mcp/kling-video-v3_0_omni", kind="mcp", provider="kling-mcp",
                   model="kling-video-v3_0_omni", hard=False) for s in shots]
    mine = routing.units(ep, routes)
    theirs = PL.compile_units(dict(cfg, model="", shots=[dict(s, id=sh["no"]) for s, sh in zip(cfg["shots"], shots)]))
    assert [u["shots"] for u in mine] == [[str(s["id"]) for s in u.shots] for u in theirs]
    assert [u["seconds"] for u in mine if len(u["shots"]) > 1] == [u.dur for u in theirs if len(u.shots) > 1]


def test_rule_route_instruction(home):
    sid, eid = sample_episode()
    ep, s, fmt, _ = jobs.context(eid)
    routes, _ = routing.resolve(ep, s, fmt, ["kling-mcp", "minimax"])
    ch = routing.rule_instruction(ep, routes, "make every shot without faces cheaper", ["minimax", "veo"])
    assert ch and all(not next(x for x in ep["shots"] if x["no"] == c["no"])["faces"] for c in ch)
    ch = routing.rule_instruction(ep, routes, "07 用海螺")
    assert ch == [dict(no="07", **{"from": "cloud:kling-mcp/kling-video-v3_0_omni", "to": "cloud:minimax/MiniMax-Hailuo-02"})]


# ------------------------------------------------------------------------------------------- costs
def test_min_clip_rounding_and_prices():
    v = costs.price_job("veo", "veo-3.1-fast", 2.0, "720p")
    assert v["seconds_billed"] == 4 and abs(v["cny"] - 2.84) < 0.05            # $0.10/s at 720p
    assert costs.price_job("veo", "veo-3.1-fast", 2.0)["seconds_billed"] == 8   # 1080p = 8 s clips only
    assert costs.price_job("veo", "veo-3.1-fast", 6.5, "720p")["seconds_billed"] == 8
    h = costs.price_job("minimax", "MiniMax-Hailuo-02", 2.0)
    assert h["seconds_billed"] == 6 and abs(h["cny"] - 1.99) < 0.05             # ¥2.0
    assert costs.price_job("minimax", "MiniMax-Hailuo-02", 7)["seconds_billed"] == 10
    k = costs.price_job("kling-mcp", "kling-video-v3_0_omni", 2.0)
    assert k["seconds_billed"] == 5 and k["native_units"] == 60 and abs(k["cny"] - 5.0) < 0.05   # ¥5.0, 60 credits
    j = costs.price_job("jimeng", "seedance-2", 3)
    assert j["manual"] and j["cny"] == 0.0 and j["native_units"] == 32
    assert costs.price_job("nobody", "x", 3)["unknown"]


def test_estimate_retry_allowance_and_code(home):
    sid, eid = sample_episode()
    est = jobs.estimate(eid, "finals")
    assert est["retry_pct"] == 0.30
    assert est["max_cny"] == round(est["subtotal_cny"] + round(est["subtotal_cny"] * 0.3, 1), 1)
    assert len(est["confirm_code"]) == 8 and est["expires_at"] - time.time() > 800
    assert est["id"] in store.load_episode(eid)["estimates"]
    assert est["free"].get("card") == 2 and est["hard_first"]
    assert jobs.estimate(eid, "stills")["confirm_code"] is None


def test_no_submit_without_confirm(home):
    sid, eid = sample_episode()
    est = jobs.estimate(eid, "finals")
    for bad in [dict(), dict(estimate_id=est["id"]), dict(estimate_id=est["id"], confirm_code="deadbeef",
                                                          max_cny=est["max_cny"]),
                dict(estimate_id=est["id"], confirm_code=est["confirm_code"], max_cny=est["max_cny"] - 1)]:
        with pytest.raises(CreateError) as e:
            jobs.run(eid, "finals", **bad)
        assert e.value.status == 409
    assert fake.SUBMITS == []
    assert costs.ledger(sid) == []


def test_one_ok_submits_once(home):
    """The same estimate + code a second time (double click, a second window) is refused before any submit."""
    sid, eid = sample_episode()
    shots = ["01", "10", "15"]
    for no in shots:
        jobs.set_source(eid, no, "cloud:minimax/MiniMax-Hailuo-02")
    est = jobs.estimate(eid, "finals", only=shots)
    assert est["subtotal_cny"] == 6.0 and est["max_cny"] == 7.8
    jobs.run(eid, "finals", est["id"], est["confirm_code"], est["max_cny"], only=shots)
    assert len(fake.SUBMITS) == 3
    with pytest.raises(CreateError) as e:
        jobs.run(eid, "finals", est["id"], est["confirm_code"], est["max_cny"], only=shots)
    assert e.value.code == "create.confirm-used"
    assert len(fake.SUBMITS) == 3
    assert [r["status"] for r in costs.ledger(sid)] == ["submitted"] * 3


def test_veo_1080p_is_8s_only_and_priced_per_resolution():
    e = costs.entry("veo", "veo-3.1-fast")
    assert costs.snap(e, 3, "1080p") == 8 and costs.snap(e, 3, "720p") == 4
    assert costs.price_job("veo", "veo-3.1-fast", 3)["cny"] == round(0.12 * 8 * 7.1, 2)
    assert costs.price_job("veo", "veo-3.1-fast", 3, "720p")["cny"] == round(0.10 * 4 * 7.1, 2)
    assert costs.price_job("veo", "veo-3.1-lite", 5)["seconds_billed"] == 6


def test_job_uses_the_services_own_model_id(home, monkeypatch):
    sid, eid = sample_episode()
    jobs.set_source(eid, "01", "cloud:seedance-ark/seedance-2")
    jobs.set_source(eid, "10", "cloud:veo/veo-3.1-fast")
    ep, s, fmt, bible = jobs.context(eid)
    _, units, _ = jobs.plan(ep, s, fmt, ["01", "10"])
    by = {u["shots"][0]: u for u in units}
    ark = jobs.build_job(ep, bible, by["01"])
    assert ark.model == costs.entry("seedance-ark", "seedance-2")["api_model"] and ark.duration == 4
    monkeypatch.setenv("ARK_SEEDANCE_MODEL", "my-ark-endpoint")
    assert jobs.build_job(ep, bible, by["01"]).model == "my-ark-endpoint"
    veo = jobs.build_job(ep, bible, by["10"])
    assert (veo.model, veo.resolution, veo.duration) == ("veo-3.1-fast", "1080p", 8)


def test_confirm_expired_and_plan_changed(home):
    sid, eid = sample_episode()
    est = jobs.estimate(eid, "finals")
    ep = store.load_episode(eid)
    ep["estimates"][est["id"]]["expires_at"] = time.time() - 1
    store.save_episode(ep)
    with pytest.raises(CreateError) as e:
        jobs.run(eid, "finals", est["id"], est["confirm_code"], est["max_cny"])
    assert e.value.code == "create.confirm-expired"
    est = jobs.estimate(eid, "finals")
    jobs.set_source(eid, "01", "cloud:kling-mcp/kling-video-v3_0_omni")       # the plan changed after the OK
    with pytest.raises(CreateError) as e:
        jobs.run(eid, "finals", est["id"], est["confirm_code"], est["max_cny"])
    assert e.value.code == "create.plan-changed"
    assert fake.SUBMITS == []


def test_budget_and_cap_refusals_in_engine(home):
    sid, eid = sample_episode()
    s = store.load_series_file(sid)
    s["spec"]["create"]["budget_cny"] = 10
    store.save_series_file(s)
    est = jobs.estimate(eid, "finals")
    with pytest.raises(CreateError) as e:
        jobs.run(eid, "finals", est["id"], est["confirm_code"], est["max_cny"])
    assert e.value.code == "create.over-budget"
    s["spec"]["create"]["budget_cny"] = 1000
    store.save_series_file(s)
    costs.set_cap(20)
    est = jobs.estimate(eid, "finals")
    with pytest.raises(CreateError) as e:
        jobs.run(eid, "finals", est["id"], est["confirm_code"], est["max_cny"])
    assert e.value.code == "create.over-cap"
    assert fake.SUBMITS == []


def test_unknown_rate_refused_unless_allowed(home, tmp_path, monkeypatch):
    rates = json.loads((ROOT / "lib" / "vstudio" / "create" / "rates.json").read_text())
    del rates["providers"]["kling-mcp"]["kling-video-v3_0_omni"]["cny_per_credit"]
    p = tmp_path / "rates.json"
    p.write_text(json.dumps(rates))
    monkeypatch.setenv("VSTUDIO_CREATE_RATES", str(p))
    sid, eid = sample_episode()
    est = jobs.estimate(eid, "finals")
    assert est["unknown"]
    with pytest.raises(CreateError) as e:
        jobs.run(eid, "finals", est["id"], est["confirm_code"], est["max_cny"])
    assert e.value.code == "create.unknown-rate"
    assert fake.SUBMITS == []
    monkeypatch.delenv("VSTUDIO_CREATE_RATES")
    costs.load_rates()


def test_price_changed_refusal(home):
    PR.set_fake(fake.FakeProvider, **{"kling-mcp": dict(quote_factor=1.2, balance=5000)})
    sid, eid = sample_episode()
    est = jobs.estimate(eid, "finals")
    with pytest.raises(CreateError) as e:
        jobs.run(eid, "finals", est["id"], est["confirm_code"], est["max_cny"])
    assert e.value.code == "create.price-changed"
    assert fake.SUBMITS == []


def test_low_credits_refusal(home):
    PR.set_fake(fake.FakeProvider, **{"kling-mcp": dict(balance=10)})
    sid, eid = sample_episode()
    est = jobs.estimate(eid, "finals")
    with pytest.raises(CreateError) as e:
        jobs.run(eid, "finals", est["id"], est["confirm_code"], est["max_cny"])
    assert e.value.code == "create.low-credits"


def test_run_finals_hardest_first_and_ledger(home):
    sid, eid = sample_episode()
    est = jobs.estimate(eid, "finals")
    res = jobs.run(eid, "finals", est["id"], est["confirm_code"], est["max_cny"])
    assert res["run"]["state"] == "done"
    order = [u for p, u in fake.SUBMITS]
    hard = [f"u{no}" for no in est["hard_first"]]
    assert order[:3] == hard or set(order[:3]) == set(hard)      # the 3 hardest go first
    assert len(order) == len(set(order))                          # each unit submitted exactly once
    led = costs.ledger(sid)
    assert len([r for r in led if r["status"] == "submitted"]) == len(order)
    assert costs.spent(sid) <= est["max_cny"]
    assert costs.month()["used_cny"] == costs.spent(sid)
    st = json.load(open(os.path.join(store.load_episode(eid)["_dir"], "work", "ai", "state.json")))
    assert st["pending"] == {} and st["takes"]


def test_early_stop_after_two_hard_failures(home):
    sid, eid = sample_episode()
    est0 = jobs.estimate(eid, "finals")
    hard = [f"u{no}" for no in est0["hard_first"]]
    PR.set_fake(fake.FakeProvider, **{"kling-mcp": dict(fail=set(hard[:2]), balance=5000)})
    fake.reset()
    est = jobs.estimate(eid, "finals")
    res = jobs.run(eid, "finals", est["id"], est["confirm_code"], est["max_cny"])
    assert res["run"]["state"] == "paused"
    assert res["run"]["paused"]["code"] == "create.hard-shots-failed"
    assert len(fake.SUBMITS) == 3                                 # nothing after the 3 hard shots


def test_timeout_is_unknown_charge_never_resubmitted(home):
    sid, eid = sample_episode()
    est0 = jobs.estimate(eid, "finals")
    target = f"u{est0['hard_first'][0]}"
    prov = fake.FakeProvider(PR.info("kling-mcp"), timeout={target}, balance=5000)
    PR.install("kling-mcp", prov)
    est = jobs.estimate(eid, "finals")
    res = jobs.run(eid, "finals", est["id"], est["confirm_code"], est["max_cny"])
    assert prov.submits.count(target) == 1                        # ZERO resubmits
    assert res["run"]["units"][target]["state"] == "unknown-charge"
    led = [r for r in costs.ledger(sid) if r["unit"] == target]
    assert len(led) == 1 and led[0]["status"] == "unknown-charge"
    m = views.making(sid)
    assert any(a["code"] == "create.unknown-charge" for a in m["alerts"])
    # a single-shot retry is a NEW estimate + confirm, never automatic
    no = target[1:]
    est1 = jobs.estimate(eid, "finals", only=[no])
    assert est1["only"] == [no] and est1["confirm_code"] != est["confirm_code"]
    jobs.run(eid, "finals", est1["id"], est1["confirm_code"], est1["max_cny"], only=[no])
    assert prov.submits.count(target) == 2


def test_rejected_submit_not_counted(home):
    sid, eid = sample_episode()
    est0 = jobs.estimate(eid, "finals")
    target = f"u{est0['hard_first'][0]}"
    PR.set_fake(fake.FakeProvider, **{"kling-mcp": dict(reject={target}, balance=5000)})
    est = jobs.estimate(eid, "finals")
    jobs.run(eid, "finals", est["id"], est["confirm_code"], est["max_cny"])
    row = [r for r in costs.ledger(sid) if r["unit"] == target][0]
    assert row["status"] == "rejected" and row["est_cny"] == 0


def test_manual_jimeng_writes_prompts_never_submits(home):
    sid, eid = sample_episode()
    jobs.set_source(eid, "15", "manual:jimeng/seedance-2")
    est = jobs.estimate(eid, "finals")
    assert any(ln["manual"] for ln in est["lines"])
    jobs.run(eid, "finals", est["id"], est["confirm_code"], est["max_cny"])
    assert not any(u == "u15" for _, u in fake.SUBMITS)
    ep = store.load_episode(eid)
    assert os.path.exists(os.path.join(ep["_dir"], "work", "ai", "sheets", "PROMPTS.md"))
    assert ep["run"]["units"]["u15"]["state"] == "manual-waiting"


def test_takes_pick_and_making_view(home):
    sid, eid = sample_episode()
    est = jobs.estimate(eid, "finals")
    jobs.run(eid, "finals", est["id"], est["confirm_code"], est["max_cny"])
    ep = store.load_episode(eid)
    multi = {no: t for no, t in ep["takes"].items() if len(t) > 1}
    assert multi and ep["ladder"]["finals"] == "pick"
    m = views.making(sid)
    assert any(c["state"] == "pick" for c in m["rows"][0]["cells"])
    for no, t in multi.items():
        jobs.pick(eid, no, os.path.basename(t[-1]["file"]))
    assert store.load_episode(eid)["ladder"]["finals"] == "done"
    with pytest.raises(CreateError):
        jobs.pick(eid, "02", "/etc/passwd")


@needs_ffmpeg
def test_handoff_creates_a_normal_work_folder(home):
    sid, eid = sample_episode()
    est = jobs.estimate(eid, "finals")
    jobs.run(eid, "finals", est["id"], est["confirm_code"], est["max_cny"])
    for no, t in store.load_episode(eid)["takes"].items():
        jobs.pick(eid, no, t[0]["file"])
    h = HO.handoff(eid, ["en", "zh", "fr"])
    assert os.path.exists(h["file"]) and h["file"].endswith(".mp4")
    from vstudio.project import home as H, works
    rec = works.show(h["dir"])
    assert rec["kind"] == "work" and rec["recipe"] == "ai-video" and rec["outputs"]
    assert any(p["dir"] == h["dir"] and p.get("kind") == "work" for p in H.projects())
    assert [p["lang"] for p in h["posts"]] == ["en", "zh", "fr"] and all("T" in p["at"] for p in h["posts"])
    post = open(os.path.join(h["dir"], "post.md"), encoding="utf-8").read()
    assert "AI" in post
    assert os.path.exists(os.path.join(h["dir"], "final", f"{h['clip']}.en.srt"))
    # the desk lists the folder under the id of its real path (desk_engine.common.batch_id): /var and /private/var
    # spellings of one folder are one item, so Send to Publish finds it
    import hashlib
    assert h["item_id"] == hashlib.sha1(os.path.realpath(h["dir"]).encode()).hexdigest()[:12]


def test_spend_summary_and_cap(home):
    sid, eid = sample_episode()
    costs.set_cap(120)
    s = costs.summary(sid)
    assert s["cap"] == 120 and s["series"]["budget"] == 300 and s["series"]["spent"] == 0
    with pytest.raises(CreateError):
        costs.set_cap(-5)


# ------------------------------------------------------------------------------------------- Veo adapter
def test_veo_request_and_poll_shapes(monkeypatch):
    from vstudio.create.providers import veo as V
    from vstudio.create.providers.aivideo import make_job
    calls = []

    def transport(url, data=None, headers=None, method=None, timeout=120):
        calls.append((url, json.loads(data) if data else None, headers, method))
        if url.endswith(":predictLongRunning"):
            return json.dumps({"name": "models/veo-3.1-fast-generate-preview/operations/op1"}).encode(), {}
        if "operations/op1" in url:
            return json.dumps({"done": True, "response": {"generateVideoResponse": {"generatedSamples": [
                {"video": {"uri": "https://example.invalid/v.mp4"}}]}}}).encode(), {}
        return b"bytes", {}
    p = V.Veo(key="k-test", transport=transport)
    job = make_job(unit="u07", model="veo-3.1-fast", prompt="B yells at the clasp", duration=4, aspect="9:16",
                   resolution="1080p")
    tid = p.submit(job)
    assert tid.endswith("operations/op1")
    url, body, headers, method = calls[0]
    assert "veo-3.1-fast-generate-preview:predictLongRunning" in url and method == "POST"
    assert headers["x-goog-api-key"] == "k-test"
    assert body["parameters"] == {"aspectRatio": "9:16", "durationSeconds": 4, "resolution": "1080p"}
    r = p.poll(tid)
    assert r["status"] == "done" and r["urls"] == ["https://example.invalid/v.mp4"]

    def boom(*a, **k):
        raise V.TransportError("timed out")
    with pytest.raises(PR.SubmitTimeout):
        V.Veo(key="k", transport=boom).submit(job)


def test_detect_never_ready_without_keys(monkeypatch):
    PR.set_fake(None)
    for k in ("KLING_MCP_TOKEN", "MINIMAX_API_KEY", "GEMINI_API_KEY", "ARK_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    d = {x["id"]: x for x in PR.detect()}
    assert not d["kling-mcp"]["ready"] and d["kling-mcp"]["code"] == "create.provider.missing-key"
    assert d["jimeng"]["ready"] and d["jimeng"]["kind"] == "manual"
    assert d["local-rapidmlx"]["code"] == "create.local-off"
    with pytest.raises(CreateError):
        PR.get("jimeng").submit(None)
    PR.set_fake(None)


def test_cli_json_error_shape(home, capsys):
    from vstudio.create import cli
    rc = cli.main(["--home", str(home), "--json", "run", "nope-e01", "--stage", "finals"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 2 and out["error"]["code"] in ("create.not-found", "create.confirm-required")


def test_no_fake_switch_in_the_engine(monkeypatch):
    """No-mock rule: only a test can stand fakes in (set_fake); no env var or CLI flag turns them on."""
    from vstudio.create import cli
    PR.set_fake(None)
    monkeypatch.setenv("VSTUDIO_CREATE_FAKE", "1")
    assert not PR.fake_mode()
    with pytest.raises(SystemExit):
        cli.parser().parse_args(["--fake", "formats"])
    src = os.path.join(ROOT, "lib", "vstudio", "create")
    blob = "".join(open(os.path.join(r, f), encoding="utf-8").read() for r, _, fs in os.walk(src) for f in fs
                   if f.endswith(".py"))
    assert "VSTUDIO_CREATE_FAKE" not in blob and "VSTUDIO_CREATE_NO_LLM" not in blob
    assert not os.path.exists(os.path.join(src, "providers", "fake.py"))
