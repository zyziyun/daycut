"""The test engine's other parts: history rows for the in-memory batches, clip transcription from an .srt next to the
file, and Create with fake video services and a fake AI in this process (tests/create_fake.py). Tests only.

  DESK_MOCK_ASR_STEP   seconds 「听一遍」 takes (default 2)
"""
import importlib.util
import os
import time

from desk_engine.autopilot import Autopilot
from desk_engine.common import BadRequest, need, write_json
from desk_engine.create import CreateApi, Refused
from desk_engine.history import History
from desk_engine.timeline import Strips, parse_srt, tokens

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), *[".."] * 6))


class MockHistory(History):
    def __init__(self, data_dir, registry, engine=None):
        super().__init__(data_dir, registry, engine)
        self.extra_work = set()                     # Create hand-offs (not put in her projects.json)

    def _candidates(self):
        out, series = super()._candidates()
        for d in sorted(self.extra_work):
            out.append(("work", d, "create", {}))
        return out, series

    def list(self, *a, **kw):
        """Simulated projects say whether they run on autopilot (a real project's project.yaml does)."""
        from .intake import mock_autopilot
        doc = super().list(*a, **kw)
        for r in doc["items"]:
            if r.get("kind") == "work" and r.get("dir"):
                ap = mock_autopilot(r["dir"])
                if ap:
                    r["autopilot"] = bool(ap.get("on"))
        return doc

    def _more_rows(self, have):
        """The in-memory demo batches have no folder on disk: listed like found batches."""
        if not hasattr(self.engine, "list_batches"):
            return []
        out = []
        for b in self.engine.list_batches():
            if b["id"] in have:
                continue
            c = b.get("counts") or {}
            done = c.get("done", 0) + c.get("approved", 0) + c.get("packaged", 0)
            st = "delivered" if b.get("delivered") else "packaged" if b.get("package") else \
                "done" if c.get("total") and done >= c["total"] else "in-progress"
            counts = dict(total=c.get("total", 0), green=c.get("green", 0), red=c.get("red", 0),
                          approved=c.get("approved", 0), done=done, failed=c.get("failed", 0))
            live = dict(state="running", status="running", needs_you=False, heartbeat=time.time()) if b.get("running") else None
            out.append(dict(kind="batch", type="batch", id=b["id"], dir=b["dir"], name=b["name"], recipe=b.get("recipe"),
                            client=b.get("client"), series=None, created=None, updated=time.time(), counts=counts,
                            status=st, thumb=None, deliveries=0, sources=["desk"], live=live, opened=True,
                            openable=True, real=b["dir"]))
        return out


class MockStrips(Strips):
    """「听一遍这条片子」 without whisper: the words of an .srt next to the file (or a placeholder sentence)."""

    def _words(self, f):
        time.sleep(float(os.environ.get("DESK_MOCK_ASR_STEP", "2")))
        cues = []
        d = os.path.dirname(f["path"])
        for cand in sorted([x for x in os.listdir(d) if x.endswith(".srt")], key=lambda x: (not x.startswith("zh"), x)):
            cues = parse_srt(open(os.path.join(d, cand), encoding="utf-8", errors="replace").read())
            if cues:
                break
        if not cues:
            dur = float(f.get("duration") or 6)
            cues = [(0.3, max(0.6, dur - 0.3), "这是 一段 模拟 的 转写 文字 用来 演示 时间轴 上 的 逐字稿")]
        out = []
        for a, b, text in cues:
            toks = tokens(text)
            if not toks or b <= a:
                continue
            step = (b - a) / len(toks)
            for i, tk in enumerate(toks):
                out.append(dict(w=tk, t=round(a + i * step, 3), te=round(a + (i + 1) * step - 0.02, 3)))
        return out


