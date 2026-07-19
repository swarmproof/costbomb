"""A deliberately denial-of-wallet-vulnerable demo agent (the launch demo).

It answers a trivial question for ~half a cent — but a crafted input lures it into a
retry/verify loop that re-reads an ever-growing context each turn, running the bill
into dollars. costbomb should find that input automatically, under its own budget
cap. This is the "5¢ → $5" story from ARCHITECTURE §4 / TEST-PLAN E2E-1.

Run it::

    costbomb run --target examples/demo_agent.py:handler --seed 1337

The handler follows costbomb's honest instrumentation contract: it returns a
``RunRecord`` describing what it *spent* (model calls + tool calls), and costbomb
meters that truthfully. A real agent would instead report its provider ``usage``.
"""

from __future__ import annotations

from costbomb.targets import ModelCall, RunRecord

MODEL = "anthropic:claude-opus-4-8"

# Words that (mis)trigger this agent into looping or over-using tools.
_LOOP_WORDS = ("retry", "until", "again", "start over", "re-verify", "verify",
               "keep trying", "discard", "clarify", "confirm", "assumption")
_TOOL_WORDS = ("cross-check", "every", "exhaustive", "triangulate", "source", "independent")


def _count(text: str, words: tuple[str, ...]) -> int:
    low = text.lower()
    return sum(low.count(w) for w in words)


def handler(text: str, ctx: object | None = None) -> RunRecord:
    loops = min(40, _count(text, _LOOP_WORDS))
    tools = min(20, _count(text, _TOOL_WORDS))

    # A short question ≈ tiny context; a document-heavy prompt grows it.
    context = 120 + len(text) // 4
    turns = 1 + 4 * loops  # the loop: each mis-triggered instruction adds turns…

    calls = [
        ModelCall(
            model=MODEL,
            provider="anthropic",
            input_tokens=context * (i + 1),  # accumulating context — the money sink
            output_tokens=40,
        )
        for i in range(turns)
    ]
    tool_calls = ["premium_api"] * tools
    return RunRecord(calls=calls, tool_calls=tool_calls)
