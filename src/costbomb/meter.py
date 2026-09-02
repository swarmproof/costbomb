"""Cost meter — the oracle (ADR-2, REQ-CM-1/4/6, NFR-8).

True dollars for one agent run is a **sum over cost sources**, attributed to the
single triggering input::

    cost(run) = Σ_calls  (in·p_in + out·p_out + think·p_think + cr·p_cr + cw·p_cw)   # model calls
              + Σ_tools  tool_price[tool]                                             # tool-call fees
              + Σ_spawns cost(child_run)                                              # sub-agent rollup

The third line is not a separate additive bucket — a spawned sub-agent's cost *is*
its own model + tool spans, which already live in the same ``Trace`` under
parent/child linkage (REQ-CM-4). So summing every priced span in the flattened
trace already includes spawns; ``spawn_usd`` is reported as the *portion* of the
total incurred inside sub-agents, for attribution, never double-counted.

A token-only meter misses the tool and spawn lines — which is exactly where
``tool-storm`` and ``recursion`` live. That is why the meter, not tokens×price,
is the oracle.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from costbomb._vendor.trace import CostSource, GenAI, Span, Swarmproof, Trace
from costbomb.pricing import PriceTable


class CostBreakdown(BaseModel):
    """Per-run cost, broken down by source/model/tool (REQ-CM-6).

    ``model_usd + tool_usd == total_usd`` by construction. ``spawn_usd`` is a view
    into the total (the sub-agent share), not an extra term.
    """

    total_usd: float = 0.0  # the agent's own bill: model tokens + direct tool fees
    model_usd: float = 0.0
    tool_usd: float = 0.0
    spawn_usd: float = 0.0
    # Delivery 1: real-world consequence cost the tools caused, and the full money at
    # risk. `blast_radius_usd == total_usd + downstream_usd`. total_usd stays the
    # direct bill (baseline-compatible); blast radius is the true denial-of-wallet number.
    downstream_usd: float = 0.0
    blast_radius_usd: float = 0.0
    by_model: dict[str, float] = Field(default_factory=dict)
    by_tool: dict[str, float] = Field(default_factory=dict)
    n_model_calls: int = 0
    n_tool_calls: int = 0
    n_spawns: int = 0
    tool_call_counts: dict[str, int] = Field(default_factory=dict)
    side_effecting_tools: list[str] = Field(default_factory=list)
    estimated: bool = False
    unpriced_tools: list[str] = Field(default_factory=list)


def _model_key(span: Span) -> str:
    """Build the ``provider:model`` price-table key from a span's gen_ai attrs."""
    model = span.get(GenAI.REQUEST_MODEL, "")
    provider = span.get(GenAI.PROVIDER_NAME, "")
    if model and provider and ":" not in model:
        return f"{provider}:{model}"
    return model


def _is_tool_span(span: Span) -> bool:
    return span.get(GenAI.OPERATION_NAME) == "execute_tool" or bool(span.get(GenAI.TOOL_NAME))


def _has_token_usage(span: Span) -> bool:
    return any(
        span.get(k) is not None
        for k in (
            GenAI.USAGE_INPUT_TOKENS,
            GenAI.USAGE_OUTPUT_TOKENS,
            Swarmproof.USAGE_REASONING_TOKENS,
            Swarmproof.USAGE_CACHE_READ_TOKENS,
            Swarmproof.USAGE_CACHE_WRITE_TOKENS,
        )
    )


