"""Make the plugin / agent shots of an episode: one job folder per shot (jobfolder.py), N parallel lanes per runner.

    make(eid, only=None, lanes=None, on_event=None) -> summary

* which shots: those routed to ``plugin:<render provider>`` or ``agent:<runner>`` (routing.py);
* concurrency per runner = min(manifest ``concurrency``, the user's ``lanes`` setting / argument, Fleet's
  ``agent:<id>`` resource class) - lanes of different runners run side by side;
* resume: a job already done whose outputs still pass QC is skipped; failed / stopped / waiting ones run again;
  a STOP file in the episode's work dir stops every lane (``create stop EID``);
* each agent process: cwd = its job folder, stdin = brief.md (command runners), stdout + stderr -> log.txt, its own
  process group (a stop / timeout kills the CLI and what it started), heartbeat in status.json every second,
  ``timeout_s`` from the manifest (default 30 min);
* QC gate: outputs/ must hold a playable video or an image, else the shot is ``failed`` (create.agent.qc-no-output);
* results: every output becomes a take of the shot (one take -> picked at once, several -> "pick takes" in the
  Inbox), failures / waiting shots are in the episode's ``make`` record -> the Making view + Inbox;
* money: a plugin whose manifest says ``cost.kind: paid`` is refused here (create.plugin.paid-needs-gate) - paid
  generation only runs through the finals estimate + confirm code.
"""
import os
import signal
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import jobfolder as JF, registry as R

HEARTBEAT_S = 1.0


def _emit(on_event, **ev):
    if on_event:
        try:
            on_event(dict(event="create.progress", stage="make", ts=time.time(), **ev))
        except Exception:  # noqa: BLE001
            pass


def _limits():
    try:
        from vstudio.batch.run import default_limits, limit_for
        lim = default_limits()
        return lambda res: limit_for(lim, res)
    except Exception:  # noqa: BLE001
        return lambda res: 2


def plan(ep, s, fmt):
    """[(shot, route)] of the shots made by plugins / agents."""
    from vstudio.create import providers as PR, routing
    routes, _ = routing.resolve(ep, s, fmt, PR.connected())
    by = {r["no"]: r for r in routes}
    return [(sh, by[sh["no"]]) for sh in ep.get("shots") or [] if by.get(sh["no"], {}).get("kind")
            in routing.MADE_BY_PLUGINS]


def runner_for(route):
    """-> (registry row, object). agent: an AgentRunner; plugin: a render-kind shot provider instance."""
    if route["kind"] == "agent":
        row = R.find(route["provider"], "agent-runner")
        return row, R.instance(row["key"])
    row = R.find(route["provider"], "shot-provider")
    cls = R.instance(row["key"])
    if (getattr(cls, "info", {}) or {}).get("kind") != "render":
        raise R.PluginError("plugin.not-ready", name=row["id"], detail="not a render provider (use cloud:<id>)")
    return row, cls()


