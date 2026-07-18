"""FakeTarget — a scripted, deterministic agent for tests and demos (no real $).

The test pyramid leans on this (TEST-PLAN §1): its spend is a pure function of the
input text and the seed, so the engine can be proven to *climb* (IT-1), to *respect
its own budget cap* (IT-2), and to be *deterministic* (E2E-5) without spending a
cent. Cost rises with the number of cost-explosion "lever" words an attack class
appends on each mutation, so a search that works will visibly drive the bill up.
"""

from __future__ import annotations

from random import Random

from costbomb._vendor.trace import Trace
from costbomb.attacks.base import Input, TargetCapabilities
from costbomb.targets.base import TargetContext
from costbomb.tracebuild import TraceBuilder

# Lever vocabularies — each mutation appends words from one of these, so occurrence
# counts grow with generation and the modelled cost climbs monotonically.
_RETRY = ("retry", "until", "start over", "re-verify", "again", "never give up", "discard")
_TOOL = ("cross-check", "every", "exhaustive", "verify", "triangulate", "source", "independent")
_SPAWN = ("sub-agent", "spawn", "recursively", "delegate", "decompose", "specialist")
_CLARIFY = ("clarify", "confirm", "assumption", "ask me", "not sure")


def _count(text: str, words: tuple[str, ...]) -> int:
    low = text.lower()
    return sum(low.count(w) for w in words)


def _est_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class FakeTarget:
    """A deterministic stand-in agent.

    Args tune the economics so a demo can show, e.g., a ~5¢ baseline exploding into
    dollars. The defaults produce a healthy amplification under the 5 attack classes.
    """

    def __init__(
        self,
        *,
        model: str = "anthropic:claude-opus-4-8",
        provider: str = "anthropic",
        priced_tool: str = "premium_api",
        base_input_tokens: int = 1500,
        base_output_tokens: int = 200,
        cap_hits: int = 30,
    ) -> None:
        self.model = model
        self.provider = provider
        self.priced_tool = priced_tool
        self.base_input_tokens = base_input_tokens
        self.base_output_tokens = base_output_tokens
        self.cap_hits = cap_hits

    def capabilities(self) -> TargetCapabilities:
        return TargetCapabilities(
            has_tools=True,
            tool_names=(self.priced_tool, "web_search"),
            priced_tool_names=(self.priced_tool,),
            can_spawn=True,
            supports_reasoning=False,
            accepts_documents=True,
        )

    def invoke(self, input: Input, ctx: TargetContext) -> Trace:
        text = input.text
        cap = self.cap_hits
        retry = min(cap, _count(text, _RETRY))
        tool = min(cap, _count(text, _TOOL))
        spawn = min(cap, _count(text, _SPAWN))
        clarify = min(cap, _count(text, _CLARIFY))

        # Small, deterministic per-run jitter so p95-over-k is meaningful (ADR-1)
        # yet identical for a given (seed, run_index) (NFR-2).
        rng = Random(ctx.seed ^ (ctx.run_index * 2654435761))
        jitter = 1.0 + rng.uniform(-0.05, 0.05)

        context = self.base_input_tokens + _est_tokens(text)
        turns = 1 + retry + clarify

        tb = TraceBuilder(ctx.seed, attack_class=input.attack_class)
        root = tb.root()

        # Each turn re-reads the accumulated context (retry/clarify loops re-send it,
        # context-bomb grows it) — this is where turns × context becomes real money.
        for i in range(turns):
            in_tok = int(context * (i + 1) * jitter)
            tb.chat(
                root,
                model=self.model,
                provider=self.provider,
                input_tokens=in_tok,
                output_tokens=self.base_output_tokens,
            )

        for _ in range(tool):
            tb.tool(root, tool_name=self.priced_tool)

        for _ in range(spawn):
            sub = tb.spawn(root)
            tb.chat(
                sub,
                model=self.model,
                provider=self.provider,
                input_tokens=int(context * jitter),
                output_tokens=self.base_output_tokens,
            )

        return tb.build()
