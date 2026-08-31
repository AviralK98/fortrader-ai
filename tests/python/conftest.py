from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture(scope="session")
def page_text() -> str:
    """A captured Fortrade page dump.

    The suite never touches the live site or a real account.
    """
    return (FIXTURES / "fortrade_page.txt").read_text(encoding="utf-8")
