"""Trade plan construction and the narrative layer's boundaries."""

from __future__ import annotations

import pytest

from backend.analysis.engine import Indicators
from backend.fortrade.models import Account, Quote, Timeframe
from backend.planning import narrative
from backend.planning.plan import (
    STOP_ATR,
    TARGET_ATR,
    TradePlan,
    Viability,
    build_plan,
)
from backend.signals.engine import Bias, Signal

ATR = 0.0010


def signal(
    bias: Bias = Bias.LONG,
    score: int = 80,
    atr: float | None = ATR,
    rsi: float | None = 55.0,
    bars: int = 500,
    reliable: bool = True,
    **components: int,
) -> Signal:
    return Signal(
        symbol="GBP/USD",
        timeframe=Timeframe.M5,
        bias=bias,
        score=score,
        trend_score=components.get("trend_score", 18),
        momentum_score=components.get("momentum_score", 16),
        structure_score=components.get("structure_score", 15),
        volatility_score=components.get("volatility_score", 15),
        timeframe_score=components.get("timeframe_score", 16),
        price=1.3500,
        bars_used=bars,
        reliable=reliable,
        indicators=Indicators(atr14=atr, rsi14=rsi),
        reasons=("EMA alignment supports the upside.",),
    )


def quote(sell: float = 1.3500, buy: float = 1.3501) -> Quote:
    return Quote(symbol="GBP/USD", sell=sell, buy=buy)


def account(equity: float = 10_000.0) -> Account:
    return Account(
        balance=equity,
        equity=equity,
        open_pnl=0.0,
        used_margin=0.0,
        available_margin=equity,
        currency="GBP",
    )


class TestViability:
    def test_wait_produces_no_levels(self) -> None:
        plan = build_plan(signal(bias=Bias.WAIT), quote(), account())

        assert plan.viability is Viability.NO_DIRECTION
        assert plan.viable is False
        assert plan.entry is None and plan.stop is None

    def test_no_atr_is_refused(self) -> None:
        plan = build_plan(signal(atr=None), quote(), account())

        assert plan.viability is Viability.NO_VOLATILITY_READING
        assert plan.viable is False

    def test_no_history_is_refused(self) -> None:
        plan = build_plan(signal(bars=0), quote(), account())

        assert plan.viability is Viability.INSUFFICIENT_HISTORY

    def test_stop_inside_the_spread_is_refused(self) -> None:
        # Observed live out of hours: a 124-point spread against a
        # 24-point stop. The position would open already past its stop.
        wide = Quote(symbol="GBP/USD", sell=1.35284, buy=1.35408)

        plan = build_plan(signal(atr=0.000161), wide, account())

        assert plan.viability is Viability.SPREAD_TOO_WIDE
        assert plan.viable is False
        assert plan.stop is None
        assert any("inside the spread" in w for w in plan.warnings)

    def test_a_clean_setup_is_tradeable(self) -> None:
        plan = build_plan(signal(), quote(), account())

        assert plan.viability is Viability.TRADEABLE
        assert plan.viable is True


class TestLevels:
    def test_long_enters_at_the_ask(self) -> None:
        plan = build_plan(signal(bias=Bias.LONG), quote(1.3500, 1.3501), account())

        assert plan.entry == pytest.approx(1.3501)

    def test_short_enters_at_the_bid(self) -> None:
        plan = build_plan(signal(bias=Bias.SHORT), quote(1.3500, 1.3501), account())

        assert plan.entry == pytest.approx(1.3500)

    def test_stop_and_target_follow_atr(self) -> None:
        plan = build_plan(signal(), quote(), account())

        assert plan.entry is not None and plan.stop is not None
        assert plan.entry - plan.stop == pytest.approx(ATR * STOP_ATR)
        assert plan.target - plan.entry == pytest.approx(ATR * TARGET_ATR)

    def test_short_inverts_the_levels(self) -> None:
        plan = build_plan(signal(bias=Bias.SHORT), quote(), account())

        assert plan.stop > plan.entry
        assert plan.target < plan.entry

    def test_reward_to_risk_is_reported(self) -> None:
        assert build_plan(signal(), quote(), account()).risk_reward == pytest.approx(
            2.0
        )

    def test_invalidation_is_the_stop(self) -> None:
        plan = build_plan(signal(), quote(), account())

        assert plan.invalidation == plan.stop


class TestSizing:
    def test_size_risks_exactly_the_budget(self) -> None:
        plan = build_plan(signal(), quote(), account(10_000), risk_percent=1.0)

        assert plan.risk_amount == pytest.approx(100.0)
        assert plan.size is not None and plan.stop is not None
        assert plan.size * abs(plan.entry - plan.stop) == pytest.approx(100.0, rel=1e-4)

    def test_risk_percent_scales_the_size(self) -> None:
        one = build_plan(signal(), quote(), account(), risk_percent=1.0)
        two = build_plan(signal(), quote(), account(), risk_percent=2.0)

        assert two.size == pytest.approx(one.size * 2)

    def test_no_account_means_no_size(self) -> None:
        # Levels are still computed; only the sizing arithmetic is absent.
        plan = build_plan(signal(), quote(), account=None)

        assert plan.viable is True
        assert plan.size is None and plan.risk_amount is None

    def test_sizing_is_labelled_as_arithmetic(self) -> None:
        plan = build_plan(signal(), quote(), account())

        assert any("not a recommendation" in w for w in plan.warnings)


