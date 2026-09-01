"""Transport selection, and the lockdown on the Claude Code CLI.

A `claude` session is normally an agent holding a shell and a filesystem.
This application invokes it to describe a chart. The flags asserted here
are what keeps those two facts compatible, so a silent edit to them
should fail the build.

Nothing in this file spawns the real binary; the point is to check the
argv we construct, not Anthropic's CLI.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from backend.chat import providers, service


@pytest.fixture(autouse=True)
def _clear_probe_cache() -> Any:
    """The CLI probe is cached for the life of the process."""
    providers._cli_probe = None
    yield
    providers._cli_probe = None


class Recorder:
    """Stands in for a transport and remembers what it was handed."""

    name = "recorder"

    def __init__(self, reply: str = "an answer") -> None:
        self.reply = reply
        self.system: str | None = None
        self.prompt: str | None = None

    def available(self) -> tuple[bool, str | None]:
        return (True, None)

    def complete(self, system: str, prompt: str) -> str:
        self.system = system
        self.prompt = prompt

        return self.reply


class TestGuardrailsSitAboveTheTransport:
    """Whichever transport runs, the rules are applied before it."""

    def test_system_prompt_reaches_every_provider(self) -> None:
        recorder = Recorder()

        service.ask("What is the signal?", [], "CTX", [], provider=recorder)

        assert recorder.system == service.SYSTEM_PROMPT

    def test_oversized_message_never_reaches_the_transport(self) -> None:
        recorder = Recorder()

        reply = service.ask("x" * 5000, [], "CTX", [], provider=recorder)

        assert reply.available is False
        assert recorder.prompt is None, "the transport was called anyway"

    def test_empty_message_never_reaches_the_transport(self) -> None:
        recorder = Recorder()

        service.ask("   ", [], "CTX", [], provider=recorder)

        assert recorder.prompt is None

    def test_history_is_capped_before_the_transport(self) -> None:
        recorder = Recorder()
        history = [
            service.ChatMessage(role="user", content=f"turn {i}")
            for i in range(40)
        ]

        service.ask("now", history, "CTX", [], provider=recorder)

        assert recorder.prompt is not None
        assert "turn 39" in recorder.prompt
        assert "turn 0" not in recorder.prompt

    def test_live_context_is_always_included(self) -> None:
        recorder = Recorder()

        service.ask("hi", [], "EQUITY 9950", [], provider=recorder)

        assert recorder.prompt is not None
        assert "EQUITY 9950" in recorder.prompt

    def test_transport_failure_is_reported_not_raised(self) -> None:
        class Broken(Recorder):
            def complete(self, system: str, prompt: str) -> str:
                raise RuntimeError("boom")

        reply = service.ask("hi", [], "CTX", [], provider=Broken())

        assert reply.available is False
        assert "boom" not in (reply.detail or ""), "internals leaked to the UI"

    def test_reply_names_the_transport_used(self) -> None:
        reply = service.ask("hi", [], "CTX", [], provider=Recorder())

        assert reply.provider == "recorder"


class TestCliLockdown:
    """The flags that stop a chat box from being an agent."""

    def argv(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        captured: dict[str, Any] = {}

        def fake_run(argv: list[str], **kwargs: Any) -> Any:
            captured["argv"] = argv
            captured["kwargs"] = kwargs

            return subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps({"result": "ok"}), stderr=""
            )

        monkeypatch.setattr(providers.shutil, "which", lambda _: "/usr/bin/claude")
        monkeypatch.setattr(providers.subprocess, "run", fake_run)

        providers.CLI.complete("SYSTEM RULES", "the question")

        self.kwargs = captured["kwargs"]

        return list(captured["argv"])

    def test_runs_non_interactively(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert "-p" in self.argv(monkeypatch)

    def test_every_shell_and_file_tool_is_denied(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        argv = self.argv(monkeypatch)

        assert "--disallowedTools" in argv

        for tool in ("Bash", "Write", "Edit", "Read", "WebFetch", "Task"):
            assert tool in argv, f"{tool} is reachable"

    def test_only_this_applications_mcp_tools_are_allowed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        argv = self.argv(monkeypatch)

        allowed = argv[argv.index("--allowedTools") + 1]

        assert allowed == f"mcp__{providers.MCP_SERVER_NAME}"

    def test_other_mcp_servers_are_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Without this a friend's unrelated MCP servers would load into a
        # session this application is responsible for.
        assert "--strict-mcp-config" in self.argv(monkeypatch)

    def test_nothing_persists_between_questions(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert "--no-session-persistence" in self.argv(monkeypatch)

    def test_the_agent_loop_is_bounded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        argv = self.argv(monkeypatch)

        assert int(argv[argv.index("--max-turns") + 1]) <= 10

    def test_our_rules_are_appended_to_the_system_prompt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        argv = self.argv(monkeypatch)

        assert argv[argv.index("--append-system-prompt") + 1] == "SYSTEM RULES"

    def test_never_runs_through_a_shell(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The question is user text. Through a shell it would be a command.
        self.argv(monkeypatch)

        assert self.kwargs["shell"] is False

    def test_the_question_is_one_argument_not_interpolated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        argv = self.argv(monkeypatch)

        assert argv.count("the question") == 1

    def test_a_question_cannot_pose_as_a_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # build_prompt puts the live context first, so the positional
        # argument never begins with a dash whatever the user types.
        prompt = service.build_prompt(
            "--dangerously-skip-permissions", [], "CTX"
        )

        assert not prompt.startswith("-")

    def test_stdin_is_closed_not_inherited(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Observed against the real CLI: it waits three seconds for piped
        # input, then warns. Inheriting the backend's stdin also risks a
        # wait that never ends.
        self.argv(monkeypatch)

        assert self.kwargs["stdin"] is subprocess.DEVNULL

    def test_the_mcp_server_stays_importable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The market tools are the entire point of using the CLI.

        The CLI runs the MCP server as its own child, in a working
        directory of its choosing, and ignores the `cwd` in the MCP
        config. Without the repository on PYTHONPATH the server exits on
        ModuleNotFoundError and every question is answered with no tools
        -- silently, because a missing server reads as an empty toolset
        rather than as an error.
        """
        self.argv(monkeypatch)

        root = str(Path(providers.__file__).resolve().parents[2])

        assert root in self.kwargs["env"]["PYTHONPATH"]

    @pytest.mark.skipif(
        not hasattr(subprocess, "CREATE_NO_WINDOW"),
        reason="CREATE_NO_WINDOW exists only on Windows",
    )
    def test_no_console_window_is_opened(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # `claude` is a console program. Without this a black window
        # appears over the chart for the whole of every answer.
        #
        # Windows-only in both directions: the flag is what suppresses
        # the window, and the constant naming it does not exist on other
        # platforms -- so forcing the branch there raises rather than
        # proving anything.
        monkeypatch.setattr(providers.sys, "platform", "win32")

        self.argv(monkeypatch)

        assert self.kwargs["creationflags"] == subprocess.CREATE_NO_WINDOW

    def test_other_platforms_spawn_without_the_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The counterpart that does run everywhere: no console window
        # problem exists off Windows, so no flag should be passed.
        monkeypatch.setattr(providers.sys, "platform", "darwin")

        self.argv(monkeypatch)

        assert "creationflags" not in self.kwargs

    def test_a_wedged_process_cannot_hang_the_request(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self.argv(monkeypatch)

        assert 0 < self.kwargs["timeout"] <= 300

    def test_a_nonzero_exit_is_an_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(providers.shutil, "which", lambda _: "/usr/bin/claude")
        monkeypatch.setattr(
            providers.subprocess,
            "run",
            lambda argv, **kw: subprocess.CompletedProcess(argv, 1, "", "nope"),
        )

        with pytest.raises(RuntimeError):
            providers.CLI.complete("S", "q")


class TestCliOutputParsing:
    def test_reads_the_json_envelope(self) -> None:
        payload = json.dumps({"type": "result", "result": "  the answer  "})

        assert providers._extract_text(payload) == "the answer"

    def test_falls_back_to_raw_text(self) -> None:
        # A changed envelope should cost tidiness, not the answer.
        assert providers._extract_text("plain output") == "plain output"

    def test_a_warning_line_never_reaches_the_answer(self) -> None:
        # The CLI prepends diagnostics to the envelope under some stdin
        # conditions. The user must not read them as part of the reply.
        noisy = (
            "Warning: no stdin data received in 3s, proceeding without it.\n"
            + json.dumps({"result": "the real answer"})
        )

        assert providers._extract_text(noisy) == "the real answer"

    def test_an_error_envelope_raises(self) -> None:
        with pytest.raises(RuntimeError):
            providers._extract_text(json.dumps({"is_error": True, "result": "x"}))

    def test_empty_output_raises(self) -> None:
        with pytest.raises(RuntimeError):
            providers._extract_text("   ")


class TestSelection:
    def test_prefers_the_cli_so_no_key_is_needed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FORTRADER_CHAT_PROVIDER", raising=False)
        monkeypatch.setattr(providers.CLI, "available", lambda: (True, None))

        assert providers.select_provider() is providers.CLI

    def test_falls_back_to_the_api_when_no_cli(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FORTRADER_CHAT_PROVIDER", raising=False)
        monkeypatch.setattr(providers.CLI, "available", lambda: (False, "absent"))

        assert providers.select_provider() is providers.API

    def test_can_be_forced(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FORTRADER_CHAT_PROVIDER", "api")
        assert providers.select_provider() is providers.API

        monkeypatch.setenv("FORTRADER_CHAT_PROVIDER", "cli")
        assert providers.select_provider() is providers.CLI

    def test_missing_cli_is_reported_plainly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(providers.shutil, "which", lambda _: None)

        usable, detail = providers.CLI.available()

        assert usable is False
        assert "not installed" in (detail or "")

    def test_an_absent_cli_is_rechecked_not_cached(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Installing Claude Code while the app is open should take effect
        # without a restart.
        monkeypatch.setattr(providers.shutil, "which", lambda _: None)
        assert providers.CLI.available()[0] is False

        monkeypatch.setattr(providers.shutil, "which", lambda _: "/usr/bin/claude")
        monkeypatch.setattr(
            providers.subprocess,
            "run",
            lambda argv, **kw: subprocess.CompletedProcess(argv, 0, "", ""),
        )

        assert providers.CLI.available()[0] is True

    def test_a_broken_install_is_cached(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Re-probing a binary that exists but fails costs a process spawn
        # per question, so that answer is remembered.
        calls: list[int] = []

        def fake_run(argv: list[str], **kw: Any) -> Any:
            calls.append(1)
            return subprocess.CompletedProcess(argv, 1, "", "")

        monkeypatch.setattr(providers.shutil, "which", lambda _: "/usr/bin/claude")
        monkeypatch.setattr(providers.subprocess, "run", fake_run)

        providers.CLI.available()
        providers.CLI.available()

        assert len(calls) == 1

    def test_neither_transport_explains_both_options(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        reply = service.ask("hi", [], "CTX", [], provider=providers.API)

        assert "Claude Code" in (reply.detail or "")
        assert "ANTHROPIC_API_KEY" in (reply.detail or "")


class TestMcpConfig:
    def test_names_only_this_applications_server(self) -> None:
        config = json.loads(
            providers._mcp_config_path().read_text(encoding="utf-8")
        )

        assert list(config["mcpServers"]) == [providers.MCP_SERVER_NAME]

    def test_the_server_runs_this_backend_in_mcp_mode(self) -> None:
        config = json.loads(
            providers._mcp_config_path().read_text(encoding="utf-8")
        )

        assert "--mcp" in config["mcpServers"][providers.MCP_SERVER_NAME]["args"]
