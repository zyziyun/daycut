"""A nested `claude -p` must not inherit the host Claude Code session (it hangs, then 401s)."""
from vstudio import llm


def test_session_vars_dropped_provider_settings_kept():
    env = {
        "PATH": "/usr/bin", "HOME": "/h",
        "CLAUDECODE": "1", "CLAUDE_PID": "42", "CLAUDE_EFFORT": "high", "CLAUDE_AGENT_SDK_VERSION": "1",
        "CLAUDE_CODE_SESSION_ID": "s", "CLAUDE_CODE_MESSAGING_TOKEN": "t", "CLAUDE_CODE_CHILD_SESSION": "1",
        "CLAUDE_CODE_ENTRYPOINT": "sdk", "CLAUDE_CODE_OAUTH_SCOPES": "x",
        "CLAUDE_CODE_USE_BEDROCK": "1", "CLAUDE_CODE_USE_VERTEX": "1", "CLAUDE_CODE_SKIP_BEDROCK_AUTH": "1",
        "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "8000", "CLAUDE_CODE_API_KEY_HELPER_TTL_MS": "1",
    }
    out = llm.strip_claude_session_env(env)
    for k in ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT", "CLAUDE_AGENT_SDK_VERSION", "CLAUDE_CODE_SESSION_ID",
              "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_ENTRYPOINT",
              "CLAUDE_CODE_OAUTH_SCOPES"):
        assert k not in out, k
    for k in ("PATH", "HOME", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_SKIP_BEDROCK_AUTH",
              "CLAUDE_CODE_MAX_OUTPUT_TOKENS", "CLAUDE_CODE_API_KEY_HELPER_TTL_MS"):
        assert k in out, k
