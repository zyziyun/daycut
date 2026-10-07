"""Planners: where the job list comes from.

``file`` (default): a human or a Claude Code agent writes the job list (segments.yaml / .csv / inline ``jobs``)
  after reading the transcript; ``plan`` just expands it. Rejected jobs (``review --apply``) come back as
  ``needs-replan`` with the reviewer's reason in ``status``; edit their rows and re-run ``plan``.

``claude`` (stub, optional): asks Claude to propose segments from the transcript. Needs the ``anthropic``
  package and ANTHROPIC_API_KEY; nothing here runs without them (and tests never touch the network).
  Pilot / interactive planning uses the regular Messages API (``--sync``); full-batch planning goes through
  the Message Batches API (50% price, results can take up to 24 h): ``plan --planner claude`` submits and
  stores the batch id, a later ``plan --planner claude`` polls and, when ended, writes
  ``segments.claude.yaml`` next to the spec for a human to check before it is planned like a file.
"""
import json
import os
import re

from . import spec as S
from .util import parse_time

MODEL = "claude-opus-5-5"
CHUNK_S = 900.0            # transcript seconds per planning request


class PlannerUnavailable(RuntimeError):
    pass


class FilePlanner:
    name = "file"

    def rows(self, spec):
        rows = []
        if spec.get("segments"):
            rows += S.read_rows(spec["segments"], spec["_dir"])
        if spec.get("jobs"):
            rows += S.read_rows(spec["jobs"], spec["_dir"])
        return rows


# --------------------------------------------------------------------------- claude (stub)
SYSTEM = (
    "You cut long recordings into short vertical clips for social platforms. From the timestamped transcript, "
    "propose self-contained segments of {min_s}-{max_s} seconds that make sense without the rest of the video: "
    "one clear point each, starting at the start of a sentence and ending after a complete thought. For each give "
    "a title (at most {title_max} characters, in the transcript's language), an optional cold-open hook range "
    "inside the segment (2-8 s, the most striking line) and one-sentence post body. Reply with JSON only: "
    '{{"segments": [{{"range": [t0, t1], "title": "...", "hook": {{"src": [t0, t1], "lines": ["..."]}}, '
    '"body": "..."}}]}}')


def _transcript_words(path):
    from vstudio import cleanup
    with open(path, encoding="utf-8") as f:
        return cleanup.load_words(json.load(f))


def transcript_chunks(words, chunk_s=CHUNK_S):
    """[(t0, t1, text with [mm:ss] marks every sentence)] chunks of ~chunk_s seconds."""
    chunks, cur, t0 = [], [], None
    for w in words:
        if t0 is None:
            t0 = w["t"]
        if w["t"] - t0 > chunk_s and cur:
            chunks.append((t0, cur[-1]["te"], cur))
            cur, t0 = [], w["t"]
        cur.append(w)
    if cur:
        chunks.append((t0, cur[-1]["te"], cur))
    out = []
    for a, b, ws in chunks:
        txt, last = [], -99.0
        for w in ws:
            if w["t"] - last > 8.0:
                txt.append(f"\n[{w['t']:.1f}] ")
                last = w["t"]
            txt.append(w["w"] if re.match(r"[\u3400-\u9fff]", w["w"][:1] or "") else " " + w["w"])
        out.append((a, b, "".join(txt).strip()))
    return out


def build_requests(spec, words, model=MODEL, min_s=30, max_s=90, title_max=20):
    """Message Batches request dicts (custom_id + params), one per transcript chunk. Pure (no network)."""
    pl = spec.get("planner_opts") or {}
    min_s, max_s = pl.get("min_s", min_s), pl.get("max_s", max_s)
    system = SYSTEM.format(min_s=min_s, max_s=max_s, title_max=pl.get("title_max", title_max))
    reqs = []
    for k, (a, b, text) in enumerate(transcript_chunks(words, pl.get("chunk_s", CHUNK_S))):
        reqs.append(dict(custom_id=f"chunk-{k:03d}", params=dict(
            model=pl.get("model", model), max_tokens=16000,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            output_config={"effort": pl.get("effort", "medium")},
            messages=[{"role": "user", "content": f"Transcript {a:.1f}-{b:.1f} s:\n{text}"}])))
    return reqs


