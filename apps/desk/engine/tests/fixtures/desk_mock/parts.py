"""The test engine's other parts: history rows for the in-memory batches, clip transcription from an .srt next to the
file, and Create with fake video services and a fake AI in this process (tests/create_fake.py). Tests only.

  DESK_MOCK_ASR_STEP   seconds 「听一遍」 takes (default 2)
"""
import importlib.util
import os
import time

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
