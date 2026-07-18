"""CI gate + baseline — regression, price-drift separation (TEST-PLAN §4 IT-3/4, §5 E2E-2/3)."""

from __future__ import annotations

from costbomb.ci import Baseline, gate
from costbomb.engine import FuzzEngine, SearchConfig
from costbomb.pricing import PriceTable
from costbomb.targets.fake import FakeTarget


def _run(target, prices, seed=1337):
    return FuzzEngine(target, prices=prices, config=SearchConfig(seed=seed, max_spend_usd=2.0, k=3)).run()


def test_it_3_baseline_diff_red_and_green(prices: PriceTable) -> None:
    base = Baseline.from_findings(_run(FakeTarget(), prices), tolerance=0.10)

    # unchanged agent → green
    g = gate(_run(FakeTarget(), prices), prices=prices, baseline=base, fail_on_regression=True)
    assert g.passed and g.exit_code == 0

    # more-expensive agent → red, names regressed classes
    worse = FakeTarget(base_input_tokens=6000)
    g2 = gate(_run(worse, prices), prices=prices, baseline=base, fail_on_regression=True)
    assert not g2.passed and g2.exit_code == 1
    assert g2.regressions


def test_it_4_price_drift_separated_from_regression(prices: PriceTable) -> None:
    base = Baseline.from_findings(_run(FakeTarget(), prices), tolerance=0.10)

    # 2x price hike, SAME agent behaviour → must stay green (baseline re-priced)
    hiked = PriceTable.default()
    for m in hiked.models.values():
        m.input_cost_per_token *= 2
        m.output_cost_per_token *= 2
    for t in hiked.tools.values():
        t.price_per_call *= 2
    g = gate(_run(FakeTarget(), hiked), prices=hiked, baseline=base, fail_on_regression=True)
    assert g.passed, "price hike must not fail the build (REQ-CI-3)"
    assert g.price_drift_absorbed


def test_budget_breach_fails(prices: PriceTable) -> None:
    rf = _run(FakeTarget(), prices)
    g = gate(rf, prices=prices, budget_usd=0.001, fail_on_regression=False)
    assert not g.passed
    assert g.over_budget


def test_baseline_roundtrip_serialization(tmp_path, prices: PriceTable) -> None:
    rf = _run(FakeTarget(), prices)
    base = Baseline.from_findings(rf, tolerance=0.15)
    path = tmp_path / ".costbomb-baseline.json"
    base.save(path)
    loaded = Baseline.load(path)
    assert loaded.tolerance == 0.15
    assert set(loaded.per_class) == set(base.per_class)
    # traces are stored so the gate can reprice (REQ-CI-3)
    assert any(e.repriceable for e in loaded.per_class.values())
