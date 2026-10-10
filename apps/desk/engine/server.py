"""Entry point: ``python engine/server.py`` (spawned by the Electron main process).

Environment
  DESK_TOKEN            per-launch bearer token (required)
  DESK_ALLOWED_ORIGINS  comma list of UI origins allowed to call the API (CORS), e.g. app://desk
  DESK_DATA_DIR         desk data folder (registry, generated specs); default ~/.vstudio-desk
  VSTUDIO_ENGINE_PATH   the video-studio repo; its lib/ is put on sys.path (PYTHONPATH also works)
  DESK_SOCKET           the Unix domain socket to listen on (macOS / Linux; the desk puts it in the app's own temp
                        folder). Unset (Windows: CPython has no AF_UNIX there): 127.0.0.1 on a random free port
  DESK_ENGINE_MOCK=1    tests only: the in-memory test engine from engine/tests/fixtures/desk_mock (the desk's test
                        harness sets it in a dev build; a packaged app neither passes it nor ships engine/tests, so
                        there it fails the start instead)
  ANTHROPIC_API_KEY / OPENAI_API_KEY   segment-planning providers (from the OS keychain via the desk)
Prints one line ``{"ready": true, "socket": "<path>" | "port": N, "mode": "real"|"mock"}`` on stdout, then serves until
stdin closes (the parent died) or SIGTERM / SIGINT. SIGUSR1 prints every thread's stack to stderr and SIGUSR2 is
noted there; neither stops the engine (keep_running_on_stray_signals).
"""
import importlib
import json
import os
import signal
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from desk_engine.app import Api, serve  # noqa: E402
from desk_engine.caps import Capabilities, CliRunner, runner_env  # noqa: E402
from desk_engine.common import EventBus, Registry  # noqa: E402
from desk_engine.studio import Studio  # noqa: E402


HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "tests", "fixtures")


def test_engine():
    """The test engine package (engine/tests/fixtures/desk_mock): fake batches, rule plans, simulated pilots and fake
    Create services for the desk's own tests. Never part of a packaged app."""
    if not os.path.isfile(os.path.join(FIXTURES, "desk_mock", "__init__.py")):
        raise ImportError("DESK_ENGINE_MOCK is set, but the test engine is not part of this build")
    if FIXTURES not in sys.path:
        sys.path.insert(0, FIXTURES)
    import desk_mock
    return desk_mock


def make_engine(data_dir, bus):
    reg = Registry(data_dir)
    engine_path = os.environ.get("VSTUDIO_ENGINE_PATH")
    if engine_path and os.path.isdir(os.path.join(engine_path, "lib")):
        sys.path.insert(0, os.path.join(engine_path, "lib"))
    if os.environ.get("DESK_ENGINE_MOCK") == "1":     # tests only: the desk passes it for a test profile, never else
        return test_engine().MockEngine(data_dir, reg, bus, step=float(os.environ.get("DESK_MOCK_STEP", "0.25"))), None
    # no silent fallback to a fake engine: a broken / missing engine fails the start and the app says why
    from desk_engine.real import RealEngine
    return RealEngine(data_dir, reg, bus, engine_path=engine_path), None


# The test engine runs Create jobs in this process (desk_mock: no subprocess), so the recorder's stitch imports the
# local ASR here, on a job thread: its native libraries too, when installed.
TEST_ENGINE_NATIVE = ("faster_whisper", "onnxruntime")      # + CTranslate2, PyAV (not cv2 too: two FFmpeg builds on a Mac)


def preload(test_engine=False):
    """Import what opening a clip and the inbox poll use in this process, in the main thread BEFORE any other thread
    starts. Windows: loading numpy's DLLs (OpenBLAS starts its thread pool under the DLL loader lock) in a background
    thread while other threads are being created (request threads, subprocess pipe readers) deadlocks the whole
    process - it stays alive, prints "ready" and never answers a request. ~0.2 s on a Mac. The test engine too: its
    routes (share, the transcript's preview) import the same modules lazily, and its Create jobs more."""
    for mod in ("numpy",) + (TEST_ENGINE_NATIVE if test_engine else ()):
        try:                                # named: the DLLs that deadlock, whatever vstudio imports below
            importlib.import_module(mod)
        except Exception:  # noqa: BLE001  (not installed / broken: whatever uses it reports that)
            pass
    try:
        import vstudio.project.inbox  # noqa: F401
        import vstudio.project.outputs  # noqa: F401
    except Exception as e:  # noqa: BLE001  (the calls themselves report a broken engine)
        print(f"[engine] preload: {e}", file=sys.stderr, flush=True)


