"""Delivery 2 — wall-clock / infra cost (time as a cost driver)."""

from __future__ import annotations

import pytest

from costbomb.attacks.base import TargetCapabilities
from costbomb.engine import FuzzEngine, SearchConfig
from costbomb.meter import CostMeter
from costbomb.pricing import PriceTable
from costbomb.targets.base import ModelCall, RunRecord
from costbomb.targets.python_target import PythonTarget
from costbomb.tracebuild import TraceBuilder

MODEL = "anthropic:claude-opus-4-8"
INFRA = PriceTable.from_path("examples/prices_infra.json")  # $0.01/s


def _trace_with_duration(seconds: float):
    tb = TraceBuilder(1)
    root = tb.root()
    tb.chat(root, model="anthropic:claude-haiku-4-5", provider="anthropic",
            input_tokens=300, output_tokens=30)
    return tb.build(duration_s=seconds)


def test_infra_cost_is_duration_times_rate() -> None:
    bd = CostMeter(INFRA).cost(_trace_with_duration(30.0))
    assert bd.duration_s == 30.0
    assert bd.infra_usd == pytest.approx(30.0 * 0.01)  # $0.30
    # total includes infra now
    assert bd.total_usd == pytest.approx(bd.model_usd + bd.tool_usd + bd.infra_usd)


def test_default_table_has_zero_infra_backward_compatible(prices: PriceTable) -> None:
    # Vendored table has no infra rate → a long run costs nothing extra (no regression).
    bd = CostMeter(prices).cost(_trace_with_duration(1000.0))
    assert prices.infra_usd_per_second == 0.0
    assert bd.infra_usd == 0.0


def test_runrecord_duration_flows_into_trace() -> None:
    rec = RunRecord(calls=[ModelCall(model="anthropic:claude-haiku-4-5", provider="anthropic",
                                     input_tokens=10)],
                    duration_s=12.5)
    trace = rec.to_trace(seed=1)
    assert trace.duration_s == 12.5
    assert CostMeter(INFRA).cost(trace).infra_usd == pytest.approx(12.5 * 0.01)


def test_trace_duration_survives_serialization() -> None:
    from costbomb._vendor.trace import Trace
    t = _trace_with_duration(7.0)
    assert Trace.from_dict(t.to_dict()).duration_s == 7.0


def test_e2e_fuzzer_finds_time_blowup() -> None:
    caps = TargetCapabilities(has_tools=False, can_spawn=False, accepts_documents=True)
    target = PythonTarget("examples/slow_agent.py:handler", capabilities=caps)
    cfg = SearchConfig(seed=3, max_spend_usd=50.0, k=2,
                       classes=("retry-loop", "clarification-trap"))
    rf = FuzzEngine(target, prices=INFRA, config=cfg).run()

    top = rf.findings[0]
    assert top.breakdown.infra_usd > 0
    assert top.breakdown.duration_s > 4.0  # more than the 1-turn baseline
    # infra dominates the cost of a slow-loop agent
    assert top.breakdown.infra_usd > top.breakdown.model_usd


def test_own_budget_cap_holds_under_infra_variance() -> None:
    # Infra makes per-run cost scale with the input the search worsens (high
    # structural variance). The own-budget cap must still never be exceeded (NFR-1).
    caps = TargetCapabilities(has_tools=False, can_spawn=False, accepts_documents=True)
    target = PythonTarget("examples/slow_agent.py:handler", capabilities=caps)
    for seed in range(12):
        rf = FuzzEngine(target, prices=INFRA, config=SearchConfig(
            seed=seed, max_spend_usd=2.0, k=5, classes=("retry-loop", "clarification-trap"))).run()
        assert rf.own_spend_usd <= 2.0, f"seed {seed} breached cap: ${rf.own_spend_usd}"
