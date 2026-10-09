"""The desk's test engine: an in-memory engine (fake batches, stage-by-stage runs), a rule planner with simulated
pilots, the desk's own v0.2 edits, .srt "transcription" and Create with fake services and a fake AI.

Tests only. The desk's e2e harness starts it with DESK_ENGINE_MOCK=1 in a dev build (engine/server.py loads this
package from engine/tests/fixtures); a packaged app never passes that variable and does not ship engine/tests.
The product code (engine/desk_engine) has no fake path of its own.
"""
from desk_engine.app import Api
from desk_engine.caps import Capabilities

from .engine import MockEngine
from .intake import MockIntake, record_pilot, rule_plan, rule_revise
from .parts import MockAutopilot, MockCreateApi, MockHistory, MockStrips
from .studio import MockStudio
from .transcript import fake_transcript

KINDS = dict(History=MockHistory, Intake=MockIntake, Strips=MockStrips, CreateApi=MockCreateApi,
             Autopilot=MockAutopilot)

__all__ = ["KINDS", "MockAutopilot", "MockCreateApi", "MockEngine", "MockHistory", "MockIntake", "MockStrips", "MockStudio", "make_api",
           "fake_transcript", "record_pilot", "rule_plan", "rule_revise"]


def make_api(engine, bus, token, origins):
    """The engine API over the test engine: the same routes, every part in its in-memory version."""
    studio = MockStudio(engine, engine.data_dir, bus, Capabilities(fixed=set()))
    return Api(engine, bus, token, origins, studio=studio, kinds=KINDS)
