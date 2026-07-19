"""Dry-run estimator — the cheap surrogate that gates real spend (REQ-CM-7, ADR-4).

Two jobs (ARCHITECTURE §2.4):
1. **Surrogate pre-ranker** — score a candidate from its *structure* so the engine
   spends real dollars only confirming the top-K. Only the *ranking* has to be good
   (UT-EST-1 measures rank correlation), so a cheap heuristic suffices.
2. **CI smoke mode** — produce a gate result in seconds with zero paid calls
   (REQ-CI-4, NFR-7): the estimate stands in for the metered cost, flagged
   ``estimated``.

The estimate mirrors the cost drivers the meter sums (turns × context, tool calls,
spawns) but reads them from the *input's* cost-intent features, since no trace
exists yet before a run.
"""

from __future__ import annotations

from costbomb._vendor.trace import Trace
from costbomb.attacks.base import Input
from costbomb.meter import CostMeter
from costbomb.pricing import PriceTable

# Generic cost-intent vocabularies (target-agnostic). These are what an input is
# *asking the agent to do*; more of them → more predicted spend.
_LOOP_WORDS = ("retry", "until", "again", "start over", "re-verify", "keep trying", "clarify",
               "confirm", "assumption", "not sure", "discard")
_TOOL_WORDS = ("cross-check", "every", "exhaustive", "verify", "triangulate", "source",
               "independent", "lookup", "tool")
_SPAWN_WORDS = ("sub-agent", "spawn", "recursively", "delegate", "decompose", "specialist")


def _count(text: str, words: tuple[str, ...]) -> int:
    low = text.lower()
    return sum(low.count(w) for w in words)


class Estimator:
    """Heuristic surrogate. A blended per-token price makes the score $-scaled."""

    def __init__(
        self,
        prices: PriceTable,
        *,
        blend_model: str = "anthropic:claude-opus-4-8",
        base_context_tokens: int = 1500,
        tool_price: float = 0.02,
        base_output_tokens: int = 200,
    ) -> None:
        self.prices = prices
        self.base_context_tokens = base_context_tokens
        self.tool_price = tool_price
        self.base_output_tokens = base_output_tokens
        try:
            mp = prices.model(blend_model)
            # A single blended $/token, weighting output like a typical short reply.
            self._per_tok = mp.input_cost_per_token + mp.output_cost_per_token * 0.1
        except Exception:  # noqa: BLE001 - unpriced blend model → nominal scale
            self._per_tok = 3.3e-06

    def estimate_input(self, input: Input) -> float:
        """Predicted worst-case $ for an input, from its structure alone."""
        loops = _count(input.text, _LOOP_WORDS)
        tools = _count(input.text, _TOOL_WORDS)
        spawns = _count(input.text, _SPAWN_WORDS)
        context = self.base_context_tokens + max(1, len(input.text) // 4)
        turns = 1 + loops

        # turns × accumulating context (Σ i·context for i in 1..turns) = the loop cost.
        model_tokens = context * (turns * (turns + 1) / 2)
        spawn_tokens = spawns * context
        model_usd = (model_tokens + spawn_tokens + turns * self.base_output_tokens) * self._per_tok
        tool_usd = tools * self.tool_price
        return model_usd + tool_usd

    def estimate_trace(self, trace: Trace) -> float:
        """When a (dry/structural) trace exists, price it directly via the meter."""
        return CostMeter(self.prices).cost(trace, annotate=False).total_usd
