"""Scoped chat about the user's own market data.

Guardrails, in the order they apply:

1. **Input limits** — message and history are capped before any spend.
2. **Grounding** — a snapshot of the live deterministic state is injected
   on every turn, so answers describe the user's actual account and
   signals rather than generic trading talk.
3. **Topic scope** — anything outside this application's market analysis
   is declined and redirected.
4. **Output constraints** — no invented numbers, no recommendations, no
   probability framing, and no forecasting.

On that last point: a language model has no information about future
prices. Asked what will happen, it is instructed to say so and then give
what *is* knowable — the current readings, the levels, and what would
invalidate the read. That is a useful answer; a confident forecast would
not be.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.chat import providers
from backend.logging_setup import get_logger
from backend.planning.plan import TradePlan

logger = get_logger(__name__)

#: Transport settings live with the transports.
MODEL = providers.MODEL
EFFORT = providers.EFFORT
MAX_TOKENS = providers.MAX_TOKENS

#: Caps applied before any request is made, so a runaway client cannot
#: turn into a runaway bill.
MAX_MESSAGE_CHARS = 2000
MAX_HISTORY_TURNS = 12


SYSTEM_PROMPT = """You answer questions about ONE thing: the market \
analysis this desktop application has computed from the user's own \
Fortrade account. You are an explanation layer over deterministic \
calculations.

SCOPE — you may discuss:
- The instruments, signals, indicators and trade plans in the context below
- What a term means (ATR, RSI, R multiple, spread, expectancy, drawdown)
- How this application computes something, and what its numbers mean
- Why a setup is or is not tradeable, and what argues against it

SCOPE — decline anything else. If asked about other software, general \
life advice, code, news, politics, other markets not in the context, or \
anything unrelated, reply briefly that you only cover this application's \
market analysis, and name one thing in the context they could ask about \
instead. Do not answer the off-topic question even partially.

HARD RULES:

1. Never forecast price. You have no information about the future. When \
asked what will happen, where price is going, or whether a trade will \
win, say plainly that this cannot be known — then give what IS knowable: \
the current readings, the levels in the plan, and what would invalidate \
the read.
2. Never invent, adjust or recompute a number. Every figure you cite must \
appear in the context below. If a number is not there, say it is not \
available rather than estimating it.
3. Never tell the user to take, avoid, or size a trade. Describe; do not \
advise. Sizing shown in the context is arithmetic, not a recommendation.
4. The score measures how much the system's own components agree. It has \
never been calibrated against outcomes. Never call it a probability, a \
chance, a likelihood, a confidence level or an edge.
5. If the context shows a small paper-trading record or withheld \
statistics, say so when the user asks how well the system works. The \
honest answer is currently that this is unknown.
6. Give the case against a setup at least as much weight as the case for.

