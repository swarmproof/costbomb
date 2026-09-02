"""Delivery 3 — duplicate-effect costing (exactly-once cross-check, REQ-RP-4)."""

from __future__ import annotations

import pytest

from costbomb.attacks.base import TargetCapabilities
from costbomb.engine import FuzzEngine, SearchConfig
from costbomb.meter import CostMeter
from costbomb.pricing import PriceTable
from costbomb.targets.python_target import PythonTarget
from costbomb.tracebuild import TraceBuilder


def _trace_with_tools(*tools: str):
    tb = TraceBuilder(1)
    root = tb.root()
    for t in tools:
        tb.tool(root, tool_name=t)
    return tb.build()


def test_repeated_side_effecting_calls_are_duplicate_charges(prices: PriceTable) -> None:
    bd = CostMeter(prices).cost(_trace_with_tools("charge_card", "charge_card", "charge_card"))
    # 3 calls, only 1 intended → 2 duplicate $50 charges
    assert bd.duplicate_calls == {"charge_card": 2}
    assert bd.duplicate_effect_usd == pytest.approx(2 * 50.0)


def test_single_call_has_no_duplicate_cost(prices: PriceTable) -> None:
    bd = CostMeter(prices).cost(_trace_with_tools("charge_card"))
    assert bd.duplicate_effect_usd == 0.0
    assert bd.duplicate_calls == {}


def test_non_side_effecting_repeats_are_not_duplicate_charges(prices: PriceTable) -> None:
    # web_search is priced but NOT side-effecting → repeating it isn't a double-charge.
    bd = CostMeter(prices).cost(_trace_with_tools("web_search", "web_search", "web_search"))
    assert bd.duplicate_effect_usd == 0.0
    assert bd.duplicate_calls == {}


def test_duplicate_cost_is_subset_of_downstream(prices: PriceTable) -> None:
    bd = CostMeter(prices).cost(_trace_with_tools(*(["charge_card"] * 5)))
    assert bd.duplicate_effect_usd == pytest.approx(4 * 50.0)  # 5 calls → 4 dupes
    assert bd.downstream_usd == pytest.approx(5 * 50.0)  # all 5 are real charges
    assert bd.duplicate_effect_usd < bd.downstream_usd


def test_e2e_refund_agent_surfaces_duplicate_charge_risk(prices: PriceTable) -> None:
    caps = TargetCapabilities(has_tools=True, can_spawn=False)
    target = PythonTarget("examples/refund_agent.py:handler", capabilities=caps)
    rf = FuzzEngine(target, prices=prices, config=SearchConfig(
        seed=7, k=2, fitness="blast_radius_usd", classes=("tool-storm",))).run()

    top = rf.findings[0]
    assert top.breakdown.duplicate_effect_usd > 0
    assert "charge_card" in top.breakdown.duplicate_calls
    assert top.side_effect_risk is True
    fj = rf.to_findings_json()["findings"][0]["breakdown"]
    assert "duplicate_effect_usd" in fj and "duplicate_calls" in fj