def parse_reply(text):
    """Claude's JSON reply -> rows (tolerates prose / code fences around the JSON)."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return []
    rows = []
    for s in data.get("segments") or []:
        try:
            r = dict(range=[parse_time(s["range"][0]), parse_time(s["range"][1])], title=s.get("title", ""))
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        if s.get("hook"):
            r["hook"] = s["hook"]
        if s.get("body"):
            r["body"] = s["body"]
        rows.append(r)
    return rows


class ClaudePlanner:
    name = "claude"

    def __init__(self, store=None, sync=False):
        self.store, self.sync = store, sync

    @staticmethod
    def available():
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return False
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return True

    def rows(self, spec):
        from vstudio import llm
        routed = self.sync and llm.route("planner").provider not in ("none", "anthropic")
        if not routed and not self.available():
            raise PlannerUnavailable(
                "claude planner needs `pip install anthropic` and ANTHROPIC_API_KEY. Without them write the job list "
                "yourself (or let a Claude Code agent write segments.yaml from the transcript) and use --planner file.")
        tr = (spec.get("inputs") or {}).get("transcript")
        if not tr or not os.path.exists(tr):
            raise PlannerUnavailable("claude planner needs inputs.transcript (run the asr once, e.g. a 1-job pilot, "
                                     "or longform-to-short transcribe.py) to read the recording")
        reqs = build_requests(spec, _transcript_words(tr))
        out_path = os.path.join(spec["_dir"], "segments.claude.yaml")
        if self.sync:                                     # pilot / interactive: regular API
            rows = []
            for r in reqs:                                # same request through vstudio.llm (system prompt cached)
                pr = r["params"]
                # the "planner" route (claude-code -> codex ...) with its fallback chain when one is configured;
                # else the Anthropic API (a route to anthropic keeps its chain too: same provider = not pinned)
                res = llm.complete("planner", pr["system"][0]["text"], pr["messages"][0]["content"], schema=True,
                                   provider=None if routed else "anthropic", model=None if routed else pr["model"],
                                   max_tokens=pr["max_tokens"], effort=(pr.get("output_config") or {}).get("effort"),
                                   cache=True, repair=False)
                rows += parse_reply(res["text"])
            return self._write(out_path, rows)
        import anthropic                                  # Message Batches: an Anthropic-only API (50 % price)
        client = anthropic.Anthropic()
        bid = self.store.meta("planner_batch_id") if self.store else None
        if not bid:
            from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
            from anthropic.types.messages.batch_create_params import Request
            b = client.messages.batches.create(requests=[
                Request(custom_id=r["custom_id"], params=MessageCreateParamsNonStreaming(**r["params"])) for r in reqs])
            if self.store:
                self.store.set_meta("planner_batch_id", b.id)
            raise PlannerUnavailable(f"submitted Message Batch {b.id} ({len(reqs)} requests, up to 24 h); "
                                     "re-run `plan --planner claude` later to collect the segments")
        b = client.messages.batches.retrieve(bid)
        if b.processing_status != "ended":
            raise PlannerUnavailable(f"Message Batch {bid} still {b.processing_status}; try again later")
        rows = []
        for res in client.messages.batches.results(bid):        # any order: keyed by custom_id
            if res.result.type == "succeeded":
                rows += parse_reply("".join(x.text for x in res.result.message.content if x.type == "text"))
        if self.store:
            self.store.set_meta("planner_batch_id", None)
        return self._write(out_path, rows)

    @staticmethod
    def _write(path, rows):
        import yaml
        rows = sorted(rows, key=lambda r: r["range"][0])
        for i, r in enumerate(rows):
            r.setdefault("id", f"c{i + 1:03d}")
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump({"segments": rows}, f, allow_unicode=True, sort_keys=False)
        raise PlannerUnavailable(f"wrote {len(rows)} proposed segments to {path}: check them, then "
                                 f"`plan <spec> --planner file --segments {os.path.basename(path)}`")


def get(name, store=None, sync=False):
    if name in (None, "file"):
        return FilePlanner()
    if name == "claude":
        return ClaudePlanner(store, sync)
    raise ValueError(f"unknown planner {name!r} (file | claude)")
