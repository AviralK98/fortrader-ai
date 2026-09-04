"""How a question reaches a model.

Two transports. The Claude Code CLI uses the subscription the user
already has; the API uses a key they must buy. Neither one holds a
guardrail: the caps, the system prompt and the grounding all live in
`service.ask` above this module, so a transport cannot weaken a rule it
never sees.

The CLI is the interesting case. A Claude Code session is normally an
agent with a shell and a filesystem, which is far more authority than
answering a question about a chart requires. Every invocation here is
therefore locked down: only this application's read-only MCP tools are
reachable, every built-in tool is removed from context, no other MCP
server the user has configured is loaded, and nothing persists between
turns. That is enforced by flags rather than by asking politely.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Protocol

from backend.logging_setup import get_logger

logger = get_logger(__name__)

MODEL = "claude-opus-5"
EFFORT = "medium"
MAX_TOKENS = 2048

#: The MCP server this application registers. Must match SERVER_NAME in
#: desktop/main/mcp-setup.ts.
MCP_SERVER_NAME = "fortrader-ai"

#: A question about a chart never needs a shell or a file. Passing a bare
#: tool name to --disallowedTools removes it from the model's context
#: entirely, so these are not merely un-approved -- they are absent.
DENIED_TOOLS = (
    "Bash",
    "BashOutput",
    "KillShell",
    "Write",
    "Edit",
    "NotebookEdit",
    "Read",
    "Glob",
    "Grep",
    "WebSearch",
    "WebFetch",
    "Task",
    "TodoWrite",
)

#: A grounded answer needs a handful of tool calls, not an exploration.
MAX_TURNS = 6

#: A wedged subprocess must not wedge the request thread with it.
CLI_TIMEOUT_SECONDS = 120

#: Probing the binary costs a process spawn, so the answer is cached for
#: the life of the backend.
_cli_probe: tuple[bool, str | None] | None = None


def _hidden() -> dict[str, Any]:
    """Spawn without a console window.

    `claude` is a console program. Started from a windowed application it
    gets a console of its own, which on Windows means a black box appears
    over the chart for as long as the answer takes and then vanishes. The
    panel already says it is working; a second window saying nothing is
    just noise.
    """
    # The flag and the platform are looked up independently because they
    # can disagree under test, where sys.platform is patched but the
    # constant is still whatever the host provides.
    flag = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    if sys.platform == "win32" and flag:
        return {"creationflags": flag}

    return {}


class ChatProvider(Protocol):
    name: str

    def available(self) -> tuple[bool, str | None]:
        """Whether this transport can run, and why not if it cannot."""
        ...

    def complete(self, system: str, prompt: str) -> str:
        """Return the model's answer as plain text."""
        ...


class ApiProvider:
    """A single Messages call. No tools, no agent loop."""

    name = "api"

    def available(self) -> tuple[bool, str | None]:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return (False, "No ANTHROPIC_API_KEY configured.")

        try:
            import anthropic  # noqa: F401
        except ImportError:
            return (False, "The `anthropic` package is not installed.")

        return (True, None)

    def complete(self, system: str, prompt: str) -> str:
        import anthropic

        response = anthropic.Anthropic().messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": EFFORT},
            messages=[{"role": "user", "content": prompt}],
        )

        if response.stop_reason == "refusal":
            raise RuntimeError("The model declined to answer.")

        return "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()


def _mcp_config_path() -> Path:
    """Write a config naming only this application's server.

    Paired with --strict-mcp-config, this is what stops the session from
    loading whatever other MCP servers the user happens to have.
    """
    from backend.config import load_settings

    if getattr(sys, "frozen", False):
        entry: dict[str, Any] = {
            "type": "stdio",
            "command": sys.executable,
            "args": ["--mcp"],
        }
    else:
        entry = {
            "type": "stdio",
            "command": sys.executable,
            "args": ["-m", "backend.main", "--mcp"],
            "cwd": str(Path(__file__).resolve().parents[2]),
        }

    path = load_settings().data_dir / "chat-mcp.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"mcpServers": {MCP_SERVER_NAME: entry}}, indent=2),
        encoding="utf-8",
    )

    return path


def _claude_candidates() -> tuple[Path, ...]:
    """Where Claude Code lands when PATH does not say."""
    home = Path.home()

    # Windows needs the extension; a bare `claude` there is the shell
    # script for WSL and cannot be spawned by CreateProcess.
    names = ("claude.exe", "claude") if os.name == "nt" else ("claude",)

    directories = (
        # Claude Code's own installer, and the default it suggests.
        home / ".local" / "bin",
        # Older installs, and what `claude migrate-installer` produces.
        home / ".claude" / "local",
        # npm -g with a user-owned prefix.
        home / ".npm-global" / "bin",
        Path("/opt/homebrew/bin"),
        Path("/usr/local/bin"),
    )

    return tuple(d / n for d in directories for n in names)