def warm(api):
    """Off the start-up path: probe the engine's output commands once, so the first editor open does not pay."""
    try:
        api.outputs.real()
    except Exception as e:  # noqa: BLE001  (the calls themselves report a broken engine)
        print(f"[engine] warm-up: {e}", file=sys.stderr, flush=True)


def _noted(signum, _frame):
    msg = f"[engine] ignored signal {signal.Signals(signum).name}: only SIGTERM / SIGINT or closing stdin stop the engine\n"
    try:
        os.write(2, msg.encode())           # not print(): a handler may run while the main thread writes stderr
    except OSError:
        pass


def keep_running_on_stray_signals():
    """SIGUSR1 / SIGUSR2 end a Python process by default. Nothing in the desk sends them, but another process may: a
    stack-dump attempt (``kill -USR1 <pid>`` is the usual "print your threads" request for Python / Node services)
    ended a running engine in 0.2.3 (main.log: "engine exited (SIGUSR1)"). SIGUSR1 now does what the sender wanted -
    faulthandler prints every thread's stack to stderr (the desk keeps it in the engine log; it works even while a
    thread holds the GIL) - and SIGUSR2 is noted; the engine keeps serving. A handler, not SIG_IGN: an ignored signal
    would stay ignored in every ffmpeg / CLI child the engine starts. Windows has neither signal."""
    if not hasattr(signal, "SIGUSR1"):
        return
    import faulthandler
    try:
        faulthandler.register(signal.SIGUSR1, file=sys.stderr, all_threads=True, chain=False)
    except (AttributeError, RuntimeError, ValueError, OSError):    # no usable stderr: at least do not die
        signal.signal(signal.SIGUSR1, _noted)
    signal.signal(signal.SIGUSR2, _noted)


def main():
    keep_running_on_stray_signals()         # first: a stray signal during start-up must not end it either
    token = os.environ.get("DESK_TOKEN")
    if not token or len(token) < 32:
        print(json.dumps(dict(ready=False, error="DESK_TOKEN missing / too short")), flush=True)
        return 2
    data_dir = os.path.abspath(os.path.expanduser(os.environ.get("DESK_DATA_DIR") or "~/.vstudio-desk"))
    os.makedirs(data_dir, exist_ok=True)
    origins = [o.strip() for o in (os.environ.get("DESK_ALLOWED_ORIGINS") or "").split(",") if o.strip()]
    bus = EventBus()
    try:
        engine, note = make_engine(data_dir, bus)
    except ImportError as e:
        print(json.dumps(dict(ready=False, error=f"the video engine (vstudio) cannot be loaded: {e}")), flush=True)
        return 3
    preload(test_engine=engine.mode != "real")                       # before any thread (see preload)
    if engine.mode == "real":
        runner = CliRunner(engine.python, runner_env(engine.engine_path))
        caps = Capabilities(runner)
        threading.Thread(target=caps.probe, daemon=True).start()      # warm the cache off the start-up path
        api = Api(engine, bus, token, origins, studio=Studio(engine, data_dir, bus, caps, runner))
        threading.Thread(target=warm, args=(api,), daemon=True).start()
    else:
        api = test_engine().make_api(engine, bus, token, origins)
    sock = os.environ.get("DESK_SOCKET") or None
    try:
        httpd = serve(api, socket_path=sock)
    except OSError as e:
        print(json.dumps(dict(ready=False, error=f"cannot listen on {sock or '127.0.0.1'}: {e}")), flush=True)
        return 4
    where = dict(socket=sock) if sock else dict(port=api.port)
    print(json.dumps(dict(ready=True, mode=engine.mode, note=note, **where)), flush=True)
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
    httpd.server_close()                    # a Unix socket file is removed here
    return 0


if __name__ == "__main__":
    sys.exit(main())
