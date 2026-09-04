"""Reconciliation — cross-check costbomb's metered $ against a real biller.

costbomb's `total_usd` / `blast_radius_usd` are sums across *different billers* (the
LLM provider, Stripe, your cloud). No single statement proves the whole number, so
validation is per-slice: meter one slice, fetch what its biller actually charged, and
compare. This module is the biller-agnostic core; the biller adapters (LLM dashboard,
Stripe test-mode) live in `costbomb.integrations`.

A passing reconciliation against a **real invoice** is the only thing that proves
NFR-8 for that slice — everything else is arithmetic or modelling.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from costbomb._vendor.trace import GenAI, Span, Trace


@dataclass
class SliceReconciliation:
    """costbomb's number for one cost slice vs the biller's own figure."""

    slice: str  # "llm" | "stripe" | "infra"
    biller: str  # "openai" | "anthropic" | "stripe-test" | "ollama-free"
    metered_usd: float  # what costbomb computed
    billed_usd: float  # ground truth from the biller (invoice / dashboard / API)
    tolerance: float = 0.01  # NFR-8
    invoice_backed: bool = True  # False for a free/derived reference (not a real bill)

    @property
    def delta_usd(self) -> float:
        return abs(self.metered_usd - self.billed_usd)

    @property
    def rel_error(self) -> float:
        if self.billed_usd > 1e-12:
            return self.delta_usd / self.billed_usd
        return 0.0 if self.metered_usd <= 1e-12 else float("inf")

    @property
    def passed(self) -> bool:
        return self.rel_error <= self.tolerance

    def summary(self) -> str:
        tag = "invoice" if self.invoice_backed else "reference (not a real bill)"
        verdict = "✓ within tolerance" if self.passed else "✗ OUT OF TOLERANCE"
        return (
            f"[{self.slice}/{self.biller}] metered ${self.metered_usd:.6f} vs "
            f"billed ${self.billed_usd:.6f} ({tag}) — "
            f"{self.rel_error:.3%} error, tol {self.tolerance:.0%} → {verdict}"
        )


def reconcile(
    slice: str,
    biller: str,
    *,
    metered_usd: float,
    billed_usd: float,
    tolerance: float = 0.01,
    invoice_backed: bool = True,
) -> SliceReconciliation:
    return SliceReconciliation(
        slice=slice, biller=biller, metered_usd=metered_usd, billed_usd=billed_usd,
        tolerance=tolerance, invoice_backed=invoice_backed,
    )


# ---- turning a real metered run into a corpus fixture ----


def _children(trace: Trace, parent_id: str) -> list[Span]:
    return [s for s in trace.spans if s.parent_span_id == parent_id]


def _runrecord_from_trace(trace: Trace, parent_id: str) -> dict[str, Any]:
    """Reconstruct a RunRecord-shaped dict from a live (proxy-captured) trace."""
    calls: list[dict[str, Any]] = []
    tool_calls: list[Any] = []
    spawns: list[dict[str, Any]] = []
    from costbomb._vendor.trace import Swarmproof

    for s in _children(trace, parent_id):
        op = s.get(GenAI.OPERATION_NAME)
        if op == "chat" or s.get(GenAI.USAGE_INPUT_TOKENS) is not None:
            calls.append({
                "model": s.get(GenAI.REQUEST_MODEL, ""),
                "provider": s.get(GenAI.PROVIDER_NAME, ""),
                "input_tokens": int(s.get(GenAI.USAGE_INPUT_TOKENS, 0) or 0),
                "output_tokens": int(s.get(GenAI.USAGE_OUTPUT_TOKENS, 0) or 0),
                "reasoning_tokens": int(s.get(Swarmproof.USAGE_REASONING_TOKENS, 0) or 0),
                "cache_read_tokens": int(s.get(Swarmproof.USAGE_CACHE_READ_TOKENS, 0) or 0),
                "cache_write_tokens": int(s.get(Swarmproof.USAGE_CACHE_WRITE_TOKENS, 0) or 0),
            })
        elif s.get(GenAI.TOOL_NAME):
            tool_calls.append(s.get(GenAI.TOOL_NAME))
        elif op == "invoke_agent":
            spawns.append(_runrecord_from_trace(trace, s.span_id))
    return {"calls": calls, "tool_calls": tool_calls, "spawns": spawns}


def fixture_from_trace(
    trace: Trace,
    *,
    name: str,
    provider: str,
    expected_usd: float,
    price_table_version: str,
    source: str = "real",
    expected_usd_source: str = "invoice",
    provenance: str = "",
) -> dict[str, Any]:
    """Emit a meter-accuracy corpus fixture from a real, metered run."""
    return {
        "name": name,
        "source": source,
        "expected_usd_source": expected_usd_source,
        "provider": provider,
        "price_table_version": price_table_version,
        "expected_usd": round(expected_usd, 8),
        "provenance": provenance,
        "run": _runrecord_from_trace(trace, trace.root_span_id),
    }