class Maker:
    def __init__(self, eid, on_event=None):
        from vstudio.create import jobs, store
        self.eid, self.on_event, self.store, self.jobs = eid, on_event, store, jobs
        self.lk = jobs.lock(eid)
        self.ep = store.load_episode(eid)

    def save(self):
        with self.lk:
            self.store.save_episode(self.ep)

    def set_unit(self, no, **f):
        with self.lk:
            self.ep.setdefault("make", {}).setdefault("units", {}).setdefault(no, {}).update(f)
            self.store.save_episode(self.ep)
        _emit(self.on_event, episode=self.eid, shot=no, **{k: v for k, v in f.items() if k in ("state", "code")})

    def stopped(self):
        return os.path.exists(os.path.join(self.store.work_dir(self.ep), "STOP"))

    def add_takes(self, no, files, runner):
        """Copy the outputs into the episode's takes folder (u<no>_v<n>.ext, like every other take)."""
        import glob
        import shutil
        from vstudio.create import store
        with self.lk:
            lst = self.ep.setdefault("takes", {}).setdefault(no, [])
            d = os.path.join(store.work_dir(self.ep), "takes")
            os.makedirs(d, exist_ok=True)
            for f in files:
                n = len(glob.glob(os.path.join(d, f"u{no}_v*.*"))) + 1
                dst = os.path.join(d, f"u{no}_v{n}{os.path.splitext(f)[1].lower() or '.mp4'}")
                shutil.copy2(f, dst)
                lst.append(dict(file=dst, unit=f"u{no}", provider=runner, model=None, task=None, at=store.stamp()))
            if len(lst) == 1:
                self.ep.setdefault("picks", {})[no] = lst[0]["file"]
            store.save_episode(self.ep)

    # ------------------------------------------------------------ one job
    def run_agent(self, job, row, runner):
        d = job["dir"]
        cmd = runner.command(job)
        env = dict(runner.env(job) or os.environ)
        env.update(REELFOLD_JOB_DIR=d, REELFOLD_OUTPUTS=os.path.join(d, "outputs"),
                   REELFOLD_STATUS=os.path.join(d, "status.json"), REELFOLD_SHOT=job["shot"])
        limit = float(R.settings_of(row["key"]).get("timeout_s") or row["timeout_s"] or 1800)
        stdin = open(os.path.join(d, "brief.md"), "rb") if getattr(runner, "stdin_brief", True) else subprocess.DEVNULL
        t0 = time.time()
        with open(os.path.join(d, "log.txt"), "ab") as log:
            try:
                p = subprocess.Popen(cmd, cwd=d, stdin=stdin, stdout=log, stderr=subprocess.STDOUT, env=env,
                                     start_new_session=True)
            except OSError as e:
                return "failed", "create.agent.failed", str(e)[:200]
            finally:
                if stdin is not subprocess.DEVNULL:
                    stdin.close()
            own = dict(state="running", pid=p.pid, started=t0, runner=row["id"])    # re-asserted: the agent may
            JF.set_status(d, heartbeat=t0, **own)                                  # rewrite status.json whole
            why = None
            while p.poll() is None:
                time.sleep(HEARTBEAT_S)
                JF.set_status(d, heartbeat=time.time(), **own)
                st = JF.status(d)
                if st.get("progress") is not None or st.get("message"):
                    self.set_unit(job["shot"], progress=st.get("progress"), message=str(st.get("message") or "")[:200])
                if self.stopped():
                    why = "stopped"
                elif time.time() - t0 > limit:
                    why = "timeout"
                if why:
                    try:
                        os.killpg(p.pid, signal.SIGKILL)
                    except OSError:
                        p.kill()
                    p.wait()
                    break
        JF.set_status(d, exit_code=p.returncode, finished=time.time(), **dict(own, pid=None))
        if why == "stopped":
            return "stopped", None, None
        if why == "timeout":
            return "failed", "create.agent.timeout", f"over {int(limit)} s"
        if p.returncode:
            return "failed", "create.agent.failed", self._tail(d) or f"exit {p.returncode}"
        return "ok", None, None

    @staticmethod
    def _tail(d):
        try:
            with open(os.path.join(d, "log.txt"), "rb") as f:
                f.seek(max(0, os.path.getsize(f.name) - 400))
                return f.read().decode("utf-8", "replace").strip().splitlines()[-1][:200]
        except (OSError, IndexError):
            return ""

    def run_render(self, job, row, prov):
        from .builtin.hyperframes import ExternalNeeded
        JF.set_status(job["dir"], state="running", started=time.time(), heartbeat=time.time(), runner=row["id"])
        try:
            prov.render(job)
        except ExternalNeeded as e:
            return "manual-waiting", "create.plugin.external", str(e)[:200]
        except Exception as e:  # noqa: BLE001
            return "failed", "create.agent.failed", str(e)[:200]
        return "ok", None, None

    def one(self, shot, route, row, obj, bible, aspect):
        from vstudio.create import store
        no = shot["no"]
        name = R.display_name(row)
        d = os.path.join(store.work_dir(self.ep), "jobs", no)
        if self.stopped():
            self.set_unit(no, state="stopped")
            return "stopped"
        note = ("Render the HyperFrames composition named in inputs/ref.json." if route["kind"] == "plugin" else "")
        job = JF.prepare(d, self.ep, shot, bible, row["id"], route["kind"], aspect=aspect,
                         deadline_s=row["timeout_s"], provider_note=note, fresh=True)
        self.set_unit(no, state="running", runner=row["id"], kind=route["kind"], name=name, dir=d, started=time.time(),
                      code=None, params={})
        res, code, err = (self.run_agent(job, row, obj) if route["kind"] == "agent" else self.run_render(job, row, obj))
        if res == "ok":
            ok, files, code = JF.qc(d)
            if ok:
                self.add_takes(no, files, f"{route['kind']}:{row['id']}")
                JF.set_status(d, state="done", progress=1, code=None)
                self.set_unit(no, state="done", n_takes=len(files), finished=time.time())
                return "done"
            res, err = "failed", ""
        JF.set_status(d, state=res, code=code, error=err)
        params = dict(runner=name, shot=no, error=err or "", name=name)
        self.set_unit(no, state=res, code=code, params=params, finished=time.time())
        return res


