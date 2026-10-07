"""Provider protocol for Create (SPEC §1.4).

    info      {id, label {en, zh, fr}, kind cloud|mcp|manual|local, needs [env or local:x], tos, license, models,
               concurrency}
    status()  {ready, code, params, balance?}   no network (``test()`` may do one cheap read-only call)
    estimate(job, rates) -> {cny, native_units, seconds_billed} via costs.price_job
    quote(job) -> provider-side price in CNY or None (no adapter exposes one yet; the fake can)
    submit(job) -> task id     PAID. Only jobs.run_finals calls it, after the spend gate. Never retried.
    poll(task_id) -> {status pending|done|failed, urls, raw}     retries OK
    download(url, path) -> path                                   retries OK
"""
import os

from ..i18n import CreateError


class SubmitTimeout(RuntimeError):
    """The request left this machine but no answer came back: it may have been charged (never resubmit)."""


class Provider:
    info = dict(id="base", label={"en": "base"}, kind="cloud", needs=[], tos="", license=None, models=[],
                concurrency=4)

    @property
    def id(self):
        return self.info["id"]

    def missing(self):
        return [n for n in self.info.get("needs") or [] if not n.startswith("local:") and not os.environ.get(n)]

    def status(self):
        miss = self.missing()
        if miss:
            return dict(ready=False, code="create.provider.missing-key", params=dict(keys=miss))
        return dict(ready=True, code="create.provider.ready", params={})

    def test(self):
        return self.status()

    def caps(self, model):
        return {}

    def balance(self):
        return None

    def quote(self, job):
        return None

    def submit(self, job):
        raise CreateError("manual-only", provider=self.id)

    def poll(self, task_id):
        return {"status": "pending", "urls": [], "raw": {}}

    def download(self, url, path):
        raise NotImplementedError
