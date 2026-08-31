"""Cross-platform path resolution.

These run on any host by faking `sys.platform`, so the macOS and Linux
branches are exercised from a Windows machine — the code cannot be built
there, but it can be checked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend import config
from mcp_bridge import client


class TestDataDirectory:
    def test_windows_uses_local_app_data(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(config.sys, "platform", "win32")
        monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\x\AppData\Local")

        assert config._default_data_dir() == Path(
            r"C:\Users\x\AppData\Local"
        ) / config.APP_NAME

    def test_macos_uses_application_support(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(config.sys, "platform", "darwin")

        result = config._default_data_dir()

        assert result.parts[-3:] == (
            "Library",
            "Application Support",
            config.APP_NAME,
        )

    def test_linux_uses_a_dotfile(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config.sys, "platform", "linux")

        assert config._default_data_dir().name == f".{config.APP_NAME.lower()}"

    def test_windows_without_localappdata_still_resolves(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A service account may have no LOCALAPPDATA; it must not crash.
        monkeypatch.setattr(config.sys, "platform", "win32")
        monkeypatch.delenv("LOCALAPPDATA", raising=False)

        assert config._default_data_dir().name == f".{config.APP_NAME.lower()}"


class TestRuntimeDiscovery:
    def test_macos_looks_under_application_support(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(client.sys, "platform", "darwin")

        candidates = client._runtime_file_candidates()

        assert candidates
        assert all("Application Support" in str(p) for p in candidates)
        assert all(p.name == "runtime.json" for p in candidates)

    def test_windows_checks_both_appdata_roots(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(client.sys, "platform", "win32")
        monkeypatch.setenv("APPDATA", r"C:\Users\x\AppData\Roaming")
        monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\x\AppData\Local")

        joined = " ".join(str(p) for p in client._runtime_file_candidates())

        # Electron's userData lives under Roaming; earlier builds used
        # Local. Both are checked so an upgrade does not lose the app.
        assert "Roaming" in joined
        assert "Local" in joined

    def test_every_platform_covers_the_electron_package_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for platform in ("win32", "darwin", "linux"):
            monkeypatch.setattr(client.sys, "platform", platform)
            monkeypatch.setenv("APPDATA", "/tmp/roaming")
            monkeypatch.setenv("LOCALAPPDATA", "/tmp/local")

            joined = " ".join(str(p) for p in client._runtime_file_candidates())

            assert "fortrader-ai-desktop" in joined, platform

    def test_missing_files_yield_no_url(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(client.sys, "platform", "darwin")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

        assert client._discover_base_url() is None

    def test_reads_the_first_runtime_file_found(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(client.sys, "platform", "darwin")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

        target = (
            tmp_path
            / "Library"
            / "Application Support"
            / "fortrader-ai-desktop"
            / "data"
        )
        target.mkdir(parents=True)
        (target / "runtime.json").write_text(
            '{"url": "http://127.0.0.1:9001"}', encoding="utf-8"
        )

        assert client._discover_base_url() == "http://127.0.0.1:9001"


def test_sidecar_name_matches_the_desktop_constant() -> None:
    """The TypeScript side must agree on the executable name.

    A mismatch would only surface when a packaged build fails to start
    its backend, which is the worst place to find out.
    """
    source = Path("desktop/main/backend-process.ts").read_text(encoding="utf-8")

    assert "'fortrader-backend.exe'" in source
    assert "'fortrader-backend'" in source
    assert "process.platform === 'win32'" in source