The user is new to trading. Explain terms in passing the first time they \
appear. Write plain prose, a few short paragraphs at most. No markdown \
headings or bullet lists. Be calm and concrete."""


OFF_TOPIC_HINT = (
    "I only cover the market analysis in this application. Ask me about "
    "the current signal, what an indicator means, or why a setup is or "
    "is not tradeable."
)


class ChatMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: str = Field(pattern="^(user|assistant)$")
    content: str


class ChatReply(BaseModel):
    model_config = ConfigDict(frozen=True)

    available: bool = False
    reply: str | None = None
    detail: str | None = None

    #: What live state the answer was grounded in, for transparency.
    grounded_on: tuple[str, ...] = ()

    #: Which transport handled it: "cli" (subscription) or "api" (key).
    provider: str | None = None


def is_configured() -> bool:
    """Whether any transport can currently answer a question."""
    return providers.select_provider().available()[0]


def build_context(
    plan: TradePlan | None,
    account: Any | None,
    coverage: list[Any] | None,
    paper_metrics: Any | None,
) -> tuple[str, list[str]]:
    """Render the live deterministic state the model may talk about.

    Returns the context block and a list naming what went into it, so the
    UI can show what an answer was actually based on.
    """
    lines: list[str] = []
    grounded: list[str] = []

    if account is not None:
        lines.append(
            f"ACCOUNT: {account.account_type.value}, equity "
            f"{account.equity} {account.currency}, balance {account.balance}, "
            f"open P&L {account.open_pnl}"
        )
        grounded.append("account")

    if plan is not None:
        lines.append(
            f"\nCURRENT SIGNAL: {plan.symbol} {plan.timeframe.value} — "
            f"bias {plan.bias.value}, score {plan.score}/100 "
            "(component agreement, NOT a probability)"
        )
        lines.append(f"Tradeable: {plan.viability.value}")

        if plan.viable:
            lines.append(
                f"Plan: entry {plan.entry}, stop {plan.stop}, "
                f"target {plan.target}, reward-to-risk {plan.risk_reward}"
            )

            if plan.size is not None:
                lines.append(
                    f"Sizing arithmetic: {plan.size} units risking "
                    f"{plan.risk_amount} {plan.currency} "
                    f"({plan.risk_percent}% of equity)"
                )

        if plan.atr is not None:
            lines.append(f"ATR: {plan.atr}")
        if plan.spread is not None:
            lines.append(f"Spread: {plan.spread}")

        if plan.supporting:
            lines.append("Supporting: " + " ".join(plan.supporting))
        if plan.opposing:
            lines.append("Arguing against: " + " ".join(plan.opposing))
        if plan.warnings:
            lines.append("Warnings: " + " ".join(plan.warnings))

        lines.append(f"Evidence: {plan.evidence}")
        grounded.append("signal and trade plan")

    if coverage:
        series = ", ".join(
            f"{c.symbol} {c.timeframe.value} ({c.count} bars)" for c in coverage[:8]
        )
        lines.append(f"\nCANDLE HISTORY HELD: {series}")
        grounded.append("candle coverage")

    if paper_metrics is not None:
        if paper_metrics.sufficient:
            lines.append(
                f"\nPAPER RECORD: {paper_metrics.trades} closed trades, "
                f"win rate {paper_metrics.win_rate}%, "
                f"expectancy {paper_metrics.expectancy_r}R"
            )
        else:
            lines.append(
                f"\nPAPER RECORD: {paper_metrics.trades} closed trades — "
                f"below the {paper_metrics.minimum_trades} needed before a "
                "win rate or expectancy means anything, so those figures "
                "are withheld rather than estimated."
            )
        grounded.append("paper trading record")

    if not lines:
        return ("No live data is currently available.", [])

    return ("\n".join(lines), grounded)


NOTHING_AVAILABLE = (
    "No way to reach a model. Either install Claude Code (`claude` on "
    "PATH) to use the subscription you already have, or set "
    "ANTHROPIC_API_KEY. The analysis panels are unaffected — this only "
    "adds the chat."
)


def unavailable_detail(
    provider: providers.ChatProvider, why_not: str | None
) -> str:
    """Explain an absent transport.

    Auto-selection only lands on the API when the CLI was already ruled
    out, so reaching here with the API means nothing works and both
    options are worth naming. A specific failure is more useful than the
    generic message whenever we have one.
    """
    if provider is providers.API:
        return NOTHING_AVAILABLE

    return why_not or NOTHING_AVAILABLE


def build_prompt(
    message: str, history: list[ChatMessage], context: str
) -> str:
    """Fold the live state and the recent turns into one prompt.

    A single string rather than a message list, because both transports
    take one: the CLI has no notion of prior assistant turns and each of
    its invocations is deliberately independent.
    """
    parts: list[str] = [f"Live data from the application:\n\n{context}"]

    # Trim oldest turns first; the current question matters most and an
    # unbounded history is an unbounded bill.
    recent = history[-MAX_HISTORY_TURNS:]

    if recent:
        transcript = "\n".join(
            f"{'User' if m.role == 'user' else 'You'}: {m.content}"
            for m in recent
        )
        parts.append(f"Earlier in this conversation:\n\n{transcript}")

    parts.append(f"Question: {message}")

    return "\n\n---\n\n".join(parts)


def ask(
    message: str,
    history: list[ChatMessage],
    context: str,
    grounded: list[str],
    provider: providers.ChatProvider | None = None,
) -> ChatReply:
    """Answer one question within scope, or explain why it cannot.

    Every guardrail is applied here, above the transport: the length cap,
    the history cap, and the system prompt. A provider only turns a
    prompt into text.
    """
    cleaned = message.strip()

    if not cleaned:
        return ChatReply(available=False, detail="Empty message.")

    if len(cleaned) > MAX_MESSAGE_CHARS:
        return ChatReply(
            available=False,
            detail=f"Message too long (limit {MAX_MESSAGE_CHARS} characters).",
        )

    chosen = provider or providers.select_provider()
    usable, why_not = chosen.available()

    if not usable:
        # Neither transport is a hard requirement, so an absent one is a
        # normal state to report rather than an error to raise.
        return ChatReply(
            available=False,
            detail=unavailable_detail(chosen, why_not),
            provider=chosen.name,
        )

    try:
        text = chosen.complete(SYSTEM_PROMPT, build_prompt(cleaned, history, context))
    except Exception:
        # Credentials are never logged; the redaction filter would strip
        # them regardless.
        logger.exception("Chat request failed", extra={"context": {"via": chosen.name}})

        return ChatReply(
            available=False,
            detail="The request failed. Check the logs for detail.",
            provider=chosen.name,
        )

    if not text:
        return ChatReply(
            available=False, detail="Empty response.", provider=chosen.name
        )

    return ChatReply(
        available=True,
        reply=text,
        grounded_on=tuple(grounded),
        provider=chosen.name,
    )
