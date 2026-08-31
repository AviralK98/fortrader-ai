from __future__ import annotations

import pytest

from backend.fortrade.models import AccountType, DataSourceKind, Timeframe
from backend.fortrade.parser import (
    FortradeParseError,
    detect_account_type,
    detect_currency,
    find_quote,
    parse_account,
    parse_chart_selection,
    parse_number,
    parse_quotes,
    parse_visible_candle,
)


class TestParseNumber:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1.35284", 1.35284),
            ("£10,000.00", 10000.0),
            ("$1,234.56", 1234.56),
            ("€99.99", 99.99),
            ("-250.75", -250.75),
            ("  8,210.4  ", 8210.4),
            ("0.00", 0.0),
        ],
    )
    def test_parses_ui_formats(self, raw: str, expected: float) -> None:
        assert parse_number(raw) == pytest.approx(expected)

    def test_parenthesised_negative(self) -> None:
        assert parse_number("(1,234.50)") == pytest.approx(-1234.50)

    @pytest.mark.parametrize("raw", ["", "   ", "£", "n/a", "--"])
    def test_rejects_unparseable(self, raw: str) -> None:
        with pytest.raises(FortradeParseError):
            parse_number(raw)


class TestAccount:
    def test_parses_all_fields(self, page_text: str) -> None:
        account = parse_account(page_text)

        assert account.balance == pytest.approx(10000.0)
        assert account.equity == pytest.approx(10000.0)
        assert account.open_pnl == pytest.approx(0.0)
        assert account.used_margin == pytest.approx(0.0)
        assert account.available_margin == pytest.approx(10000.0)

    def test_currency_is_detected_not_hardcoded(self, page_text: str) -> None:
        assert detect_currency(page_text) == "GBP"
        assert detect_currency("Balance\n$5,000.00") == "USD"
        assert detect_currency("Balance\n€5.000,00".replace(",", "")) == "EUR"

    def test_currency_falls_back_when_absent(self) -> None:
        assert detect_currency("Balance\n5000.00") == "GBP"

    def test_demo_account_is_detected(self, page_text: str) -> None:
        assert detect_account_type(page_text) is AccountType.DEMO

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Account LIVE", AccountType.LIVE),
            ("REAL money account", AccountType.LIVE),
            ("nothing here", AccountType.UNKNOWN),
        ],
    )
    def test_account_type_variants(
        self, text: str, expected: AccountType
    ) -> None:
        assert detect_account_type(text) is expected

    def test_source_is_recorded(self, page_text: str) -> None:
        account = parse_account(page_text, DataSourceKind.FIXTURE)

        assert account.source is DataSourceKind.FIXTURE

    def test_missing_label_raises(self) -> None:
        with pytest.raises(FortradeParseError, match="Balance"):
            parse_account("no account panel here")


class TestQuotes:
    def test_parses_every_visible_quote(self, page_text: str) -> None:
        quotes = parse_quotes(page_text)

        symbols = {q.symbol for q in quotes}

        assert symbols == {"EUR/USD", "GBP/USD", "USD/JPY", "GOLD", "UK 100"}

    def test_bid_ask_and_derived_spread(self, page_text: str) -> None:
        quote = find_quote(parse_quotes(page_text), "GBP/USD")

        assert quote.sell == pytest.approx(1.35284)
        assert quote.buy == pytest.approx(1.35408)
        assert quote.spread == pytest.approx(0.00124)
        assert quote.spread_points == 124

    def test_mid_price(self, page_text: str) -> None:
        quote = find_quote(parse_quotes(page_text), "EUR/USD")

        assert quote.mid == pytest.approx((1.15811 + 1.15836) / 2)

    def test_change_percent_sign_is_kept(self, page_text: str) -> None:
        quotes = {q.symbol: q for q in parse_quotes(page_text)}

        assert quotes["GBP/USD"].change_percent == pytest.approx(-0.50)
        assert quotes["USD/JPY"].change_percent == pytest.approx(0.31)

    def test_quoted_at_is_parsed_as_day_first(self, page_text: str) -> None:
        quote = find_quote(parse_quotes(page_text), "GBP/USD")

        assert quote.quoted_at is not None
        assert (quote.quoted_at.day, quote.quoted_at.month) == (28, 8)

    def test_lookup_is_case_insensitive(self, page_text: str) -> None:
        quotes = parse_quotes(page_text)

        assert find_quote(quotes, "gbp/usd").symbol == "GBP/USD"

    def test_unknown_symbol_lists_alternatives(self, page_text: str) -> None:
        quotes = parse_quotes(page_text)

        with pytest.raises(FortradeParseError, match="available:"):
            find_quote(quotes, "AUD/CAD")

    def test_empty_page_yields_no_quotes(self) -> None:
        assert parse_quotes("") == []


class TestChart:
    def test_selection(self, page_text: str) -> None:
        chart = parse_chart_selection(page_text)

        assert chart.symbol == "GBP/USD"
        assert chart.timeframe is Timeframe.M1

    def test_visible_candle_ohlc(self, page_text: str) -> None:
        candle = parse_visible_candle(page_text)

        assert candle.open == pytest.approx(1.35300)
        assert candle.high == pytest.approx(1.35420)
        assert candle.low == pytest.approx(1.35280)
        assert candle.close == pytest.approx(1.35408)

    def test_visible_candle_is_marked_incomplete(self, page_text: str) -> None:
        # The bar on screen is still forming; treating it as closed would
        # bias any indicator computed over it.
        assert parse_visible_candle(page_text).complete is False

    def test_chart_timestamp_is_year_first(self, page_text: str) -> None:
        candle = parse_visible_candle(page_text)

        assert (candle.timestamp.year, candle.timestamp.month) == (2026, 8)

    def test_missing_chart_raises(self) -> None:
        with pytest.raises(FortradeParseError, match="chart panel"):
            parse_chart_selection("Balance\n£10,000.00")
