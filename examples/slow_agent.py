"""A time-blowup demo agent — where the cost is wall-clock, not tokens (Delivery 2).

Cheap tokens, but a crafted input makes it grind for many turns on dedicated compute.
Priced with an infra rate (see `examples/prices_infra.json`), the long run costs real
money even though the token bill is trivial — the "$47k over 11 days" shape, where
time is the cost driver.

    costbomb run --target examples/slow_agent.py:handler \
        --price-table examples/prices_infra.json --classes retry-loop,clarification-trap
"""

from __future__ import annotations

from costbomb.targets import ModelCall, RunRecord

MODEL = "anthropic:claude-haiku-4-5"
SECONDS_PER_TURN = 4.0

_LOOP_WORDS = ("retry", "until", "again", "verify", "re-verify", "keep trying",
               "start over", "discard", "clarify", "confirm")


def _count(text: str, words: tuple[str, ...]) -> int:
    low = text.lower()
    return sum(low.count(w) for w in words)


def handler(text: str, ctx: object | None = None) -> RunRecord:
    turns = 1 + min(40, _count(text, _LOOP_WORDS))
    calls = [
        ModelCall(model=MODEL, provider="anthropic", input_tokens=300, output_tokens=30)
        for _ in range(turns)
    ]
    # The money sink is time on dedicated compute, not tokens.
    return RunRecord(calls=calls, duration_s=turns * SECONDS_PER_TURN)
