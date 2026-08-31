import re
from playwright.sync_api import sync_playwright


CDP_URL = "http://127.0.0.1:9222"


def _get_body_text() -> str:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)

        if not browser.contexts:
            raise RuntimeError("No Chrome context found")

        context = browser.contexts[0]

        page = None

        for candidate in context.pages:
            if "ready.fortrade.com" in candidate.url:
                page = candidate
                break

        if page is None:
            raise RuntimeError(
                "Fortrade tab not found. "
                "Start Chrome with remote debugging first."
            )

        return page.locator("body").inner_text(timeout=10000)


def _parse_number(value: str) -> float:
    value = value.strip()

    value = (
        value
        .replace("£", "")
        .replace("$", "")
        .replace("€", "")
        .replace(",", "")
    )

    return float(value)


def _extract_money(text: str, label: str) -> float:
    pattern = rf"{re.escape(label)}\s*\n([£$€]?[0-9,.-]+)"

    match = re.search(pattern, text)

    if not match:
        raise RuntimeError(
            f"Could not find '{label}' in Fortrade page"
        )

    return _parse_number(match.group(1))


def get_account() -> dict:
    text = _get_body_text()

    return {
        "balance": _extract_money(text, "Balance"),
        "open_pnl": _extract_money(text, "Open P&L"),
        "equity": _extract_money(text, "Equity"),
        "used_margin": _extract_money(text, "Used Margin"),
        "available_margin": _extract_money(
            text,
            "Available Margin",
        ),
        "currency": "GBP",
    }


QUOTE_PATTERN = re.compile(
    r"(?P<symbol>"
    r"[A-Z]{3}/[A-Z]{3}"
    r"|GOLD"
    r"|Crude Oil \(CL\)"
    r"|USA 500"
    r"|UK 100"
    r")\n"
    r"(?P<change>[+-]?\d+(?:\.\d+)?)%\n"
    r"(?P<timestamp>"
    r"\d{2}/\d{2}/\d{4} "
    r"\d{2}:\d{2}:\d{2}"
    r")\n"
    r"(?P<sell>[\d,.]+)\n"
    r"SELL\n"
    r"(?P<spread_points>\d+)\n"
    r"(?P<buy>[\d,.]+)\n"
    r"BUY"
)


def get_quotes() -> list[dict]:
    text = _get_body_text()

    quotes = []

    for match in QUOTE_PATTERN.finditer(text):
        quotes.append({
            "symbol": match.group("symbol"),
            "change_percent": float(
                match.group("change")
            ),
            "timestamp": match.group("timestamp"),
            "sell": _parse_number(
                match.group("sell")
            ),
            "buy": _parse_number(
                match.group("buy")
            ),
            "spread_points": int(
                match.group("spread_points")
            ),
        })

    return quotes


def get_quote(symbol: str) -> dict:
    symbol = symbol.upper()

    for quote in get_quotes():
        if quote["symbol"].upper() == symbol:
            quote["spread_price"] = round(
                quote["buy"] - quote["sell"],
                8,
            )

            return quote

    raise RuntimeError(
        f"Symbol '{symbol}' not found in Favourites"
    )


def get_visible_chart() -> dict:
    text = _get_body_text()

    pattern = re.compile(
        r"(?P<symbol>[A-Z]{3}/[A-Z]{3})\n"
        r"(?P<sell>[\d,.]+)\n"
        r"SELL\n"
        r"\d+\n"
        r"(?P<buy>[\d,.]+)\n"
        r"BUY.*?"
        r"\n(?P<timeframe>M1|M5|M15|M30|H1|H4|D1)\n"
        r"(?P<timestamp>\d{4}/\d{2}/\d{2} \d{2}:\d{2})"
        r".*?"
        r"Open:\s*\n(?P<open>[\d,.]+)"
        r".*?"
        r"High:\s*\n(?P<high>[\d,.]+)"
        r".*?"
        r"Low:\s*\n(?P<low>[\d,.]+)"
        r".*?"
        r"Close:\s*\n(?P<close>[\d,.]+)",
        re.DOTALL,
    )

    matches = list(pattern.finditer(text))

    if not matches:
        raise RuntimeError(
            "Could not parse visible Fortrade chart"
        )

    # Last matching block should normally be the chart,
    # rather than the favourites list.
    match = matches[-1]

    return {
        "symbol": match.group("symbol"),
        "timeframe": match.group("timeframe"),
        "timestamp": match.group("timestamp"),
        "sell": _parse_number(
            match.group("sell")
        ),
        "buy": _parse_number(
            match.group("buy")
        ),
        "candle": {
            "open": _parse_number(
                match.group("open")
            ),
            "high": _parse_number(
                match.group("high")
            ),
            "low": _parse_number(
                match.group("low")
            ),
            "close": _parse_number(
                match.group("close")
            ),
        },
    }