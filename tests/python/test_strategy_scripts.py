"""User-written strategy scripts.

These run real subprocesses, because the behaviour worth testing is what
happens when someone's script is wrong: the whole point of the design is
that a broken strategy costs one reading rather than the application.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from backend.strategies import scripts


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    return scripts.scripts_dir(tmp_path)


CANDLES = [{"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5}] * 5
INDICATORS = {"ema9": 1.36, "ema21": 1.35, "rsi14": 55.0}


def write(folder: Path, name: str, source: str) -> Path:
    path = folder / f"{name}.py"
    path.write_text(source, encoding="utf-8")

    return path


class TestFolder:
    def test_is_created_with_an_example_and_a_readme(
        self, tmp_path: Path
    ) -> None:
        folder = scripts.scripts_dir(tmp_path)

        assert (folder / "example_strategy.py").is_file()
        assert (folder / "README.txt").is_file()

    def test_the_example_is_a_working_strategy(self, folder: Path) -> None:
        # An example that does not run teaches the wrong thing.
        result = scripts.run(
            folder / "example_strategy.py", CANDLES, INDICATORS
        )

        assert result.error is None
        assert result.bias == "LONG"

    def test_discovery_lists_scripts_by_name(self, folder: Path) -> None:
        write(folder, "b_second", "def analyse(c, i): return {}")
        write(folder, "a_first", "def analyse(c, i): return {}")

        names = [p.name for p in scripts.discover(folder.parent)]

        assert names == ["a_first.py", "b_second.py", "example_strategy.py"]

    def test_private_and_cache_files_are_ignored(self, folder: Path) -> None:
        write(folder, "_helper", "x = 1")
        (folder / ".hidden.py").write_text("x = 1", encoding="utf-8")

        names = [p.name for p in scripts.discover(folder.parent)]

        assert "_helper.py" not in names
        assert ".hidden.py" not in names


class TestBrokenScriptsAreSurvivable:
    """Every one of these must produce a message, not an exception."""

    def test_an_exception_reports_the_authors_own_error(
        self, folder: Path
    ) -> None:
        path = write(
            folder, "boom", "def analyse(c, i):\n    raise ValueError('my bug')\n"
        )

        result = scripts.run(path, CANDLES, INDICATORS)

        assert result.error is not None
        assert "my bug" in result.error
        assert result.bias == "WAIT"

    def test_a_syntax_error_is_reported(self, folder: Path) -> None:
        path = write(folder, "bad_syntax", "def analyse(c, i)\n    return {}\n")

        result = scripts.run(path, CANDLES, INDICATORS)

        assert result.error is not None
        assert "SyntaxError" in result.error

    def test_a_missing_entry_point_is_named(self, folder: Path) -> None:
        path = write(folder, "no_entry", "x = 1\n")

        result = scripts.run(path, CANDLES, INDICATORS)

        assert result.error is not None
        assert scripts.ENTRY_POINT in result.error

    def test_a_non_dict_return_is_refused(self, folder: Path) -> None:
        path = write(folder, "wrong_type", "def analyse(c, i):\n    return 'no'\n")

        result = scripts.run(path, CANDLES, INDICATORS)

        assert result.error is not None

    def test_an_unknown_bias_is_refused(self, folder: Path) -> None:
        path = write(
            folder, "odd_bias", "def analyse(c, i):\n    return {'bias': 'MAYBE'}\n"
        )

        result = scripts.run(path, CANDLES, INDICATORS)

        assert result.error is not None
        assert "MAYBE" in result.error

    def test_a_hang_is_bounded_and_reported(self, folder: Path) -> None:
        # Without a timeout one bad loop would wedge the signal path for
        # as long as the application stayed open.
        path = write(
            folder, "hang", "def analyse(c, i):\n    while True:\n        pass\n"
        )

        started = time.time()
        result = scripts.run(path, CANDLES, INDICATORS)
        elapsed = time.time() - started

        assert result.error is not None
        assert "did not finish" in result.error
        assert elapsed < scripts.TIMEOUT_SECONDS + 10

    def test_a_script_that_exits_is_reported(self, folder: Path) -> None:
        path = write(
            folder,
            "quitter",
            "import sys\ndef analyse(c, i):\n    sys.exit(3)\n",
        )

        result = scripts.run(path, CANDLES, INDICATORS)

        assert result.error is not None


class TestResults:
    def test_a_valid_result_is_returned(self, folder: Path) -> None:
        path = write(
            folder,
            "good",
            "def analyse(c, i):\n"
            "    return {'bias': 'SHORT', 'score': 72, 'reasons': ['because']}\n",
        )

        result = scripts.run(path, CANDLES, INDICATORS)

        assert (result.bias, result.score, result.reasons) == (
            "SHORT",
            72,
            ("because",),
        )

    def test_an_out_of_range_score_is_clamped_not_rejected(
        self, folder: Path
    ) -> None:
        # An arithmetic slip should not throw away the bias with it.
        path = write(
            folder,
            "loud",
            "def analyse(c, i):\n    return {'bias': 'LONG', 'score': 5000}\n",
        )

        result = scripts.run(path, CANDLES, INDICATORS)

        assert result.error is None
        assert result.score == 100

    def test_printing_does_not_corrupt_the_result(self, folder: Path) -> None:
        # People debug with print(). It must not break their strategy.
        path = write(
            folder,
            "chatty",
            "def analyse(c, i):\n"
            "    print('debugging')\n"
            "    return {'bias': 'LONG', 'score': 60}\n",
        )

        result = scripts.run(path, CANDLES, INDICATORS)

        assert result.error is None
        assert result.bias == "LONG"

    def test_reasons_are_capped(self, folder: Path) -> None:
        path = write(
            folder,
            "verbose",
            "def analyse(c, i):\n"
            "    return {'bias': 'LONG', 'reasons': ['r'] * 100}\n",
        )

        result = scripts.run(path, CANDLES, INDICATORS)

        assert len(result.reasons) <= 8

    def test_the_script_receives_the_data_it_was_given(
        self, folder: Path
    ) -> None:
        path = write(
            folder,
            "echo",
            "def analyse(c, i):\n"
            "    return {'bias': 'LONG', 'score': len(c),\n"
            "            'reasons': [str(i.get('rsi14'))]}\n",
        )

        result = scripts.run(path, [{"close": 1.0}] * 7, {"rsi14": 42.0})

        assert result.score == 7
        assert result.reasons == ("42.0",)


class TestRunnerIsCheapToStart:
    def test_the_entry_point_does_not_import_the_http_server(self) -> None:
        """The runner is spawned once per signal.

        Importing backend.main used to pull in FastAPI, uvicorn and
        pandas -- about two seconds per run, on the path that produces a
        signal. Those imports now live inside main() and must stay there.
        """
        import ast

        source = (
            Path(__file__).resolve().parents[2] / "backend" / "main.py"
        ).read_text(encoding="utf-8")

        tree = ast.parse(source)

        top_level = {
            alias.name
            for node in tree.body
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module
            for node in tree.body
            if isinstance(node, ast.ImportFrom) and node.module
        }

        for heavy in ("uvicorn", "backend.api.server", "backend.config"):
            assert heavy not in top_level, f"{heavy} is imported at module scope"
