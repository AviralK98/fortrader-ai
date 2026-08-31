"""Parsers turning raw Fortrade UI text into normalised models.

Ported from the Playwright proof of concept in `legacy/prototypes/`, with
three changes that make it testable and safer:

1. These are pure functions over text. They perform no I/O, so the whole
   suite runs against fixtures without a Fortrade account.
2. Currency is parsed from the rendered symbol rather than hardcoded.
3. Failures raise `FortradeParseError` instead of bare `RuntimeError`.

This text-level parsing is the *discovery* path. It is deliberately behind
`FortradeDataSource` so that a structured network-observation provider can
replace it without touching anything downstream.
"""

from __future__ import annotations

import re
from datetime import datetime

from backend.fortrade.models import (
    Account,
    AccountType,
    Candle,
    ChartSelection,
    DataSourceKind,
    Quote,
    Timeframe,
)


class FortradeParseError(ValueError):
    """Raised when expected information is absent from the rendered page."""


CURRENCY_SYMBOLS = {
    "£": "GBP",
    "$": "USD",
    "€": "EUR",
    "¥": "JPY",
}

_NUMBER_CLEAN = re.compile(r"[£$€¥,\s]")


def parse_number(value: str) -> float:
    """Parse a UI-rendered number, tolerating currency symbols and commas."""
    cleaned = _NUMBER_CLEAN.sub("", value.strip())

    # Fortrade renders negatives as (1.23) in some locales.
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]

    if not cleaned:
        raise FortradeParseError(f"Empty numeric value in {value!r}")

    try:
        return float(cleaned)
    except ValueError as exc:
        raise FortradeParseError(
            f"Could not parse number from {value!r}"
        ) from exc


def detect_currency(text: str) -> str:
    """Infer account currency from the symbol used on the Balance figure."""
    match = re.search(r"Balance\s*\n\s*([£$€¥])", text)

    if match:
        return CURRENCY_SYMBOLS.get(match.group(1), "GBP")

    for symbol, code in CURRENCY_SYMBOLS.items():
        if symbol in text:
            return code

    return "GBP"


def detect_account_type(text: str) -> AccountType:
    """Identify DEMO vs LIVE from the account chip Fortrade renders."""
    if re.search(r"\bDEMO\b", text, re.IGNORECASE):
        return AccountType.DEMO

    if re.search(r"\b(LIVE|REAL)\b", text, re.IGNORECASE):
        return AccountType.LIVE

    return AccountType.UNKNOWN


def _extract_money(text: str, label: str) -> float:
    pattern = rf"{re.escape(label)}\s*\n\s*(\(?-?[£$€¥]?[0-9,.]+\)?)"

    match = re.search(pattern, text)

    if not match:
        raise FortradeParseError(f"Could not find {label!r} in Fortrade page")

    return parse_number(match.group(1))


def parse_account(
    text: str,
    source: DataSourceKind = DataSourceKind.DOM,
) -> Account:
    """Extract the account summary strip."""
    return Account(
        balance=_extract_money(text, "Balance"),
        open_pnl=_extract_money(text, "Open P&L"),
        equity=_extract_money(text, "Equity"),
        used_margin=_extract_money(text, "Used Margin"),
        available_margin=_extract_money(text, "Available Margin"),
        currency=detect_currency(text),
        account_type=detect_account_type(text),
        source=source,
    )


# Instrument names seen in the watchlist. Forex pairs match structurally;
# the rest are named because they contain spaces and punctuation.
_INSTRUMENT = (
    r"[A-Z]{3}/[A-Z]{3}"
    r"|GOLD|SILVER"
    r"|Crude Oil \(CL\)"
    r"|USA 500|USA 30|USA 100"
    r"|UK 100|GER 40|FRA 40|JPN 225"
)

QUOTE_PATTERN = re.compile(
    rf"(?P<symbol>{_INSTRUMENT})\n"
    r"(?P<change>[+-]?\d+(?:\.\d+)?)%\n"
    r"(?P<timestamp>\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2})\n"
    r"(?P<sell>[\d,.]+)\n"
    r"SELL\n"
    r"(?P<spread_points>\d+)\n"
    r"(?P<buy>[\d,.]+)\n"
    r"BUY"
)

