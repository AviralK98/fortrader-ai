"""User-written Python analysis scripts.

A script replaces the decision half of the engine. It receives the bars
and the indicators this application has already computed, and returns a
bias, a score and its reasons. It does not have to reimplement EMA, RSI
or ATR, and it cannot change how those are measured -- only what is
concluded from them.

**This runs code the user supplied.** That is the point, and it is not
something a sandbox makes safe: Python has no reliable in-process
sandbox, and every published attempt at one has been escaped. The
protections here are therefore about accidents, not adversaries:

* Scripts run in a **separate process**, so an infinite loop or a crash
  costs one signal instead of the backend.
* Every run has a **timeout**.
* Anything a script raises is reported as a warning on the signal, so a
  broken script degrades to WAIT rather than to a dead panel.
* Scripts are only ever loaded from one folder the user owns, never
  from a URL, an archive or anywhere the application writes.

What that does NOT protect against is a script that was written to do
harm. A strategy file is an ordinary Python program: it can read your
files and your Fortrade session and talk to the network. Run scripts you
wrote. A script from someone else deserves the same suspicion as any
program they emailed you.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.logging_setup import get_logger

logger = get_logger(__name__)

#: Folder inside the user's data directory. Nothing else is searched.
SCRIPTS_DIRNAME = "strategies"

#: The function a script must define.
ENTRY_POINT = "analyse"

#: A strategy that has not decided in this long is not going to.
TIMEOUT_SECONDS = 15

#: Bars handed to a script. Enough for a 200-period average with room.
MAX_CANDLES = 1000

VALID_BIASES = ("LONG", "SHORT", "WAIT")

EXAMPLE_SCRIPT = '''"""Example strategy. Copy this file and edit it.

`analyse` is called with two arguments and must return a dict.

    candles     list of bars, oldest first. Each is a dict with
                open, high, low, close, volume and time.
    indicators  what the application already measured for this series:
                ema9, ema21, ema50, ema200, rsi14, atr14, macd,
                macd_signal, macd_histogram, support, resistance.
                Any of them may be None when there is not enough history.

Return a dict with:

    bias     "LONG", "SHORT" or "WAIT"
    score    0-100, how strongly your rules agree. NOT a probability:
             nothing here has been calibrated against outcomes.
    reasons  list of short strings explaining the call

Anything you raise is caught and shown as a warning on the signal, so a
mistake here costs one reading rather than breaking the application.
"""


def analyse(candles, indicators):
    ema9 = indicators.get("ema9")
    ema21 = indicators.get("ema21")
    rsi = indicators.get("rsi14")

    if ema9 is None or ema21 is None or rsi is None:
        return {
            "bias": "WAIT",
            "score": 50,
            "reasons": ["Not enough history to measure anything."],
        }

    reasons = [f"EMA9 {ema9:.5f} against EMA21 {ema21:.5f}.", f"RSI {rsi:.1f}."]

    if ema9 > ema21 and rsi < 70:
        return {"bias": "LONG", "score": 65, "reasons": reasons}

    if ema9 < ema21 and rsi > 30:
        return {"bias": "SHORT", "score": 65, "reasons": reasons}

    return {
        "bias": "WAIT",
        "score": 50,
        "reasons": [*reasons, "Neither side is clear."],
    }
'''

README = """Strategy scripts
================

Every .py file here that defines `analyse` appears in the app as a
strategy you can select.

Start by copying example_strategy.py. The contract is documented at the
top of it.

These are ordinary Python programs and they run on your machine with
your permissions. Write your own, and treat a file from someone else the
way you would treat any program they sent you.

Changing the numbers is not the same as improving them. Run a backtest
before believing a change helped -- the app can measure a strategy, and
an untested idea that feels right is still untested.
"""


@dataclass(frozen=True)
class ScriptResult:
    """What a script concluded, or why it could not."""

    bias: str = "WAIT"
    score: int = 50
    reasons: tuple[str, ...] = ()
    error: str | None = None


def scripts_dir(data_dir: Path) -> Path:
    """The scripts folder, created with its example on first use."""
    folder = data_dir / SCRIPTS_DIRNAME

    if not folder.exists():
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "example_strategy.py").write_text(
            EXAMPLE_SCRIPT, encoding="utf-8"
        )
        (folder / "README.txt").write_text(README, encoding="utf-8")

        logger.info("Created strategy scripts folder", extra={"context": {}})

    return folder


def discover(data_dir: Path) -> list[Path]:
    """Every .py file in the scripts folder, by name.

    Not recursive, and dotfiles and __pycache__ are skipped: the folder is
    a flat list of strategies, not a package to be crawled.
    """
    folder = scripts_dir(data_dir)

    return sorted(
        path
        for path in folder.glob("*.py")
        if path.is_file() and not path.name.startswith((".", "_"))
    )


def _child_command(script: Path) -> list[str]:
    """How to launch the runner.

    In a packaged build `sys.executable` is the sidecar, not a Python
    interpreter, so the runner is a mode of this same executable — the
    arrangement `--mcp` already uses.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, "--run-strategy", str(script)]

    return [sys.executable, "-m", "backend.main", "--run-strategy", str(script)]


