"""Small OS shims so the engine runs on Windows as well as macOS / Linux.

    from vstudio import oscompat
    with open("run.lock", "a") as f:
        if not oscompat.try_lock(f): ...          # another process holds it (oscompat.lock(f) waits instead)
        ...
        oscompat.unlock(f)
    oscompat.pid_alive(1234)                      # never sends a signal (os.kill(pid, 0) KILLS on Windows)
    oscompat.kill_tree(proc)                      # the child and everything it started

POSIX: ``fcntl.flock``, ``os.kill(pid, 0)``, ``os.killpg`` (the child must have been started with
``start_new_session=True``). Windows: ``msvcrt.locking`` on one byte far past the data (readers and writers of the
file are not blocked), ``OpenProcess`` + ``GetExitCodeProcess``, ``taskkill /T /F``.
"""
import os
import signal
import subprocess

WINDOWS = os.name == "nt"
_LOCK_AT = 1 << 30
CREATE_NO_WINDOW = 0x08000000


def _seek_raw(f, pos):
    os.lseek(f.fileno(), pos, os.SEEK_SET)


def try_lock(f):
    """Take an exclusive, non-blocking lock on the open file ``f``. -> True when taken, False when another
    process (or another open file in this process, on Windows) holds it."""
    if WINDOWS:
        import msvcrt
        f.flush()
        here = os.lseek(f.fileno(), 0, os.SEEK_CUR)
        try:
            _seek_raw(f, _LOCK_AT)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
        finally:
            _seek_raw(f, here)
    import fcntl
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def lock(f, poll=0.05):
    """Take an exclusive lock on the open file ``f``, waiting for it as long as it takes."""
    if WINDOWS:
        import time
        while not try_lock(f):
            time.sleep(poll)
        return
    import fcntl
    fcntl.flock(f, fcntl.LOCK_EX)


def unlock(f):
    """Release a lock taken with ``try_lock`` (closing the file releases it too)."""
    try:
        if WINDOWS:
            import msvcrt
            f.flush()
            here = os.lseek(f.fileno(), 0, os.SEEK_CUR)
            try:
                _seek_raw(f, _LOCK_AT)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            finally:
                _seek_raw(f, here)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_UN)
    except (OSError, ValueError):
        pass


def pid_alive(pid):
    """True while process ``pid`` exists (any owner). Never signals it."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if WINDOWS:
        import ctypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        h = k.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ctypes.get_last_error() == 5          # access denied: exists, another user's
        try:
            code = ctypes.c_ulong()
            return bool(k.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259   # STILL_ACTIVE
        finally:
            k.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def kill_tree(proc, sig=signal.SIGTERM):
    """End ``proc`` (a Popen or a pid) and the processes it started. POSIX: ``sig`` to its process group (start it
    with ``start_new_session=True``; falls back to the process alone). Windows: ``taskkill /T /F`` (there is no
    graceful signal for a console child), falling back to TerminateProcess. -> True when something was signalled."""
    pid = getattr(proc, "pid", proc)
    if hasattr(proc, "poll") and proc.poll() is not None:
        return False
    if WINDOWS:
        try:
            r = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                               creationflags=CREATE_NO_WINDOW, timeout=15)
            if r.returncode == 0:
                return True
        except (OSError, subprocess.SubprocessError):
            pass
        try:
            if hasattr(proc, "kill"):
                proc.kill()
            else:
                os.kill(int(pid), signal.SIGTERM)          # TerminateProcess
            return True
        except OSError:
            return False
    try:
        os.killpg(int(pid), sig)
        return True
    except OSError:
        try:
            os.kill(int(pid), sig)
            return True
        except OSError:
            return False


def relpath(path, start=os.curdir):
    """``os.path.relpath`` with ``/`` separators on every OS (relative paths stored in JSON / YAML / manifests and
    used as ids stay the same on Windows; Windows APIs accept ``/``) that never raises for another drive (Windows
    ``C:\\x`` vs ``D:\\y``: the absolute path, as is)."""
    try:
        rel = os.path.relpath(path, start)
    except ValueError:
        return os.path.abspath(path)
    return rel.replace(os.sep, "/") if os.sep != "/" else rel