def create_fake():
    """tests/create_fake.py of this repo (fake video services + the fake AI)."""
    spec = importlib.util.spec_from_file_location("create_fake", os.path.join(REPO, "tests", "create_fake.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class MockCreateApi(CreateApi):
    """The same ``vstudio.create`` commands, in this process, against a private store (<DESK_DATA_DIR>/create-mock)
    with fake services and a fake AI: nothing leaves the machine, nothing is charged."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._mod = None

    def mock_home(self):
        return os.path.join(self.data_dir, "create-mock")

    def real(self):
        return False

    def engine(self):
        if self._mod is None:
            from vstudio.create import cli, store
            create_fake().install()
            store.configure(self.mock_home())
            self._mod = cli
        return self._mod

    def _dispatch(self, args, on_event=None):
        cli = self.engine()
        from vstudio.create.i18n import CreateError
        if args[:1] == ["handoff"] and "--no-register" not in args:
            args = args + ["--no-register"]          # her real projects.json is never written by a test
        a = cli.parser().parse_args(self._base() + args)
        try:
            return cli.dispatch(a, on_event=on_event) if on_event else cli.dispatch(a)
        except CreateError as e:
            raise Refused(e.code, e.params, e.status) from e

    def call(self, args, timeout=180):
        self.used = True
        return self._dispatch(args)

    def _run_job(self, args, on_event, limit=None):
        return self._dispatch(args, on_event)

    def roots(self):
        out = super().roots()
        if self.used and os.path.isdir(self.mock_home()):
            out.append(self.mock_home())
        return out

    def _after_handoff(self, res, schedule):
        if res.get("dir") and self.history is not None and hasattr(self.history, "extra_work"):
            self.history.extra_work.add(os.path.abspath(res["dir"]))
        return super()._after_handoff(res, schedule)


class MockAutopilot(Autopilot):
    """``vstudio.project decisions | reopen | autopilot`` for the simulated projects (``.vstudio/mock-autopilot.json``):
    taking a decision back adds it to the folder's PICKS.md "creator should confirm" list, which the Inbox asks."""

    def __init__(self, history, runner, bus=None, intake=None):
        super().__init__(history, runner, bus, intake)
        self.intake = intake

    def _mock(self, item):
        from .intake import MOCK_AP, mock_autopilot
        e = self.history.find(item)
        d = e.get("dir") or ""
        return e, d, mock_autopilot(d), os.path.join(d, ".vstudio", MOCK_AP)

    def get(self, item):
        from desk_engine import pilot
        _e, d, ap, _p = self._mock(item)
        base = dict(item=item, running=bool(pilot.running(d)), queued=pilot.queued(d))
        if not ap:
            return dict(base, supported=False, autopilot=None, decisions=[])
        asked = [dict(checkpoint=k.partition(":")[0], item=k.partition(":")[2], asked=True) for k in ap.get("ask") or []]
        return dict(base, supported=True, autopilot=dict(on=bool(ap.get("on")), spend_cap=0, judge=True,
                                                          ask=ap.get("ask") or []),
                    decisions=sorted(ap.get("decisions") or [], key=lambda x: str(x.get("at")), reverse=True) + asked)

    def reopen(self, item, checkpoint, sub="*"):
        _e, d, ap, path = self._mock(item)
        need(ap, "only a recipe project has decisions to take back")
        hit = [x for x in ap.get("decisions") or [] if x["checkpoint"] == checkpoint and x["item"] == sub]
        if not hit:
            raise BadRequest(f"{checkpoint} has no answer for {sub}")
        ap["decisions"] = [x for x in ap["decisions"] if x not in hit]
        ap["ask"] = sorted(set(ap.get("ask") or []) | {f"{checkpoint}:{sub}"})
        write_json(path, ap)
        with open(os.path.join(d, "PICKS.md"), "a", encoding="utf-8") as f:
            f.write(f"\n## Taken back from the autopilot (creator should confirm)\n- **{sub}** {checkpoint}: your call\n")
        if self.bus:
            self.bus.publish("batches")
            self.bus.publish("inbox")
        return dict(ok=True, checkpoint=checkpoint, item=sub, rerun={sub: [f"cp_{checkpoint}"]}, resumed=False)

    def mode(self, item, on):
        from desk_engine import pilot
        need(isinstance(on, bool), "on: true (autopilot) or false (ask me first)")
        e, d, ap, path = self._mock(item)
        need(e.get("kind") == "work", "only a recipe project can switch to autopilot")
        ap = dict(ap or dict(decisions=[], ask=[]), on=on)
        write_json(path, ap)
        resumed = False
        live = (e.get("live") or {}).get("state")
        if on and live == "waiting" and not pilot.running(d) and self.intake is not None:
            import json as _json
            rec = _json.load(open(os.path.join(d, ".vstudio", "work.json"), encoding="utf-8"))
            made = len([f for f in os.listdir(os.path.join(d, "final"))
                        if f.endswith(".mp4")]) if os.path.isdir(os.path.join(d, "final")) else 0
            proj = dict(name=rec.get("title"), items=dict(count=int(rec.get("count") or 3)))
            self.intake._queue_run(d, proj, autopilot=True, start_at=made)
            resumed = True
        if self.bus:
            self.bus.publish("batches")
            self.bus.publish("inbox")
        return dict(ok=True, autopilot=dict(on=on), resumed=resumed)