def run(
    script: Path,
    candles: list[dict[str, Any]],
    indicators: dict[str, Any],
) -> ScriptResult:
    """Execute one script and return what it decided.

    Never raises. A script that crashes, hangs, or returns nonsense
    produces a WAIT with the reason attached, because a broken strategy
    should cost one reading rather than the panel it feeds.
    """
    payload = json.dumps(
        {"candles": candles[-MAX_CANDLES:], "indicators": indicators}
    )

    try:
        completed = subprocess.run(
            _child_command(script),
            input=payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_SECONDS,
            shell=False,
            **_hidden(),
        )
    except subprocess.TimeoutExpired:
        return ScriptResult(
            error=f"{script.name} did not finish within {TIMEOUT_SECONDS}s."
        )
    except OSError as error:
        return ScriptResult(error=f"{script.name} could not be run: {error}")

    if completed.returncode != 0:
        # The child prints the script's own traceback last, which is the
        # part the author needs; a return code is not actionable.
        detail = (completed.stderr or "").strip().splitlines()
        tail = detail[-1] if detail else f"exited {completed.returncode}"

        return ScriptResult(error=f"{script.name}: {tail}")

    return _parse(script, completed.stdout)


def _hidden() -> dict[str, Any]:
    """Spawn without a console window on Windows."""
    flag = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    if sys.platform == "win32" and flag:
        return {"creationflags": flag}

    return {}


def _parse(script: Path, stdout: str) -> ScriptResult:
    """Read the child's reply, refusing anything malformed."""
    text = stdout.strip()

    if not text:
        return ScriptResult(error=f"{script.name} returned nothing.")

    try:
        payload = json.loads(text.splitlines()[-1])
    except json.JSONDecodeError:
        return ScriptResult(error=f"{script.name} did not return a result.")

    if not isinstance(payload, dict):
        return ScriptResult(error=f"{script.name} did not return a dictionary.")

    if payload.get("error"):
        return ScriptResult(error=f"{script.name}: {payload['error']}")

    bias = str(payload.get("bias", "WAIT")).upper()

    if bias not in VALID_BIASES:
        return ScriptResult(
            error=f"{script.name} returned bias {bias!r}; expected one of "
            f"{', '.join(VALID_BIASES)}."
        )

    try:
        score = int(payload.get("score", 50))
    except (TypeError, ValueError):
        return ScriptResult(error=f"{script.name} returned a non-numeric score.")

    # Clamped rather than rejected: a score outside the range is a
    # arithmetic slip, and the bias is still worth having.
    score = max(0, min(100, score))

    raw_reasons = payload.get("reasons") or []
    reasons = (
        tuple(str(r)[:200] for r in raw_reasons[:8])
        if isinstance(raw_reasons, list)
        else ()
    )

    return ScriptResult(bias=bias, score=score, reasons=reasons)


def run_child(script_path: str) -> int:
    """Runner entry point: read stdin, call the script, print JSON.

    Runs in its own process. The script is imported here and nowhere
    else, so nothing it does at import time touches the backend.
    """
    import importlib.util
    import traceback

    try:
        request = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError) as error:
        print(json.dumps({"error": f"bad input: {error}"}))
        return 0

    try:
        path = Path(script_path)
        spec = importlib.util.spec_from_file_location("user_strategy", path)

        if spec is None or spec.loader is None:
            print(json.dumps({"error": "could not be loaded"}))
            return 0

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        entry = getattr(module, ENTRY_POINT, None)

        if entry is None or not callable(entry):
            print(
                json.dumps(
                    {"error": f"does not define a function called {ENTRY_POINT}"}
                )
            )
            return 0

        result = entry(request.get("candles", []), request.get("indicators", {}))

        if not isinstance(result, dict):
            print(json.dumps({"error": f"{ENTRY_POINT} did not return a dict"}))
            return 0

        print(json.dumps(result, default=str))

    except Exception:
        # The author's own traceback is the useful part; the last line of
        # it is what the application shows them.
        traceback.print_exc(file=sys.stderr)

        lines = traceback.format_exc().strip().splitlines()
        print(json.dumps({"error": lines[-1] if lines else "raised an error"}))

    return 0