_UI_TIMESTAMP = "%d/%m/%Y %H:%M:%S"


def _parse_ui_timestamp(raw: str) -> datetime | None:
    try:
        return datetime.strptime(raw, _UI_TIMESTAMP)
    except ValueError:
        return None


def parse_quotes(
    text: str,
    source: DataSourceKind = DataSourceKind.DOM,
) -> list[Quote]:
    """Extract every quote rendered in the watchlist."""
    quotes: list[Quote] = []

    for match in QUOTE_PATTERN.finditer(text):
        quotes.append(
            Quote(
                symbol=match.group("symbol"),
                change_percent=float(match.group("change")),
                quoted_at=_parse_ui_timestamp(match.group("timestamp")),
                sell=parse_number(match.group("sell")),
                buy=parse_number(match.group("buy")),
                spread_points=int(match.group("spread_points")),
                source=source,
            )
        )

    return quotes


def find_quote(quotes: list[Quote], symbol: str) -> Quote:
    """Case-insensitive lookup, raising if the symbol is not on screen."""
    wanted = symbol.strip().upper()

    for quote in quotes:
        if quote.symbol.upper() == wanted:
            return quote

    available = ", ".join(sorted(q.symbol for q in quotes)) or "none"

    raise FortradeParseError(
        f"Symbol {symbol!r} is not in the visible watchlist "
        f"(available: {available})"
    )


CHART_PATTERN = re.compile(
    r"(?P<symbol>[A-Z]{3}/[A-Z]{3})\n"
    r"(?P<sell>[\d,.]+)\n"
    r"SELL\n"
    r"\d+\n"
    r"(?P<buy>[\d,.]+)\n"
    r"BUY.*?"
    r"\n(?P<timeframe>M1|M5|M15|M30|H1|H4|D1)\n"
    r"(?P<timestamp>\d{4}/\d{2}/\d{2} \d{2}:\d{2})"
    r".*?Open:\s*\n(?P<open>[\d,.]+)"
    r".*?High:\s*\n(?P<high>[\d,.]+)"
    r".*?Low:\s*\n(?P<low>[\d,.]+)"
    r".*?Close:\s*\n(?P<close>[\d,.]+)",
    re.DOTALL,
)

_CHART_TIMESTAMP = "%Y/%m/%d %H:%M"


def parse_chart_selection(
    text: str,
    source: DataSourceKind = DataSourceKind.DOM,
) -> ChartSelection:
    """Identify the instrument and timeframe currently on the chart."""
    matches = list(CHART_PATTERN.finditer(text))

    if not matches:
        raise FortradeParseError("Could not locate the chart panel")

    # The watchlist renders the same shape earlier in the document, so the
    # final match is the chart. This ordering assumption is why this path
    # is discovery-only; the network provider in Phase D removes it.
    match = matches[-1]

    return ChartSelection(
        symbol=match.group("symbol"),
        timeframe=Timeframe(match.group("timeframe")),
        source=source,
    )


def parse_visible_candle(
    text: str,
    source: DataSourceKind = DataSourceKind.DOM,
) -> Candle:
    """Extract the single OHLC bar the chart legend is describing.

    This yields exactly one bar. It is not a substitute for a real candle
    history — see `CandleProvider` for that.
    """
    matches = list(CHART_PATTERN.finditer(text))

    if not matches:
        raise FortradeParseError("Could not locate the chart panel")

    match = matches[-1]

    timestamp = datetime.strptime(match.group("timestamp"), _CHART_TIMESTAMP)

    return Candle(
        symbol=match.group("symbol"),
        timeframe=Timeframe(match.group("timeframe")),
        timestamp=timestamp,
        open=parse_number(match.group("open")),
        high=parse_number(match.group("high")),
        low=parse_number(match.group("low")),
        close=parse_number(match.group("close")),
        complete=False,
        source=source,
    )
