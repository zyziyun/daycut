"""The useful end of a child process's output, for stage errors.

A failed render prints thousands of progress-bar redraws (``\\r``-separated), ``@hf-progress`` lines and JSON
trace records; a stage error built from "the last 1500 characters" then holds only progress bars and the real
reason (an ffmpeg / dyld / Python error line) is gone. :func:`tail` keeps the last ``n`` meaningful lines.

    from vstudio import proctail
    proctail.tail(stderr_text)            # -> "line\\nline\\n..." (<= 20 lines)
    proctail.is_noise("  45% |█████▌   | 120/300")  # True
"""
import re

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")
_NOISE = (
    re.compile(r"@hf-progress", re.I),
    re.compile(r"^\s*\[(INFO|DEBUG|TRACE)\]"),                       # hyperframes' structured log records
    re.compile(r"^\s*\{.*\"(phase|progress|elapsedMs|framesCompleted)\".*\}\s*$"),
    re.compile(r"[█▉▊▋▌▍▎▏░▒▓■□━─╸╺]{3,}"),                          # drawn bars
    re.compile(r"^\s*[\[(|]?[=#>\-. ]{6,}[\])|]?\s*\d{1,3}(\.\d+)?\s*%"),   # [=====>   ] 45%
    re.compile(r"^\s*\d{1,3}(\.\d+)?\s*%\s*([|\[(]|$)"),                # 45% |...
    re.compile(r"^\s*[⠁-⣿◐◓◑◒|/\\-]\s+\S.*\d+\s*/\s*\d+\s*$"),        # spinner + n/total
    re.compile(r"^\s*(frame|size)=\s*\d+.*(fps|time)=", re.I),       # ffmpeg -stats
    re.compile(r"^\s*(capturing|encoding|rendering)\b.*\d+\s*/\s*\d+", re.I),
    re.compile(r"^\s*\[initSession[:\]]"),                            # hyperframes per-worker session chatter
    re.compile(r"Keep editing by chatting|hyperframes\.dev/studio/download"),
)


def is_noise(line):
    s = _ANSI.sub("", line or "").strip()
    return not s or any(rx.search(s) for rx in _NOISE)


def lines(text):
    """Text -> clean lines (ANSI removed, a ``\\r`` redraw keeps only its last state)."""
    out = []
    for ln in str(text or "").replace("\r\n", "\n").split("\n"):
        if "\r" in ln:
            ln = next((p for p in reversed(ln.split("\r")) if p.strip()), "")
        out.append(_ANSI.sub("", ln).rstrip())
    return out


def tail(text, n=20, max_chars=2000):
    """The last ``n`` meaningful lines of ``text`` (progress / trace noise and blank lines removed), joined."""
    keep = [ln for ln in lines(text) if not is_noise(ln)]
    # a repeated line (the same warning per frame) counts once
    dedup = []
    for ln in keep:
        if not dedup or dedup[-1] != ln:
            dedup.append(ln)
    s = "\n".join(dedup[-n:])
    return s[-max_chars:] if len(s) > max_chars else s


def clean_error(msg, n=20, max_chars=2000):
    """A stage error ``"<head>: <captured output>"`` -> the head + the meaningful tail of the output."""
    s = str(msg or "")
    first, _, rest = s.partition("\n")
    head, sep, body = first.partition(": ")
    if not sep:
        head, body = "", first
    t = tail(body + "\n" + rest, n, max_chars)
    if not head:
        return t
    if not t:
        return f"{head}: (no error output)"
    return f"{head}:\n{t}" if "\n" in t else f"{head}: {t}"


# missing / broken external tools a stage needs (Node.js for HyperFrames, ffmpeg): code + params for the desk
_TOOLS = (
    ("node", re.compile(r"node unavailable|referenced from:\s*\S*/node\b|library not loaded\S*.*\bnode\b|"
                        r"npx \(node\) not found|env: node: no such file|node(\.js)? \S* ?is too old", re.I | re.S)),
    ("ffmpeg", re.compile(r"ffmpeg not found|ffprobe not found|vstudio_ff(mpeg|probe)=\S* does not exist|"
                          r"lacks filter\(s\)|unknown bitstream filter|no such filter|"
                          r"referenced from:\s*\S*/ff(mpeg|probe)\b|ff(mpeg|probe): (command )?not found", re.I)),
)


def tool_failure(text):
    """An error caused by a missing / broken external tool -> {code: "tool-node" | "tool-ffmpeg",
    params: {tool, fix}}; else None. fix: brew-reinstall-node | install-node | reinstall-app | install-ffmpeg."""
    t = str(text or "")
    low = t.lower()
    for tool, rx in _TOOLS:
        if rx.search(t):
            if tool == "node":
                brew = ("homebrew" in low or "/cellar/" in low or "brew reinstall" in low) and "too old" not in low
                fix = "brew-reinstall-node" if brew else "install-node"
            else:
                bundled = "reelfold.app" in low or "/runtime/ffmpeg" in low or "vstudio_ff" in low
                fix = "reinstall-app" if bundled else "install-ffmpeg"
            return dict(code=f"tool-{tool}", params=dict(tool=tool, fix=fix))
    return None