class CostMeter:
    """Reads a :class:`Trace` and produces a :class:`CostBreakdown`.

    The meter is *pure*: same trace + same table → same numbers, every time. That
    is what makes re-pricing (REQ-CM-8) and the price-drift-separated CI gate
    (REQ-CI-3) possible — you just call :meth:`cost` again with a different table.
    """

    def __init__(self, prices: PriceTable) -> None:
        self.prices = prices

    def cost(self, trace: Trace, *, annotate: bool = True) -> CostBreakdown:
        """Compute the full breakdown for one run.

        When ``annotate`` is set, each priced span gets ``swarmproof.cost.usd`` and
        ``swarmproof.cost.source`` written back so the exported trace carries the
        per-span cost (REQ-CM-6, REQ-RP-5).
        """
        bd = CostBreakdown(estimated=trace.estimated)
        self_cost: dict[str, float] = {}

        for span in trace.spans:
            source, amount = self._span_cost(span, bd)
            self_cost[span.span_id] = amount
            if source is None:
                continue
            if annotate:
                span.set(Swarmproof.COST_USD, round(amount, 10))
                span.set(Swarmproof.COST_SOURCE, source.value)
            if span.get(Swarmproof.COST_ESTIMATED):
                bd.estimated = True

        bd.total_usd = bd.model_usd + bd.tool_usd
        bd.spawn_usd = self._spawn_share(trace, self_cost)
        bd.n_spawns = self._count_spawns(trace)

        bd.blast_radius_usd = bd.total_usd + bd.downstream_usd

        # Deterministic, cent-clean rounding for reports/baselines (NFR-2).
        bd.total_usd = round(bd.total_usd, 10)
        bd.model_usd = round(bd.model_usd, 10)
        bd.tool_usd = round(bd.tool_usd, 10)
        bd.spawn_usd = round(bd.spawn_usd, 10)
        bd.downstream_usd = round(bd.downstream_usd, 10)
        bd.blast_radius_usd = round(bd.blast_radius_usd, 10)
        bd.by_model = {k: round(v, 10) for k, v in sorted(bd.by_model.items())}
        bd.by_tool = {k: round(v, 10) for k, v in sorted(bd.by_tool.items())}
        bd.side_effecting_tools = sorted(set(bd.side_effecting_tools))
        return bd

    # ---- per-span costing ----

    def _span_cost(self, span: Span, bd: CostBreakdown) -> tuple[CostSource | None, float]:
        if _is_tool_span(span):
            name = span.get(GenAI.TOOL_NAME, "unknown_tool")
            fee = self.prices.tool_price(name)
            if not self.prices.has_tool(name) and name not in bd.unpriced_tools:
                bd.unpriced_tools.append(name)
            bd.tool_usd += fee
            bd.downstream_usd += self.prices.tool_downstream(name)  # consequence cost
            bd.by_tool[name] = bd.by_tool.get(name, 0.0) + fee
            bd.tool_call_counts[name] = bd.tool_call_counts.get(name, 0) + 1
            if self.prices.tool_side_effecting(name) and name not in bd.side_effecting_tools:
                bd.side_effecting_tools.append(name)
            bd.n_tool_calls += 1
            return CostSource.TOOL, fee

        if _has_token_usage(span) or span.get(GenAI.OPERATION_NAME) == "chat":
            key = _model_key(span)
            price = self.prices.model(key)  # loud on unknown model (UT-CM-6)
            amount = (
                int(span.get(GenAI.USAGE_INPUT_TOKENS, 0)) * price.input_cost_per_token
                + int(span.get(GenAI.USAGE_OUTPUT_TOKENS, 0)) * price.output_cost_per_token
                + int(span.get(Swarmproof.USAGE_REASONING_TOKENS, 0)) * price.reasoning_cost_per_token
                + int(span.get(Swarmproof.USAGE_CACHE_READ_TOKENS, 0)) * price.cache_read_cost_per_token
                + int(span.get(Swarmproof.USAGE_CACHE_WRITE_TOKENS, 0)) * price.cache_write_cost_per_token
            )
            bd.model_usd += amount
            bd.by_model[key] = bd.by_model.get(key, 0.0) + amount
            bd.n_model_calls += 1
            return CostSource.MODEL, amount

        return None, 0.0

    # ---- spawn attribution (REQ-CM-4) ----

    @staticmethod
    def _spawn_spans(trace: Trace) -> list[Span]:
        """`invoke_agent` spans other than the root — i.e. sub-agent spawns."""
        return [
            s
            for s in trace.spans
            if s.get(GenAI.OPERATION_NAME) == "invoke_agent" and s.span_id != trace.root_span_id
        ]

    def _count_spawns(self, trace: Trace) -> int:
        return len(self._spawn_spans(trace))

    def _spawn_share(self, trace: Trace, self_cost: dict[str, float]) -> float:
        """Sum of self-costs of every span descending from a spawned sub-agent."""
        spawn_roots = {s.span_id for s in self._spawn_spans(trace)}
        if not spawn_roots:
            return 0.0
        parent_of = {s.span_id: s.parent_span_id for s in trace.spans}

        def under_spawn(span_id: str) -> bool:
            seen: set[str] = set()
            cur: str | None = span_id
            while cur is not None and cur not in seen:
                if cur in spawn_roots:
                    return True
                seen.add(cur)
                cur = parent_of.get(cur)
            return False

        return sum(cost for sid, cost in self_cost.items() if under_spawn(sid))

    def reprice(self, trace: Trace, table: PriceTable) -> CostBreakdown:
        """Re-price a recorded trace under a different table (REQ-CM-8, REQ-CI-3).

        Used by the CI gate to separate provider price drift from agent regression:
        the baseline's stored inputs/traces are re-priced under the current table
        before comparison, so a price hike alone never fails a build.
        """
        return CostMeter(table).cost(trace, annotate=False)
