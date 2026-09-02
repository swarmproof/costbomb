"""A side-effecting demo agent — where the blast radius dwarfs the token bill.

A "refund bot" that answers cheaply, but a crafted input lures it into a tool-storm
of `charge_card` calls (a real, side-effecting tool priced at $50 *downstream* per
call in the vendored table). The LLM token cost stays pennies; the **blast radius** —
the real money moved — runs into thousands. This is the case token-only metering
misses entirely (Delivery 1).

    costbomb run --target examples/refund_agent.py:handler --classes tool-storm,retry-loop
"""

from __future__ import annotations

from costbomb.targets import ModelCall, RunRecord

MODEL = "anthropic:claude-haiku-4-5"  # a cheap model — the tokens are not the danger

_STORM_WORDS = ("every", "each", "all", "retry", "again", "re-verify", "verify",
                "exhaustive", "reprocess", "reissue", "until")


def _count(text: str, words: tuple[str, ...]) -> int:
    low = text.lower()
    return sum(low.count(w) for w in words)


def handler(text: str, ctx: object | None = None) -> RunRecord:
    # Each mis-triggered instruction makes the bot "reprocess" one more refund →
    # one more real charge_card call.
    storms = min(40, _count(text, _STORM_WORDS))
    charges = 1 + storms

    context = 400 + len(text) // 4
    calls = [ModelCall(model=MODEL, provider="anthropic", input_tokens=context, output_tokens=40)]
    # The agent decides to fire a real, side-effecting tool once per reprocess.
    tool_calls = ["charge_card"] * charges
    return RunRecord(calls=calls, tool_calls=tool_calls)
