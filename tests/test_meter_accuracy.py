"""Meter-accuracy corpus — the oracle's dedicated suite (TEST-PLAN §6, NFR-8).

The meter is the oracle; if it lies, the search optimizes a lie and the CI gate is
meaningless. This suite checks costbomb's metered dollars against each fixture's
**independently-known** cost.

Honesty contract (see tests/fixtures/meter/README.md):
- `synthetic` fixtures prove the meter's *arithmetic* (no dropped token class, no
  double-counted spawn) — their expected $ is hand-computed, not produced by the meter.
- `real` fixtures prove the ≤1% claim in NFR-8 — their expected $ is the provider's
  own reported cost. Until ≥REQUIRED_REAL of them exist, `test_ma1_real_invoice_corpus`
  SKIPS with a loud message, so a green run never reads as "validated against real bills".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from costbomb.meter import CostMeter
from costbomb.pricing import PriceTable
from costbomb.targets.http_target import _parse_run_record  # RunRecord-from-payload parser

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "meter"
TOLERANCE = 0.01  # NFR-8: ≤1%
REQUIRED_REAL = 20  # TEST-PLAN §6: ≥20 recorded real runs across providers


def _load() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(FIXTURES_DIR.glob("*.json"))]


FIXTURES = _load()
IDS = [f["name"] for f in FIXTURES]


def _metered(fx: dict) -> CostMeter:
    pt = PriceTable.default()
    assert fx["price_table_version"] == pt.version, (
        f"fixture {fx['name']} priced against {fx['price_table_version']} "
        f"but loaded table is {pt.version} — refusing to compare across tables (MA-5)."
    )
    record = _parse_run_record(fx["run"])
    trace = record.to_trace(seed=0)
    return CostMeter(pt).cost(trace)


def test_corpus_loads() -> None:
    assert FIXTURES, "no meter fixtures found"


@pytest.mark.parametrize("fx", FIXTURES, ids=IDS)
def test_ma1_metered_matches_expected_within_tolerance(fx: dict) -> None:
    """MA-1 — metered $ within ≤1% of the fixture's known cost."""
    bd = _metered(fx)
    expected = fx["expected_usd"]
    rel = abs(bd.total_usd - expected) / expected if expected else abs(bd.total_usd)
    assert rel <= TOLERANCE, f"{fx['name']}: metered {bd.total_usd} vs expected {expected} ({rel:.3%})"


@pytest.mark.parametrize("fx", FIXTURES, ids=IDS)
def test_ma2_breakdown_sums_to_total(fx: dict) -> None:
    """MA-2 — per-source breakdown is internally consistent."""
    bd = _metered(fx)
    assert bd.model_usd + bd.tool_usd == pytest.approx(bd.total_usd)
    if "expected_breakdown" in fx:
        eb = fx["expected_breakdown"]
        assert bd.model_usd == pytest.approx(eb["model_usd"], rel=TOLERANCE, abs=1e-9)
        assert bd.tool_usd == pytest.approx(eb["tool_usd"], rel=TOLERANCE, abs=1e-9)
        assert bd.spawn_usd == pytest.approx(eb["spawn_usd"], rel=TOLERANCE, abs=1e-9)


def test_ma3_subagent_cost_rolls_up_to_parent() -> None:
    """MA-3 — a multi-agent fixture attributes child spend to the triggering input."""
    fx = next(f for f in FIXTURES if f["run"].get("spawns"))
    bd = _metered(fx)
    assert bd.n_spawns >= 1
    assert bd.spawn_usd > 0
    assert bd.spawn_usd <= bd.total_usd  # spawn share is part of the total, not extra


def test_ma4_cache_and_reasoning_priced_distinctly() -> None:
    """MA-4 — 2026 token classes (reasoning/cache) are each priced, not lumped in."""
    fx = next(
        f for f in FIXTURES
        if any(c.get("reasoning_tokens") or c.get("cache_write_tokens") for c in f["run"]["calls"])
    )
    bd = _metered(fx)
    assert bd.total_usd == pytest.approx(fx["expected_usd"], rel=TOLERANCE)


def test_ma5_price_table_version_pinned() -> None:
    """MA-5 — every fixture pins the table it was priced against; a refresh that

    changes a fixture's cost fails MA-1 rather than silently shifting the oracle.
    """
    pt = PriceTable.default()
    for fx in FIXTURES:
        assert fx["price_table_version"] == pt.version


def test_ma1_real_invoice_corpus() -> None:
    """AC-1 — the ≤1% claim is only *proven* by real provider invoices.

    Skips (loudly) until the real corpus exists, so a synthetic-only green run is
    never mistaken for real-world validation.
    """
    real = [f for f in FIXTURES if f.get("source") == "real"]
    if len(real) < REQUIRED_REAL:
        pytest.skip(
            f"meter NOT YET validated against real invoices: {len(real)}/{REQUIRED_REAL} "
            "real fixtures present. Synthetic fixtures prove arithmetic only. "
            "Add real recorded runs (see tests/fixtures/meter/README.md) to prove NFR-8."
        )
    for fx in real:
        bd = _metered(fx)
        rel = abs(bd.total_usd - fx["expected_usd"]) / fx["expected_usd"]
        assert rel <= TOLERANCE, f"{fx['name']}: {rel:.3%} > {TOLERANCE:.0%}"