def make(eid, only=None, lanes=None, on_event=None):
    from vstudio.create import jobs, store
    from vstudio.create.i18n import CreateError
    store.need_eid(eid)
    ep, s, fmt, bible = jobs.context(eid)
    todo = plan(ep, s, fmt)
    if only:
        keep = set(only)
        todo = [(sh, r) for sh, r in todo if sh["no"] in keep]
    if not todo:
        raise CreateError("make.nothing", status=409)
    M = Maker(eid, on_event)
    try:
        os.remove(os.path.join(store.work_dir(M.ep), "STOP"))
    except OSError:
        pass
    aspect = bible.get("aspect") or "9:16"
    limit = _limits()
    groups, skipped = {}, []
    prev = (M.ep.get("make") or {}).get("units") or {}
    M.ep["make"] = dict(id=f"m{int(time.time())}", state="running", started=store.stamp(), units={}, lanes={})
    for sh, r in todo:
        no = sh["no"]
        old = prev.get(no) or {}
        if old.get("state") == "done" and old.get("runner") == r["provider"] and (M.ep.get("takes") or {}).get(no):
            M.ep["make"]["units"][no] = dict(old)                           # resume: already made by this runner
            continue
        try:
            row, obj = runner_for(r)
            if row["cost"].get("kind") == "paid":
                raise R.PluginError("plugin.paid-needs-gate", name=R.display_name(row))
            st = obj.status() if hasattr(obj, "status") else dict(ready=True)
            if not st.get("ready"):
                raise R.PluginError("plugin.not-ready", name=R.display_name(row),
                                    detail=(st.get("params") or {}).get("detail") or st.get("code"))
        except R.PluginError as e:
            M.ep["make"]["units"][no] = dict(state="failed", runner=r["provider"], kind=r["kind"], code=e.code,
                                             params=e.params)
            skipped.append(no)
            continue
        M.ep["make"]["units"][no] = dict(state="queued", runner=row["id"], kind=r["kind"], name=R.display_name(row))
        groups.setdefault(row["key"], (row, obj, []))[2].append(sh)
    for k, (row, obj, shots) in groups.items():
        want = lanes or R.settings_of(k).get("lanes") or row["concurrency"]
        M.ep["make"]["lanes"][row["id"]] = max(1, min(int(want), 8, int(limit(f"agent:{row['id']}"))))
    M.save()
    route_of = {sh["no"]: r for sh, r in todo}
    _emit(on_event, episode=eid, state="running", total=sum(len(g[2]) for g in groups.values()),
          lanes=M.ep["make"]["lanes"])

    def lane(row, obj, shots):
        n = M.ep["make"]["lanes"][row["id"]]
        with ThreadPoolExecutor(max_workers=n, thread_name_prefix=f"lane-{row['id']}") as ex:
            list(ex.map(lambda sh: M.one(sh, route_of[sh["no"]], row, obj, bible, aspect), shots))

    threads = [threading.Thread(target=lane, args=g, daemon=True) for g in groups.values()]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    with M.lk:
        units = M.ep["make"]["units"]
        M.ep["make"]["state"] = "stopped" if M.stopped() else "done"
        M.ep["make"]["finished"] = store.stamp()
        M.ep["make"]["done"] = sum(1 for u in units.values() if u.get("state") == "done")
        M.ep["make"]["failed"] = sum(1 for u in units.values() if u.get("state") == "failed")
        M.ep["make"]["waiting"] = sum(1 for u in units.values() if u.get("state") == "manual-waiting")
        store.save_episode(M.ep)
    _emit(on_event, episode=eid, state=M.ep["make"]["state"], done=M.ep["make"]["done"], total=len(todo))
    out = {k: v for k, v in M.ep["make"].items()}
    out.update(ok=True, episode=eid, skipped=skipped)
    return out
