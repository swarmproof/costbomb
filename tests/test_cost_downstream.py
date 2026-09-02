"""Delivery 1 — downstream tool-cost / blast radius (the money a tool *moves*)."""

from __future__ import annotations

import pytest

from costbomb.attacks.base import TargetCapabilities
from costbomb.engine import FuzzEngine, SearchConfig
from costbomb.meter import CostMeter
from costbomb.pricing import PriceTable
from costbomb.targets.python_target import PythonTarget
from costbomb.tracebuild import TraceBuilder

MODEL = "anthropic:claude-opus-4-8"


def test_downstream_and_blast_radius_math(prices: PriceTable) -> None:
    tb = TraceBuilder(1)
    root = tb.root()
    tb.chat(root, model=MODEL, provider="anthropic", input_tokens=1000, output_tokens=0)  # 0.003
    for _ in range(3):
        tb.tool(root, tool_name="charge_card")  # $0 direct, $50 downstream each
    bd = CostMeter(prices).cost(tb.build())

    assert bd.total_usd == pytest.approx(0.003)  # direct bill = model only (charge_card fee is 0)
    assert bd.downstream_usd == pytest.approx(150.0)  # 3 × $50 real charges
    assert bd.blast_radius_usd == pytest.approx(0.003 + 150.0)
    assert bd.side_effecting_tools == ["charge_card"]
    assert bd.tool_call_counts["charge_card"] == 3


def test_non_side_effecting_tool_has_no_downstream(prices: PriceTable) -> None:
    tb = TraceBuilder(1)
    root = tb.root()
    tb.tool(root, tool_name="web_search")  # priced fee, not side-effecting
    bd = CostMeter(prices).cost(tb.build())
    assert bd.downstream_usd == 0.0
    assert bd.side_effecting_tools == []
    assert bd.blast_radius_usd == pytest.approx(bd.total_usd)


def test_blast_radius_defaults_to_total_when_no_side_effects(prices: PriceTable) -> None:
    tb = TraceBuilder(1)
    root = tb.root()
    tb.chat(root, model=MODEL, provider="anthropic", input_tokens=500, output_tokens=50)
    bd = CostMeter(prices).cost(tb.build())
    assert bd.blast_radius_usd == pytest.approx(bd.total_usd)  # backward-compatible


def test_e2e_fuzzer_targets_blast_radius(prices: PriceTable) -> None:
    # The refund agent's *direct* cost is flat, but its blast radius scales with the
    # storm. Optimizing blast_radius_usd must find the high-blast-radius input.
    caps = TargetCapabilities(has_tools=True, can_spawn=False, accepts_documents=True)
    target = PythonTarget("examples/refund_agent.py:handler", capabilities=caps)
    cfg = SearchConfig(seed=7, max_spend_usd=2.0, k=2, fitness="blast_radius_usd",
                       classes=("tool-storm", "retry-loop"))
    rf = FuzzEngine(target, prices=prices, config=cfg).run()

    top = rf.findings[0]
    assert top.breakdown.downstream_usd > 0
    assert "charge_card" in top.breakdown.side_effecting_tools
    # the money at risk dwarfs the agent's own bill
    assert top.breakdown.blast_radius_usd > 10 * top.breakdown.total_usd
    assert top.worst_usd == pytest.approx(top.breakdown.blast_radius_usd)  # fitness = blast radius


def test_findings_json_carries_blast_radius(prices: PriceTable) -> None:
    caps = TargetCapabilities(has_tools=True, can_spawn=False)
    target = PythonTarget("examples/refund_agent.py:handler", capabilities=caps)
    rf = FuzzEngine(target, prices=prices,
                    config=SearchConfig(seed=1, k=1, fitness="blast_radius_usd",
                                        classes=("tool-storm",))).run()
    fj = rf.to_findings_json()
    bd = fj["findings"][0]["breakdown"]
    assert "blast_radius_usd" in bd and "downstream_usd" in bd
    assert "side_effecting_tools" in bd