def find_claude() -> str | None:
    """Locate the Claude Code CLI.

    `shutil.which` searches PATH, which is correct in a terminal and
    wrong in a packaged app. macOS starts a .app from LaunchServices
    with an environment that never sourced .zshrc, so a binary in
    ~/.local/bin -- where Claude Code installs itself -- is not on the
    PATH this process inherited, and the app ends up telling a user who
    has Claude Code that they do not.

    The desktop shell widens PATH from the login shell before the
    backend starts, which fixes the common case. This is the second
    line: it still answers correctly when there is no login shell to
    ask, when the profile is unusual, or when the backend is run on its
    own.

    Only PATH gets a bare name; the fallbacks are absolute and are
    checked for being executable files, so nothing here can resolve to
    a directory or to something the user cannot run.
    """
    found = shutil.which("claude")

    if found is not None:
        return found

    for candidate in _claude_candidates():
        try:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
        except OSError:
            # An unreadable home or a broken symlink is not an error
            # here -- it just means this candidate is not the answer.
            continue

    return None


class CliProvider:
    """One locked-down `claude -p` invocation per question."""

    name = "cli"

    def available(self) -> tuple[bool, str | None]:
        global _cli_probe

        if _cli_probe is not None:
            return _cli_probe

        binary = find_claude()

        if binary is None:
            # Deliberately not cached. Someone who installs Claude Code
            # while the app is open should not have to restart it, and a
            # PATH lookup is cheap enough to repeat.
            return (
                False,
                "Claude Code is not installed, or `claude` could not be "
                "found on PATH or in a standard install location.",
            )

        # Actually run it. Whether a .cmd shim or a shell wrapper can be
        # spawned varies by platform and install method, and a clear
        # message now beats a confusing failure on the first question.
        try:
            probe = subprocess.run(
                [binary, "--version"],
                capture_output=True,
                timeout=30,
                shell=False,
            )
            _cli_probe = (
                (True, None)
                if probe.returncode == 0
                else (False, f"`claude --version` exited {probe.returncode}.")
            )
        except (OSError, subprocess.SubprocessError) as error:
            _cli_probe = (False, f"Could not run the Claude Code CLI: {error}")

        return _cli_probe

    def complete(self, system: str, prompt: str) -> str:
        binary = find_claude()

        if binary is None:
            raise RuntimeError("The Claude Code CLI disappeared from PATH.")

        config = _mcp_config_path()

        argv = [
            binary,
            "-p",
            "--output-format",
            "json",
            "--append-system-prompt",
            system,
            # Only this application's read-only market tools.
            "--allowedTools",
            f"mcp__{MCP_SERVER_NAME}",
            "--disallowedTools",
            *DENIED_TOOLS,
            "--mcp-config",
            str(config),
            # Ignore every other MCP server on this machine.
            "--strict-mcp-config",
            "--max-turns",
            str(MAX_TURNS),
            # Each question stands alone; nothing carries between turns.
            "--no-session-persistence",
            prompt,
        ]

        # The CLI spawns the MCP server as its own child, which inherits
        # this environment. In a source checkout that server is started
        # as `python -m backend.main`, so the repository has to be
        # importable from whatever directory it happens to land in --
        # the `cwd` key in the MCP config is not honoured, and without
        # this the server dies on ModuleNotFoundError and every question
        # is answered with no tools at all.
        env = dict(os.environ)

        if not getattr(sys, "frozen", False):
            root = str(Path(__file__).resolve().parents[2])
            existing = env.get("PYTHONPATH")
            env["PYTHONPATH"] = (
                f"{root}{os.pathsep}{existing}" if existing else root
            )

        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CLI_TIMEOUT_SECONDS,
            shell=False,
            env=env,
            **_hidden(),
            # The CLI waits three seconds for piped input before giving
            # up, and inherits this process's stdin if we say nothing.
            # Closing it explicitly removes both the delay and the
            # warning it prints when the wait expires.
            stdin=subprocess.DEVNULL,
            # Somewhere with nothing of the user's in it. File tools are
            # already denied; this makes the denial redundant rather than
            # load-bearing.
            cwd=config.parent,
        )

        if result.returncode != 0:
            logger.error(
                "Claude Code CLI failed",
                extra={"context": {"returncode": result.returncode}},
            )
            raise RuntimeError(f"Claude Code exited {result.returncode}.")

        return _extract_text(result.stdout)


def _extract_text(stdout: str) -> str:
    """Pull the answer out of --output-format json.

    Falls back to the raw stream: a changed envelope should degrade to a
    slightly untidy answer, not to no answer at all.
    """
    stripped = stdout.strip()

    if not stripped:
        raise RuntimeError("Claude Code returned nothing.")

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        # The CLI can prepend a diagnostic line to the envelope. Retry
        # from the first brace so a warning never lands in the user's
        # answer; if that fails too, the raw text is still better than
        # nothing.
        brace = stripped.find("{")

        if brace == -1:
            return stripped

        try:
            payload = json.loads(stripped[brace:])
        except json.JSONDecodeError:
            return stripped

    if isinstance(payload, dict):
        if payload.get("is_error"):
            raise RuntimeError("Claude Code reported an error.")

        result = payload.get("result")

        if isinstance(result, str) and result.strip():
            return result.strip()

    return stripped


API = ApiProvider()
CLI = CliProvider()


def select_provider() -> ChatProvider:
    """Prefer the transport the user is already paying for.

    FORTRADER_CHAT_PROVIDER forces `cli` or `api`; the default tries the
    CLI first because it costs nothing per question.
    """
    forced = os.environ.get("FORTRADER_CHAT_PROVIDER", "auto").strip().lower()

    if forced == "cli":
        return CLI
    if forced == "api":
        return API

    return CLI if CLI.available()[0] else API
