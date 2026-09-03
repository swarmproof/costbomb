"""Reconciliation core — costbomb metered $ vs a real biller (per-slice NFR-8)."""

from __future__ import annotations

import pytest

from costbomb.meter import CostMeter
from costbomb.pricing import PriceTable
from costbomb.targets.http_target import _parse_run_record
from costbomb.tracebuild import TraceBuilder
from costbomb.validation import fixture_from_trace, reconcile

MODEL = "anthropic:claude-opus-4-8"


def test_reconcile_within_tolerance_passes() -> None:
    r = reconcile("llm", "openai", metered_usd=1.005, billed_usd=1.0, tolerance=0.01)
    assert r.passed and r.rel_error == pytest.approx(0.005)


def test_reconcile_out_of_tolerance_fails() -> None:
    r = reconcile("llm", "openai", metered_usd=1.02, billed_usd=1.0, tolerance=0.01)
    assert not r.passed
    assert "OUT OF TOLERANCE" in r.summary()


def test_reconcile_zero_billed_zero_metered_passes() -> None:
    r = reconcile("llm", "ollama-free", metered_usd=0.0, billed_usd=0.0, invoice_backed=False)
    assert r.passed
    assert "not a real bill" in r.summary()


def test_reconcile_zero_billed_nonzero_metered_fails() -> None:
    r = reconcile("llm", "openai", metered_usd=0.5, billed_usd=0.0)
    assert r.rel_error == float("inf")
    assert not r.passed


def test_fixture_from_trace_roundtrips_through_meter(prices: PriceTable) -> None:
    tb = TraceBuilder(1)
    root = tb.root()
    tb.chat(root, model=MODEL, provider="anthropic", input_tokens=1000, output_tokens=100)
    tb.chat(root, model=MODEL, provider="anthropic", input_tokens=500, output_tokens=50)
    tb.tool(root, tool_name="web_search")
    trace = tb.build()
    true_cost = CostMeter(prices).cost(trace).total_usd

    fx = fixture_from_trace(trace, name="live-run", provider="anthropic",
                            expected_usd=true_cost, price_table_version=prices.version,
                            expected_usd_source="invoice", provenance="test")
    # the emitted fixture is a valid corpus fixture that re-meters to the same cost
    assert fx["source"] == "real" and fx["expected_usd_source"] == "invoice"
    assert len(fx["run"]["calls"]) == 2 and fx["run"]["tool_calls"] == ["web_search"]
    remetered = CostMeter(prices).cost(_parse_run_record(fx["run"]).to_trace(seed=0)).total_usd
    assert remetered == pytest.approx(true_cost)


def test_fixture_from_trace_captures_spawns(prices: PriceTable) -> None:
    tb = TraceBuilder(1)
    root = tb.root()
    sub = tb.spawn(root)
    tb.chat(sub, model=MODEL, provider="anthropic", input_tokens=200, output_tokens=20)
    fx = fixture_from_trace(tb.build(), name="x", provider="anthropic", expected_usd=0.0,
                            price_table_version=prices.version)
    assert len(fx["run"]["spawns"]) == 1
    assert len(fx["run"]["spawns"][0]["calls"]) == 1
