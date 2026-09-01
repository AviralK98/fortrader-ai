"""The version is written in four places and must agree in all of them.

The release workflow compares the tag against desktop/package.json and
refuses to build on a mismatch, which is the last line of defence. This
is the earlier one: it fails on the commit that introduces the drift
rather than on the tag days later, and it also catches the halves that
the workflow never looks at -- the backend reports its own version over
/health, and a sidecar claiming a different version from the app around
it is a confusing thing to debug.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _json_version(relative: str) -> str:
    return str(json.loads((ROOT / relative).read_text(encoding="utf-8"))["version"])


def _regex_version(relative: str, pattern: str) -> str:
    text = (ROOT / relative).read_text(encoding="utf-8")

    # MULTILINE: these declarations are never on the first line.
    match = re.search(pattern, text, re.MULTILINE)

    assert match is not None, f"no version found in {relative}"

    return match.group(1)


def test_every_version_string_agrees() -> None:
    versions = {
        "package.json": _json_version("package.json"),
        "desktop/package.json": _json_version("desktop/package.json"),
        "pyproject.toml": _regex_version(
            "pyproject.toml", r'^version\s*=\s*"([^"]+)"'
        ),
        "backend/api/server.py": _regex_version(
            "backend/api/server.py", r'^VERSION\s*=\s*"([^"]+)"'
        ),
    }

    assert len(set(versions.values())) == 1, (
        "version strings disagree, so a tag can only match some of them: "
        f"{versions}"
    )
