"""Every user-facing engine message is a code + params; the desk renders ``t('create.<code>', params)``.

    msg("route.character-split", cast="A", shots=["03", "07"]) -> {"code": "create.route.character-split", ...}
"""

CODES = (
    # errors / refusals (jobs.run, costs.check)
    "create.confirm-required", "create.confirm-mismatch", "create.confirm-expired", "create.confirm-used",
    "create.plan-changed",
    "create.over-budget", "create.over-cap", "create.unknown-rate", "create.low-credits", "create.price-changed",
    "create.provider-not-ready", "create.max-too-low", "create.nothing-to-make", "create.not-found",
    "create.bad-input", "create.manual-only", "create.local-off", "create.ai-failed",
    # progress / inbox
    "create.pick-takes", "create.budget", "create.hard-shots-failed", "create.recording-recovered",
    "create.manual-waiting", "create.unknown-charge", "create.shot-failed", "create.done",
    # routing
    "create.route.character-split", "create.route.no-service", "create.route.override", "create.route.faces",
    "create.route.no-faces", "create.route.card", "create.route.record", "create.route.reuse",
    # ladder
    "create.stage.stills", "create.stage.animatic", "create.stage.drafts", "create.stage.finals",
    "create.stage.assemble",
)


def msg(code, **params):
    code = code if code.startswith("create.") else f"create.{code}"
    return {"code": code, "params": params}


class CreateError(RuntimeError):
    """A refusal or a user-facing failure: ``code`` (one of CODES) + ``params``; ``status`` = HTTP-ish status."""

    def __init__(self, code, status=400, **params):
        self.code = code if code.startswith("create.") else f"create.{code}"
        self.params = params
        self.status = status
        super().__init__(f"{self.code} {params}" if params else self.code)

    def doc(self):
        return {"error": {"code": self.code, "params": self.params}}