class TestOpposingCase:
    def test_weak_components_are_listed_against(self) -> None:
        plan = build_plan(signal(trend_score=4, momentum_score=3), quote(), account())

        joined = " ".join(plan.opposing)

        assert "trend" in joined and "momentum" in joined

    def test_stretched_rsi_is_listed_against_a_long(self) -> None:
        plan = build_plan(signal(bias=Bias.LONG, rsi=82.0), quote(), account())

        assert any("stretched" in o for o in plan.opposing)

    def test_stretched_rsi_is_listed_against_a_short(self) -> None:
        plan = build_plan(signal(bias=Bias.SHORT, rsi=18.0), quote(), account())

        assert any("stretched" in o for o in plan.opposing)

    def test_provisional_history_is_listed_against(self) -> None:
        plan = build_plan(signal(bars=90, reliable=False), quote(), account())

        assert any("provisional" in o for o in plan.opposing)

    def test_expensive_spread_is_listed_against(self) -> None:
        # Spread over half an ATR but still outside the 2x stop guard.
        plan = build_plan(signal(atr=0.0010), quote(1.3500, 1.3506), account())

        assert any("ATR" in o for o in plan.opposing)

    def test_cautions_are_not_filed_as_supporting(self) -> None:
        # Observed live: "Compressed ranges leave little room to a target"
        # appeared under the supporting case. The engine emits all its
        # reasons into one list; a caution under a "for" heading reads as
        # endorsement of the trade.
        sig = signal().model_copy(
            update={
                "reasons": (
                    "EMA alignment is complete and supports the downside.",
                    "Compressed ranges leave little room to a target.",
                    "RSI is stretched in the direction of the move.",
                )
            }
        )

        plan = build_plan(sig, quote(), account())

        assert plan.supporting == (
            "EMA alignment is complete and supports the downside.",
        )
        assert any("little room" in o for o in plan.opposing)
        assert any("stretched" in o for o in plan.opposing)

    def test_opposing_entries_are_not_duplicated(self) -> None:
        plan = build_plan(signal(bias=Bias.LONG, rsi=82.0), quote(), account())

        assert len(plan.opposing) == len(set(plan.opposing))

    def test_a_clean_setup_has_nothing_against_it(self) -> None:
        assert build_plan(signal(), quote(), account()).opposing == ()


class TestEvidenceFraming:
    def test_evidence_states_the_record_is_absent(self) -> None:
        plan = build_plan(
            signal(),
            quote(),
            account(),
            paper_trades_closed=3,
            paper_trades_required=20,
        )

        assert "3 of 20" in plan.evidence
        assert "no measured record" in plan.evidence

    def test_score_is_never_framed_as_odds(self) -> None:
        plan = build_plan(signal(score=87), quote(), account())

        assert "agreement" in plan.evidence
        for word in ("probability", "chance", "likelihood", "win rate"):
            assert word not in plan.evidence.lower()

    def test_plan_carries_no_recommendation_field(self) -> None:
        # There is deliberately no "should I take this" answer.
        forbidden = {"recommendation", "advice", "prediction", "forecast"}

        assert not forbidden & set(TradePlan.model_fields)


class TestNarrativeBoundaries:
    def test_absent_key_is_a_normal_state(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        assert narrative.is_configured() is False
        assert narrative.explain(build_plan(signal(), quote(), account())) is None

    def test_system_prompt_forbids_forecasting(self) -> None:
        prompt = narrative.SYSTEM_PROMPT.lower()

        assert "never predict" in prompt
        assert "never invent" in prompt

    def test_system_prompt_forbids_recommending(self) -> None:
        assert (
            "never tell the reader to take the trade" in narrative.SYSTEM_PROMPT.lower()
        )

    def test_system_prompt_blocks_probability_framing(self) -> None:
        prompt = narrative.SYSTEM_PROMPT.lower()

        assert "not a probability" in prompt
        assert "calibrated" in prompt

    def test_system_prompt_requires_the_opposing_case(self) -> None:
        assert "opposing" in narrative.SYSTEM_PROMPT

    def test_rendered_plan_carries_no_invented_numbers(self) -> None:
        plan = build_plan(signal(), quote(), account())

        rendered = narrative._render_plan(plan)

        # Everything the model may cite must come from the plan itself.
        assert str(plan.entry) in rendered
        assert str(plan.stop) in rendered
        assert "NOT a probability" in rendered

    def test_uses_the_current_model(self) -> None:
        assert narrative.MODEL == "claude-opus-5"
