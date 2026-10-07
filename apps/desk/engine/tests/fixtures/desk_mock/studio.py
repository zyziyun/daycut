"""The test engine's v0.2 adapter: the desk's own edit / re-run / segment planning against the in-memory engine
(no CLI), a demo client, and no persona. Tests only."""
import os
import time

from desk_engine import planning as P
from desk_engine.studio import DEFAULT_CLIENT, Studio
from desk_engine.v02store import dump_yaml, write_text

from .transcript import fake_transcript


class MockStudio(Studio):
    def __init__(self, engine, data_dir, bus, caps, runner=None):
        super().__init__(engine, data_dir, bus, caps, runner)
        self._seed()

    def can(self, what):
        return True                                  # the in-memory engine plans, edits and re-runs itself

    def capabilities(self):
        return dict(mode=self.e.mode, source="mock",
                    commands={c: False for c in ("plan-segments", "client", "job-edit", "job-rerun", "deliver",
                                                 "metrics", "timing")},
                    fallback=dict(plan=True, edit=True, rerun=True))

    def _persona_defaults(self):
        return dict(DEFAULT_CLIENT)

    def _seed(self):
        if self.list_clients():
            return
        self.create_client(dict(slug="demo", name="示例客户 · 知识讲师", style="干净、信息密度高、不花哨",
                                platforms=["xiaohongshu:full", "tiktok:vertical"], tags=["RAG", "面试", "AI"],
                                glossary=[dict(wrong="rag", right="RAG")], cleanup_profile="strict"))
        demo = next((b for b in self.e.list_batches() if b["name"] == "demo-course"), None)
        if demo:
            self.store.set_batch_meta(demo["id"], client="demo", created=time.time())
            self.set_crm("demo", dict(stage="pilot"))

    def _plan_segments(self, plan):
        b = plan["request"]
        dur = P.probe_duration(b["source"])
        for p in ("asr", "planning"):
            time.sleep(self.step * 2)
            self._plan_progress(plan, p)
        words = fake_transcript(dur)
        segs = P.rule_plan(words, count=b["count"], min_s=b["min"], max_s=b["max"])
        if b["provider"] != "none":
            for s in segs:
                s["why"] = f"[{b['provider']} mock] " + s["why"]
        draft = os.path.join(plan["dir"], "segments.draft.yaml")
        write_text(draft, dump_yaml(dict(source=b["source"], segments=segs)))
        return dict(source=b["source"], duration=round(dur, 2), provider=b["provider"], segments=segs,
                    words=[dict(w=w["w"], t=w["t"], te=w["te"]) for w in words], draft=draft)

    def _rerun(self, bid, jid, stages):
        return self.e.rerun_job(bid, jid, stages)
