"""Delivery 3 (real integration) — key-aware exactly-once cross-check (REQ-RP-4)."""

from __future__ import annotations

import pytest

from costbomb.meter import CostMeter, NativeDedupChecker
from costbomb.pricing import PriceTable
from costbomb.tracebuild import TraceBuilder


def _trace(*calls):
    """calls: (tool, key, deduped) tuples."""
    tb = TraceBuilder(1)
    root = tb.root()
    for name, key, deduped in calls:
        tb.tool(root, tool_name=name, key=key, deduped=deduped)
    return tb.build()


# ---- native checker: dedup by business key, honor target dedup ----

def test_same_key_repeats_are_duplicates(prices: PriceTable) -> None:
    bd = CostMeter(prices).cost(_trace(
        ("charge_card", "order-1", False),
        ("charge_card", "order-1", False),
        ("charge_card", "order-1", False),
    ))
    assert bd.duplicate_calls == {"charge_card": 2}  # 3 to one order → 2 dupes
    assert bd.duplicate_effect_usd == pytest.approx(2 * 50.0)


def test_distinct_keys_are_not_duplicates(prices: PriceTable) -> None:
    # 3 charges to 3 different orders = 3 legitimate effects, no double-charge.
    bd = CostMeter(prices).cost(_trace(
        ("charge_card", "order-1", False),
        ("charge_card", "order-2", False),
        ("charge_card", "order-3", False),
    ))
    assert bd.duplicate_effect_usd == 0.0
    assert bd.duplicate_calls == {}


def test_target_deduped_calls_are_not_at_risk(prices: PriceTable) -> None:
    # Same order 3×, but the agent's own idempotency already fired-once twice.
    bd = CostMeter(prices).cost(_trace(
        ("charge_card", "order-1", False),
        ("charge_card", "order-1", True),
        ("charge_card", "order-1", True),
    ))
    assert bd.duplicate_effect_usd == 0.0  # protected → no exposure


def test_native_checker_unit() -> None:
    c = NativeDedupChecker()
    assert c.at_risk_duplicates("t", ["a", "a", "a"], [False, False, False]) == 2
    assert c.at_risk_duplicates("t", ["a", "b"], [False, False]) == 0
    assert c.at_risk_duplicates("t", ["a", "a"], [False, True]) == 0


# ---- the REAL integration: observe dedup via the exactly_once middleware ----

eo = pytest.importorskip("exactly_once")  # needs `pip install costbomb[exactly-once]`


def test_exactly_once_checker_matches_native(prices: PriceTable) -> None:
    from costbomb.integrations.exactly_once import ExactlyOnceDedupChecker

    real = ExactlyOnceDedupChecker()
    native = NativeDedupChecker()
    cases = [
        (["o1", "o1", "o1", "o2"], [False] * 4),
        (["o1", "o2", "o3"], [False] * 3),
        (["o1", "o1"], [False, True]),
    ]
    for keys, dd in cases:
        assert real.at_risk_duplicates("charge_card", keys, dd) == native.at_risk_duplicates(
            "charge_card", keys, dd
        )


def test_meter_with_real_checker(prices: PriceTable) -> None:
    from costbomb.integrations.exactly_once import ExactlyOnceDedupChecker

    trace = _trace(*[("charge_card", "order-1", False)] * 5)
    bd = CostMeter(prices, dedup_checker=ExactlyOnceDedupChecker()).cost(trace)
    assert bd.duplicate_effect_usd == pytest.approx(4 * 50.0)  # real middleware: 4 deduped


def test_cross_check_report_before_after(prices: PriceTable) -> None:
    from costbomb.integrations.exactly_once import cross_check

    trace = _trace(*[("charge_card", "order-R100", False)] * 10)
    [report] = cross_check(trace, prices)
    assert report.tool == "charge_card"
    assert report.calls == 10
    assert report.fires == 1  # exactly-once collapses to a single real charge
    assert report.deduped == 9
    assert report.usd_prevented == pytest.approx(9 * 50.0)
