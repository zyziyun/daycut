"""The sidecar survives stray signals (0.2.3: "engine exited (SIGUSR1)" in main.log - Python's default for SIGUSR1 /
SIGUSR2 is to terminate). SIGUSR1 prints every thread's stack to stderr, SIGUSR2 is noted; only SIGTERM / SIGINT or
closing stdin stop the engine."""
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest

TOKEN = "t" * 40
SERVER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server.py")


@unittest.skipUnless(hasattr(signal, "SIGUSR1"), "POSIX signals")
class StraySignalTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="rfs-", dir="/tmp")
        env = dict(os.environ, DESK_TOKEN=TOKEN, DESK_ALLOWED_ORIGINS="app://desk", DESK_ENGINE_MOCK="1",
                   DESK_DATA_DIR=self.dir, DESK_SOCKET=os.path.join(self.dir, "e.sock"))
        self.p = subprocess.Popen([sys.executable, SERVER], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True)
        self.err = []
        threading.Thread(target=lambda: self.err.extend(iter(self.p.stderr.readline, "")), daemon=True).start()
        self.assertTrue(json.loads(self.p.stdout.readline())["ready"])

    def tearDown(self):
        if self.p.poll() is None:
            self.p.kill()
        self.p.wait(timeout=10)
        for f in (self.p.stdin, self.p.stdout, self.p.stderr):
            try:
                f.close()
            except OSError:
                pass
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)

    def wait_for(self, text, timeout=10.0):
        end = time.time() + timeout
        while time.time() < end:
            if any(text in line for line in self.err):
                return True
            time.sleep(0.05)
        return False

    def test_sigusr1_dumps_stacks_and_keeps_serving(self):
        os.kill(self.p.pid, signal.SIGUSR1)
        self.assertTrue(self.wait_for("most recent call first"), "".join(self.err))
        time.sleep(0.3)
        self.assertIsNone(self.p.poll(), "SIGUSR1 ended the engine")
        os.kill(self.p.pid, signal.SIGUSR1)                    # again: the handler stays installed
        time.sleep(0.3)
        self.assertIsNone(self.p.poll())

    def test_sigusr2_is_noted_not_fatal(self):
        os.kill(self.p.pid, signal.SIGUSR2)
        self.assertTrue(self.wait_for("ignored signal SIGUSR2"), "".join(self.err))
        self.assertIsNone(self.p.poll())

    def test_sigterm_still_stops_it_cleanly(self):
        os.kill(self.p.pid, signal.SIGUSR1)
        self.assertTrue(self.wait_for("most recent call first"))
        os.kill(self.p.pid, signal.SIGTERM)
        self.assertEqual(self.p.wait(timeout=15), 0)


if __name__ == "__main__":
    unittest.main()
