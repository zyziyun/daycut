"""Built-in agent runners: Claude Code (headless ``claude -p``), Codex (``codex exec``) and a generic command.

All of them run with cwd = the job folder and the brief on stdin, may only write inside the job folder, and use
the user's own CLI login (API keys / base URLs are removed from their environment like the AI-provider CLIs, so
the subscription is used, not a key that would bill per token).
"""
from vstudio.plugins.contract import AgentRunner, CommandRunner

PROMPT = ("You are working in a Reelfold job folder (the current directory). Read brief.md and job.json, use the "
          "files in inputs/, and write the finished shot (an .mp4, or a .png / .jpg still) into outputs/. You may "
          "update status.json {\"progress\": 0..1, \"message\": \"...\"} while you work. Do not touch anything "
          "outside this folder. When done, write outputs/result.json {\"files\": [...], \"notes\": \"...\"}.")


def _clean_env(strip):
    import os
    from vstudio.llm import strip_env
    return strip_env(os.environ, strip)


class ClaudeCodeRunner(AgentRunner):
    id = "claude-code"
    exe = "claude"
    stdin_brief = False                 # the prompt points at brief.md

    def command(self, job):
        tools = self.settings.get("allowed_tools") or (self.manifest or {}).get("allowed_tools") or \
            "Read,Write,Edit,Glob,Grep,Bash(hyperframes:*),Bash(./node_modules/.bin/hyperframes:*),Bash(ffmpeg:*),Bash(ffprobe:*)"
        cmd = [self.find(), "-p", PROMPT, "--output-format", "json", "--permission-mode", "acceptEdits",
               "--allowedTools", tools, "--no-session-persistence"]
        if self.settings.get("model"):
            cmd += ["--model", str(self.settings["model"])]
        return cmd

    def env(self, job):
        from vstudio.llm import CLI_STRIP_ENV
        return _clean_env(CLI_STRIP_ENV)


class CodexRunner(AgentRunner):
    id = "codex"
    exe = "codex"
    stdin_brief = False

    def command(self, job):
        cmd = [self.find(), "exec", "--sandbox", "workspace-write", "--skip-git-repo-check", "--cd", job["dir"]]
        if self.settings.get("model"):
            cmd += ["--model", str(self.settings["model"])]
        return cmd + [PROMPT]

    def env(self, job):
        from vstudio.llm import CODEX_STRIP_ENV
        return _clean_env(CODEX_STRIP_ENV)


class ShellRunner(CommandRunner):
    """Any command: set it in Settings (plugins.json settings["agent-runner:shell"].command = [argv...])."""
    id = "shell"
