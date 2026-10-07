"""Login status of every LLM provider, and the exact commands to log in / out. The engine never handles credentials:
it reads what the CLIs report, whether a key variable is present (never its value), and whether local servers answer.

    python -m vstudio.llm auth status [--provider P ...] [--json] [--no-probe] [--deep] [--refresh] [--timeout S]
    python -m vstudio.llm auth login  --provider claude-code|codex [--json] [--variant device]
    python -m vstudio.llm auth logout --provider claude-code|codex [--json]

``status`` rows: {provider, kind (subscription-cli | api | local), state, ready, installed, version, account
{email, plan, auth_method, org}, key_env, base_url, models, probe, can_login, can_logout, message {code, params,
message, message_zh}}. States: logged-in | expired | not-logged-in | not-installed | configured | not-configured |
server-down | no-models | ready | error.

claude-code: ``claude auth status --json`` (loggedIn, authMethod, subscriptionType, email) and, unless --no-probe, a
real tiny ``claude -p`` round-trip on the cheapest model, because the status command says "loggedIn" even when the
OAuth token has expired (the probe then answers 401). codex: ``codex login status`` (--deep adds a tiny ``codex
exec``). Every CLI runs with ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / ANTHROPIC_BASE_URL (claude) or OPENAI_* /
CODEX_API_KEY (codex) removed from its environment, so the user's own subscription login is what is checked.

Cache: every CLI probe result is kept in ``$VSTUDIO_AUTH_CACHE`` (default ``$VSTUDIO_HOME/auth-cache.json``) with a
fingerprint of the login (CLI path + mtime, the ``auth status`` / ``login status`` output, the credentials file's
mtime). A login known to be expired (same fingerprint, younger than ``VSTUDIO_AUTH_CACHE_TTL`` s, default 3600) is
reported instantly (``probe.cached``) instead of a probe that an expired ``claude -p`` drags out for ~3 minutes, and
``vstudio.llm.complete`` skips that provider at once (straight to the fallback). ``--refresh`` (the desk's
"check again", after a login) ignores the cache. Probes time out after ``--timeout`` (default 60 s).

``login`` / ``logout`` only print the command (absolute CLI path + args) and the variables to remove; the desk runs it
in a terminal so the browser / code-paste flow happens with the user, not through this engine.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import time

from . import llm as L

INSTALL = {
    "claude-code": dict(url="https://docs.claude.com/en/docs/claude-code/setup",
                        command="curl -fsSL https://claude.ai/install.sh | bash"),
    "codex": dict(url="https://developers.openai.com/codex/cli", command="npm install -g @openai/codex"),
    "anthropic": dict(url="https://console.anthropic.com/settings/keys", command="pip install anthropic"),
    "openai": dict(url="https://platform.openai.com/api-keys", command="pip install openai"),
    "gemini": dict(url="https://aistudio.google.com/apikey", command="pip install google-genai"),
    "deepseek": dict(url="https://platform.deepseek.com/api_keys", command="pip install openai"),
    "qwen": dict(url="https://dashscope.console.aliyun.com/apiKey", command="pip install openai"),
    "kimi": dict(url="https://platform.moonshot.cn/console/api-keys", command="pip install openai"),
    "glm": dict(url="https://open.bigmodel.cn/usercenter/apikeys", command="pip install openai"),
    "openrouter": dict(url="https://openrouter.ai/keys", command="pip install openai"),
    "ollama": dict(url="https://ollama.com/download", command="ollama serve && ollama pull qwen3:8b"),
    "lmstudio": dict(url="https://lmstudio.ai", command="LM Studio > Developer > Start server"),
    "vllm": dict(url="https://docs.vllm.ai/en/latest/getting_started/quickstart.html", command="vllm serve <model>"),
    "llamacpp": dict(url="https://github.com/ggml-org/llama.cpp", command="llama-server -m model.gguf"),
}
CLIS = {"claude-code": dict(exe="claude", strip=L.CLI_STRIP_ENV), "codex": dict(exe="codex", strip=L.CODEX_STRIP_ENV)}
API = ("anthropic", "openai", "gemini", "deepseek", "qwen", "kimi", "glm", "openrouter")
LOCALS = ("ollama", "lmstudio", "vllm", "llamacpp")
ORDER = ("claude-code", "codex") + API + LOCALS
KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY"}
PKG = {"anthropic": "anthropic", "gemini": "google.genai"}

MSG = {   # code -> (en, zh); {params} filled from the row
    "auth-logged-in": ("Logged in{plan_s}{email_s}", "已登录{plan_s}{email_s}"),
    "auth-expired": ("The login has expired: log in again", "登录已过期，请重新登录"),
    "auth-not-logged-in": ("Not logged in", "未登录"),
    "auth-not-installed": ("{exe} is not installed", "未安装 {exe}"),
    "auth-api-key-login": ("Logged in with an API key (API billing, not the subscription)",
                           "用 API 密钥登录（按 API 计费，不走订阅）"),
    "auth-error": ("Could not check the login: {error}", "无法检查登录状态：{error}"),
    "auth-timeout": ("The login check did not answer in {seconds} s", "登录检查 {seconds} 秒内没有响应"),
    "key-configured": ("{key_env} is set", "已配置 {key_env}"),
    "key-missing": ("{key_env} is not set", "未配置 {key_env}"),
    "package-missing": ("Needs the Python package: {command}", "需要安装 Python 包：{command}"),
    "local-up": ("Running at {base_url} · {n} models", "本地服务运行中 {base_url} · {n} 个模型"),
    "local-down": ("No server answering at {base_url}", "本地服务未运行（{base_url}）"),
    "local-no-models": ("{base_url} answers but lists no models", "{base_url} 有响应但没有模型"),
    "login-command": ("Run {display} and finish in the browser", "运行 {display}，在浏览器里完成登录"),
    "logout-command": ("Run {display}", "运行 {display}"),
    "login-unsupported": ("{provider} has no CLI login: add a key instead", "{provider} 没有命令行登录，请填写密钥"),
}


def msg(code, _fmt=None, **params):
    """{code, params, message, message_zh}; ``_fmt``: extra values used only to format the texts."""
    en, zh = MSG[code]
    p = {k: ("" if v is None else v) for k, v in {**params, **(_fmt or {})}.items()}
    return dict(code=code, params=params, message=en.format(**p), message_zh=zh.format(**p))


def _run(cmd, env, timeout, input=None):
    """(returncode, stdout, stderr) of a CLI in an empty temp dir; (-1, "", why) when it cannot run."""
    cmd = [*L.cli_argv(cmd[0]), *cmd[1:]]                  # Windows: npm .cmd shims run through node directly
    with tempfile.TemporaryDirectory(prefix="vstudio-auth-") as tmp:
        try:
            r = subprocess.run(cmd, input=input, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               cwd=tmp, timeout=timeout, env=env)
        except subprocess.TimeoutExpired:
            return -1, "", f"timed out after {timeout} s"
        except OSError as e:
            return -1, "", str(e)
    return r.returncode, r.stdout or "", r.stderr or ""


def cli_env(provider, base=None):
    """The environment a subscription CLI runs with: API keys / base URLs removed (the user's own login)."""
    return L.strip_env(os.environ if base is None else base, CLIS[provider]["strip"])


def _base_row(provider, kind):
    return dict(provider=provider, kind=kind, state="error", ready=False, installed=None, version=None, account=None,
                key_env=None, base_url=None, models=None, probe=None, can_login=False, can_logout=False,
                install=INSTALL.get(provider), message=None)


# ------------------------------------------------------------------ parsing (pure: unit-tested)
EXPIRED = re.compile(r"\b401\b|token (has )?expired|expired token|oauth token|invalid_grant|refresh token|"
                     r"re-?authenticate|authentication_error|unauthori[sz]ed|failed to authenticate", re.I)
NOT_LOGGED = re.compile(r"not logged in|please run /login|invalid api key|no credentials|login required", re.I)


def parse_claude_status(text):
    """``claude auth status --json`` -> dict(logged_in, account) (None when it is not JSON)."""
    try:
        d = json.loads(text or "")
    except ValueError:
        return None
    if not isinstance(d, dict):
        return None
    plan = d.get("subscriptionType") or None
    acct = dict(email=d.get("email") or None, plan=plan, auth_method=d.get("authMethod") or None,
                org=d.get("orgName") or None, api_provider=d.get("apiProvider") or None)
    return dict(logged_in=bool(d.get("loggedIn")), account=acct)


def parse_claude_probe(rc, out, err):
    """A ``claude -p --output-format json`` reply -> (state, detail): logged-in | expired | not-logged-in | error."""
    d = None
    try:
        d = json.loads(out or "")
    except ValueError:
        pass
    if isinstance(d, dict) and not d.get("is_error") and rc == 0:
        return "logged-in", None
    text = str((d or {}).get("result") or "") + " " + (err or "") + ("" if d else " " + (out or ""))
    status = (d or {}).get("api_error_status")
    if NOT_LOGGED.search(text) and status != 401:
        return "not-logged-in", text.strip()[:200]
    if status in (401, 403) or EXPIRED.search(text):
        return "expired", text.strip()[:200]
    return "error", (text.strip() or f"exit {rc}")[:200]


def parse_codex_status(rc, out, err):
    """``codex login status`` -> dict(logged_in, auth_method). Never keeps the (masked) key it may print."""
    t = f"{out}\n{err}"
    if re.search(r"not logged in", t, re.I):
        return dict(logged_in=False, auth_method=None)
    m = re.search(r"logged in using (?:an? )?(chatgpt|api key|access token)", t, re.I)
    if m:
        how = m.group(1).lower()
        return dict(logged_in=True, auth_method="chatgpt" if how == "chatgpt" else how.replace(" ", "-"))
    if rc == 0 and re.search(r"logged in", t, re.I):
        return dict(logged_in=True, auth_method=None)
    return dict(logged_in=False, auth_method=None)


def parse_codex_probe(rc, out, err):
    errs = []
    for ln in (out or "").splitlines():
        try:
            ev = json.loads(ln)
        except ValueError:
            continue
        if ev.get("type") in ("turn.failed", "error"):
            e = ev.get("error")
            errs.append(str(e.get("message") if isinstance(e, dict) else ev.get("message") or e or ev.get("type")))
        if ev.get("type") == "turn.completed" and rc == 0:
            return "logged-in", None
    text = " ".join(errs) + " " + (err or "")
    if rc == 0 and not errs:
        return "logged-in", None
    if NOT_LOGGED.search(text):
        return "not-logged-in", text.strip()[:200]
    if EXPIRED.search(text):
        return "expired", text.strip()[:200]
    return "error", (text.strip() or f"exit {rc}")[:200]


# ------------------------------------------------------------------ cache (known-expired logins)
PROBE_TIMEOUT = 60
CRED_FILES = {"claude-code": ("~/.claude/.credentials.json",), "codex": ("~/.codex/auth.json",)}


def cache_path():
    f = os.environ.get("VSTUDIO_AUTH_CACHE")
    if f:
        return os.path.expanduser(f)
    home = os.path.expanduser(os.environ.get("VSTUDIO_HOME") or "~/.config/vstudio")
    return os.path.join(home, "auth-cache.json")


def cache_ttl():
    try:
        return float(os.environ.get("VSTUDIO_AUTH_CACHE_TTL") or 3600)
    except ValueError:
        return 3600.0


def _read_cache():
    try:
        with open(cache_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_cache(d):
    p = cache_path()
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
    except OSError:
        pass                                   # a read-only home never breaks a status check / an AI call


def _mtime(p):
    try:
        return os.stat(os.path.expanduser(p)).st_mtime
    except OSError:
        return None


def fingerprint(provider, status_out=None):
    """A hash that changes when the login changes (re-login, other CLI, other account); no secret is read.
    ``status_out``: the ``auth status`` / ``login status`` output when the caller already has it."""
    if provider not in CLIS:
        return None
    exe = L.find_cli(CLIS[provider]["exe"])
    if not exe:
        return None
    if status_out is None:
        args = ["auth", "status", "--json"] if provider == "claude-code" else ["login", "status"]
        rc, out, err = _run([exe, *args], cli_env(provider), 20)
        status_out = f"{rc}|{out}|{err}"
    parts = [os.path.realpath(exe), _mtime(exe), status_out] + [_mtime(f) for f in CRED_FILES.get(provider, ())]
    return hashlib.sha1(json.dumps(parts, default=str).encode()).hexdigest()[:16]


def remember(provider, state, detail=None, fp=None):
    """Record a CLI login state (probe result, or an AI call that failed with an auth error / timed out / succeeded).
    ``fp=""``: store without a fingerprint (computing one runs the CLI, which a hung CLI would drag out)."""
    if provider not in CLIS:
        return
    d = _read_cache()
    if state == "logged-in" and provider not in d:
        return                                  # nothing to clear: the common path stays file-free
    d[provider] = dict(state=state, at=time.time(), detail=(detail or "")[:200] or None,
                       fp=fp if fp is not None else fingerprint(provider))
    _write_cache(d)


def forget(provider=None):
    d = _read_cache()
    for p in [provider] if provider else list(d):
        d.pop(p, None)
    _write_cache(d)


def known_state(provider, fp=None):
    """The cached entry {state, at, detail} when it is still valid (same fingerprint, within the TTL), else None."""
    e = _read_cache().get(provider)
    if not isinstance(e, dict) or time.time() - float(e.get("at") or 0) > cache_ttl():
        return None
    if (fp if fp is not None else fingerprint(provider)) != e.get("fp"):
        return None
    return e


def known_expired(provider):
    """True when ``provider``'s login is known to be expired / logged out (checked without a probe)."""
    if provider not in CLIS or not os.path.exists(cache_path()):
        return False
    e = known_state(provider)
    return bool(e and e.get("state") in ("expired", "not-logged-in"))


def unresponsive_ttl():
    try:
        return float(os.environ.get("VSTUDIO_LLM_UNRESPONSIVE_TTL") or 600)
    except ValueError:
        return 600.0


def known_unresponsive(provider):
    """True when ``provider``'s CLI timed out on a call in the last ``VSTUDIO_LLM_UNRESPONSIVE_TTL`` s (default 10 min)
    and nothing has answered since: ``vstudio.llm.complete`` then goes straight to the fallback instead of waiting
    the whole CLI timeout again (a dead / hung ``claude -p`` cost every plan 120 s before Codex took over)."""
    if provider not in CLIS or not os.path.exists(cache_path()):
        return False
    # no fingerprint here: it runs `claude auth status`, which a hung CLI drags out too - the short TTL is the guard
    e = _read_cache().get(provider)
    return bool(isinstance(e, dict) and e.get("state") == "unresponsive"
                and time.time() - float(e.get("at") or 0) < unresponsive_ttl())


# ------------------------------------------------------------------ per provider
def _claude_code(probe=True, timeout=PROBE_TIMEOUT, refresh=False):
    row = _base_row("claude-code", "subscription-cli")
    exe = L.find_cli("claude")
    if not exe:
        return dict(row, state="not-installed", installed=False, message=msg("auth-not-installed", exe="claude"))
    env = cli_env("claude-code")
    row.update(installed=True, exe=exe, version=L._cli_version(exe), can_login=True, can_logout=True)
    rc, out, err = _run([exe, "auth", "status", "--json"], env, 20)
    fp = fingerprint("claude-code", f"{rc}|{out}|{err}")
    st = parse_claude_status(out)
    if st is None:
        # older CLIs have no `auth status`: the probe alone decides
        st = dict(logged_in=None, account=None)
    row["account"] = st["account"]
    if st["logged_in"] is False:
        return dict(row, state="not-logged-in", message=msg("auth-not-logged-in"))
    state, detail = ("logged-in", None) if st["logged_in"] else ("error", (err or out).strip()[:200] or None)
    known = None if refresh else known_state("claude-code", fp)
    if known and known.get("state") in ("expired", "not-logged-in"):
        state, detail = known["state"], known.get("detail")
        row["probe"] = dict(ran=False, cached=True, state=state, at=known.get("at"))
        return dict(row, state=state, ready=False, verified=True, detail=detail, message=_cli_msg(state, row, detail))
    if probe:
        t0 = time.time()
        prc, pout, perr = _run([exe, "-p", "--output-format", "json", "--tools", "", "--no-session-persistence",
                                "--strict-mcp-config", "--model", "haiku"], env, timeout, input="Reply with: ok")
        state, detail = parse_claude_probe(prc, pout, perr)
        if prc == -1 and "timed out" in perr:
            state, detail = "error", perr
            row["probe"] = dict(ran=True, state="timeout", seconds=round(time.time() - t0, 1))
            remember("claude-code", "unresponsive", perr, fp="")   # AI calls go straight to the fallback meanwhile
            return dict(row, state=state, ready=False, verified=False, detail=detail,
                        message=msg("auth-timeout", seconds=timeout))
        row["probe"] = dict(ran=True, state=state)
        if state in ("expired", "not-logged-in", "logged-in"):
            remember("claude-code", state, detail, fp)
    else:
        row["probe"] = dict(ran=False)       # "logged-in" from `auth status` alone: an expired token looks the same
    return dict(row, state=state, ready=state == "logged-in", verified=bool(probe), detail=detail,
                message=_cli_msg(state, row, detail))


def _codex(probe=False, timeout=PROBE_TIMEOUT, refresh=False):
    row = _base_row("codex", "subscription-cli")
    exe = L.find_cli("codex")
    if not exe:
        return dict(row, state="not-installed", installed=False, message=msg("auth-not-installed", exe="codex"))
    env = cli_env("codex")
    row.update(installed=True, exe=exe, version=L._cli_version(exe), can_login=True, can_logout=True)
    rc, out, err = _run([exe, "login", "status"], env, 20)
    fp = fingerprint("codex", f"{rc}|{out}|{err}")
    st = parse_codex_status(rc, out, err)
    row["account"] = dict(email=None, plan=None, auth_method=st["auth_method"], org=None)
    if not st["logged_in"]:
        return dict(row, state="not-logged-in", message=msg("auth-not-logged-in"), probe=dict(ran=False))
    state, detail = "logged-in", None
    known = None if refresh else known_state("codex", fp)
    if known and known.get("state") in ("expired", "not-logged-in"):
        state, detail = known["state"], known.get("detail")
        row["probe"] = dict(ran=False, cached=True, state=state, at=known.get("at"))
        return dict(row, state=state, ready=False, detail=detail, message=_cli_msg(state, row, detail))
    if probe:
        with tempfile.TemporaryDirectory(prefix="vstudio-auth-") as tmp:
            prc, pout, perr = _run([exe, "exec", "--json", "--sandbox", "read-only", "--skip-git-repo-check",
                                    "--cd", tmp, "-"], env, timeout, input="Reply with: ok")
        state, detail = parse_codex_probe(prc, pout, perr)
        row["probe"] = dict(ran=True, state=state)
        if state in ("expired", "not-logged-in", "logged-in"):
            remember("codex", state, detail, fp)
    else:
        row["probe"] = dict(ran=False)
    m = _cli_msg(state, row, detail)
    if state == "logged-in" and st["auth_method"] == "api-key":
        m = msg("auth-api-key-login")
    return dict(row, state=state, ready=state == "logged-in", detail=detail, message=m)


def _cli_msg(state, row, detail):
    if state == "logged-in":
        a = row.get("account") or {}
        plan, email = a.get("plan"), a.get("email")
        return msg("auth-logged-in", dict(plan_s=f" · {plan.title()}" if plan else "",
                                          email_s=f" · {email}" if email else ""), plan=plan, email=email)
    if state == "expired":
        return msg("auth-expired")
    if state == "not-logged-in":
        return msg("auth-not-logged-in")
    return msg("auth-error", error=detail or "unknown")


def _api(p):
    row = _base_row(p, "api")
    if p in L.PRESETS:
        base, key_env, _, _ = L.compatible_target(p, {})
        row["base_url"], pkg = base, "openai"
    else:
        key_env, pkg = KEY_ENV[p], PKG.get(p, "openai")
    has_key = bool(os.environ.get(key_env)) or (p == "gemini" and bool(os.environ.get("GOOGLE_API_KEY")))
    row.update(key_env=key_env, installed=L._has(pkg))
    if not has_key:
        return dict(row, state="not-configured", message=msg("key-missing", key_env=key_env))
    if not row["installed"]:
        return dict(row, state="configured", message=msg("package-missing", command=INSTALL[p]["command"]))
    return dict(row, state="configured", ready=True, message=msg("key-configured", key_env=key_env))


def _local(p, probe=True):
    row = _base_row(p, "local")
    c = L.check(p, probe=probe)
    base = L.compatible_target(p, {})[0]
    row.update(base_url=base, models=c.get("models"))
    if c["ready"]:
        return dict(row, state="ready", ready=True, installed=True,
                    message=msg("local-up", base_url=base, n=len(c.get("models") or [])))
    if "lists no models" in c.get("detail", ""):
        return dict(row, state="no-models", message=msg("local-no-models", base_url=base))
    return dict(row, state="server-down", message=msg("local-down", base_url=base))


def status(providers=None, probe=True, deep=False, refresh=False, timeout=PROBE_TIMEOUT):
    """One row per provider (see module doc). ``probe``: the claude-code round-trip; ``deep``: also codex's;
    ``refresh``: ignore the cached known-expired state; ``timeout``: seconds per probe."""
    out = []
    for p in providers or ORDER:
        p = L.canonical(p) or p
        try:
            if p == "claude-code":
                out.append(_claude_code(probe=probe, timeout=timeout, refresh=refresh))
            elif p == "codex":
                out.append(_codex(probe=probe and deep, timeout=timeout, refresh=refresh))
            elif p in API:
                out.append(_api(p))
            elif p in LOCALS:
                out.append(_local(p, probe=probe))
        except Exception as e:  # noqa: BLE001 - one broken provider must not hide the others
            out.append(dict(_base_row(p, "unknown"), message=msg("auth-error", error=str(e)[:200])))
    return out


def command(provider, action="login", variant=None):
    """{provider, action, command [abs exe, args], display, env_unset, variants} - nothing is run."""
    p = L.canonical(provider)
    if p not in CLIS:
        return dict(ok=False, provider=provider, action=action,
                    message=msg("login-unsupported", provider=provider))
    exe = L.find_cli(CLIS[p]["exe"])
    if not exe:
        return dict(ok=False, provider=p, action=action, install=INSTALL[p],
                    message=msg("auth-not-installed", exe=CLIS[p]["exe"]))
    variants = []
    if p == "claude-code":
        rc, out, err = _run([exe, "auth", "--help"], cli_env(p), 15)
        has_auth = rc == 0 and re.search(r"^\s*login\b", out, re.M)
        if action == "login":
            args = ["auth", "login"] if has_auth else []          # older CLIs: interactive `claude`, then /login
            if has_auth:
                variants = [dict(id="console", args=["auth", "login", "--console"]),
                            dict(id="sso", args=["auth", "login", "--sso"])]
        else:
            args = ["auth", "logout"] if has_auth else ["logout"]
    else:
        if action == "login":
            args = ["login"]
            rc, out, err = _run([exe, "login", "--help"], cli_env(p), 15)
            if "--device-auth" in out:
                variants = [dict(id="device", args=["login", "--device-auth"])]
        else:
            args = ["logout"]
    chosen = next((v["args"] for v in variants if v["id"] == variant), args)
    display = " ".join([CLIS[p]["exe"], *chosen])
    return dict(ok=True, provider=p, action=action, command=[*L.cli_argv(exe), *chosen], display=display,
                env_unset=list(CLIS[p]["strip"]), interactive=action == "login",
                variants=[dict(v, display=" ".join([CLIS[p]["exe"], *v["args"]])) for v in variants],
                note=None if args else "type /login in the session, then /exit",
                message=msg("login-command" if action == "login" else "logout-command", display=display))


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="python -m vstudio.llm auth")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status", help="login / key / server status of each provider")
    s.add_argument("--provider", action="append")
    s.add_argument("--json", action="store_true")
    s.add_argument("--no-probe", action="store_true", help="skip the tiny claude round-trip and local probes")
    s.add_argument("--deep", action="store_true", help="also probe codex with a tiny round-trip")
    s.add_argument("--refresh", action="store_true", help="ignore the cached known-expired state (after a login)")
    s.add_argument("--timeout", type=float, default=PROBE_TIMEOUT, help="seconds per probe (default 60)")
    sub.add_parser("forget", help="clear the cached login states")
    for name in ("login", "logout"):
        x = sub.add_parser(name, help=f"print the command that {name}s (the engine runs nothing)")
        x.add_argument("--provider", required=True)
        x.add_argument("--variant")
        x.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "status":
        rows = status(a.provider, probe=not a.no_probe, deep=a.deep, refresh=a.refresh, timeout=a.timeout)
        if a.json:
            print(json.dumps(dict(providers=rows), indent=2, ensure_ascii=False))
        else:
            for r in rows:
                print(f"  {r['state']:<14} {r['provider']:<12} {(r.get('message') or {}).get('message', '')}")
        return 0
    if a.cmd == "forget":
        forget()
        print(json.dumps(dict(ok=True)))
        return 0
    d = command(a.provider, a.cmd, a.variant)
    if a.json:
        print(json.dumps(d, indent=2, ensure_ascii=False))
    else:
        print(d.get("display") or d["message"]["message"])
    return 0 if d.get("ok") else 1
