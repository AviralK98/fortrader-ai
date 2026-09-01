"""Optional plain-language narrative over a deterministic trade plan.

This is the "explanation layer" and nothing more. The model is given a
plan that is already fully computed and asked to describe it. It never
chooses a direction, never produces a price, and is told in the system
prompt that it cannot forecast — because it cannot. A language model has
no information about future prices, and text that sounds like a forecast
is more persuasive than it is informative.

Entirely optional: with no API key configured the application behaves
exactly as before, and every caller must handle `None`.
"""

from __future__ import annotations

import os

from backend.logging_setup import get_logger
from backend.planning.plan import TradePlan

logger = get_logger(__name__)

MODEL = "claude-opus-5"

#: Explaining pre-computed numbers is not intelligence-sensitive work, so
#: this runs below the default effort to keep the per-call cost small.
EFFORT = "medium"

MAX_TOKENS = 1024

SYSTEM_PROMPT = """You explain trading analysis that has already been \
computed. You are an explanation layer, not an analyst.

Absolute rules:

1. Never predict or forecast price. You have no information about future \
prices. If asked what will happen, say plainly that this cannot be known.
2. Never invent, adjust or recompute a number. Every price, size and score \
comes from the plan you are given. Quote them; do not derive new ones.
3. Never tell the reader to take the trade, and never phrase anything as \
advice or a recommendation.
4. The score measures how much the system's own components agree. It is \
not a probability and has never been calibrated against outcomes. Do not \
describe it as a chance, likelihood or edge.
5. Give the case against at least as much weight as the case for. If the \
`opposing` list is non-empty, those points must appear.

The reader is new to trading. Explain terms like ATR, R multiple and \
spread in passing when you first use them.

Write 3 short paragraphs of plain prose. No headings, no bullet lists, no \
markdown. Be concrete and calm. Do not open with a greeting."""


def is_configured() -> bool:
    """True when an API key is present.

    Absence is a normal state, not an error: the deterministic plan is the
    product, and the narrative is a garnish on top of it.
    """
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _render_plan(plan: TradePlan) -> str:
    """Flatten the plan into the facts the model may talk about."""
    lines = [
        f"Instrument: {plan.symbol} on {plan.timeframe.value}",
        f"Bias: {plan.bias.value}",
        f"Score: {plan.score}/100 (component agreement, NOT a probability)",
        f"Viability: {plan.viability.value}",
    ]

    if plan.viable:
        lines += [
            f"Entry: {plan.entry}",
            f"Stop: {plan.stop}",
            f"Target: {plan.target}",
            f"Reward-to-risk: {plan.risk_reward}",
        ]

        if plan.size is not None:
            lines.append(
                f"Position size: {plan.size} units, risking "
                f"{plan.risk_amount} {plan.currency or ''} "
                f"({plan.risk_percent}% of equity)"
            )

    if plan.atr is not None:
        lines.append(f"ATR: {plan.atr}")

    if plan.spread is not None:
        lines.append(f"Spread: {plan.spread}")

    if plan.supporting:
        lines.append("Supporting: " + " ".join(plan.supporting))

    if plan.opposing:
        lines.append("Opposing: " + " ".join(plan.opposing))

    if plan.warnings:
        lines.append("Warnings: " + " ".join(plan.warnings))

    lines.append(f"Evidence so far: {plan.evidence}")

    return "\n".join(lines)


def explain(plan: TradePlan) -> str | None:
    """Return a narrative for the plan, or None when unavailable.

    Failure is never fatal. The deterministic plan already answers the
    question; this only makes it readable.
    """
    if not is_configured():
        return None

    try:
        import anthropic
    except ImportError:
        logger.info("anthropic package not installed; narrative unavailable")
        return None

    try:
        client = anthropic.Anthropic()

        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            thinking={"type": "adaptive"},
            output_config={"effort": EFFORT},
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Explain this trade plan to someone new to trading.\n\n"
                        + _render_plan(plan)
                    ),
                }
            ],
        )

        if response.stop_reason == "refusal":
            logger.warning("Narrative request was declined")
            return None

        text = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()

        return text or None

    except Exception:
        # Never let an optional garnish break the panel. The API key is
        # not logged — the redaction filter would strip it anyway.
        logger.exception("Narrative generation failed")
        return None
