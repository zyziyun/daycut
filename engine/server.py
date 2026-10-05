"""Entry point: ``python engine/server.py`` (spawned by the Electron main process).

Environment
  DESK_TOKEN            per-launch bearer token (required)
  DESK_ALLOWED_ORIGINS  comma list of UI origins allowed to call the API (CORS), e.g. app://desk
  DESK_DATA_DIR         desk data folder (registry, generated specs); default ~/.vstudio-desk
  VSTUDIO_ENGINE_PATH   the video-studio repo; its lib/ is put on sys.path (PYTHONPATH also works)
  DESK_ENGINE_MOCK=1    force the in-memory mock engine
  DESK_MOCK_STEP        seconds per mock stage (default 0.25)
Prints one line ``{"ready": true, "port": N, "mode": "real"|"mock"}`` on stdout, then serves until stdin closes
(the parent died) or SIGTERM.
"""
import json
import os
import signal
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from desk_engine.app import Api, serve  # noqa: E402
from desk_engine.common import EventBus, Registry  # noqa: E402


def make_engine(data_dir, bus):
    reg = Registry(data_dir)
    engine_path = os.environ.get("VSTUDIO_ENGINE_PATH")
    if engine_path and os.path.isdir(os.path.join(engine_path, "lib")):
        sys.path.insert(0, os.path.join(engine_path, "lib"))
    reason = None
    if os.environ.get("DESK_ENGINE_MOCK") != "1":
        try:
            from desk_engine.real import RealEngine
            return RealEngine(data_dir, reg, bus, engine_path=engine_path), None
        except ImportError as e:
            reason = f"vstudio not importable ({e}); using the mock engine"
    from desk_engine.mock import MockEngine
    return MockEngine(data_dir, reg, bus, step=float(os.environ.get("DESK_MOCK_STEP", "0.25"))), reason


def main():
    token = os.environ.get("DESK_TOKEN")
    if not token or len(token) < 32:
        print(json.dumps(dict(ready=False, error="DESK_TOKEN missing / too short")), flush=True)
        return 2
    data_dir = os.path.abspath(os.path.expanduser(os.environ.get("DESK_DATA_DIR") or "~/.vstudio-desk"))
    os.makedirs(data_dir, exist_ok=True)
    origins = [o.strip() for o in (os.environ.get("DESK_ALLOWED_ORIGINS") or "").split(",") if o.strip()]
    bus = EventBus()
    engine, note = make_engine(data_dir, bus)
    api = Api(engine, bus, token, origins)
    httpd = serve(api)
    print(json.dumps(dict(ready=True, port=api.port, mode=engine.mode, note=note)), flush=True)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *a: stop.set())
    signal.signal(signal.SIGINT, lambda *a: stop.set())

    def watch_stdin():                      # parent closed our stdin (crashed / quit) -> exit
        try:
            sys.stdin.read()
        except Exception:  # noqa: BLE001
            pass
        stop.set()
    threading.Thread(target=watch_stdin, daemon=True).start()
    stop.wait()
    engine.shutdown()
    httpd.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
