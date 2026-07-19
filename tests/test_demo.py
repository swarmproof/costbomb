"""E2E-1 — the signature demo: a benign agent cracked automatically (TEST-PLAN §5)."""

from __future__ import annotations

import pytest

from costbomb.attacks.base import Input, TargetCapabilities
from costbomb.engine import FuzzEngine, SearchConfig
from costbomb.meter import CostMeter
from costbomb.pricing import PriceTable
from costbomb.targets.base import TargetContext
from costbomb.targets.python_target import PythonTarget

DEMO = "examples/demo_agent.py:handler"
CAPS = TargetCapabilities(has_tools=True, can_spawn=False, accepts_documents=True)


def _demo_target() -> PythonTarget:
    return PythonTarget(DEMO, capabilities=CAPS)


@pytest.mark.parametrize("seed", [1, 42, 1337, 2024])
def test_e2e_1_demo_cracked_over_50x_under_cap(prices: PriceTable, seed: int) -> None:
    cfg = SearchConfig(seed=seed, max_spend_usd=2.0, k=5)
    rf = FuzzEngine(_demo_target(), prices=prices, config=cfg, run_id=f"demo-{seed}").run()

    assert rf.amplification_factor >= 50.0, f"seed {seed}: only {rf.amplification_factor:.1f}×"
    assert rf.own_spend_usd <= 2.0, f"seed {seed}: cap breached ${rf.own_spend_usd}"
    # recursion must be honestly skipped — the demo agent cannot spawn (REQ-AL-5)
    assert "recursion" in rf.classes_skipped


def test_e2e_1_repro_reproduces_the_spend(prices: PriceTable) -> None:
    rf = FuzzEngine(_demo_target(), prices=prices, config=SearchConfig(seed=1337, k=5)).run()
    top = rf.findings[0]

    # Re-run the exact reported repro input on the demo agent — it must reproduce
    # a spend within the finding's sample band (deterministic agent → exact).
    target = _demo_target()
    inp = Input(text=top.repro["input"], attack_class=top.attack_class, seed=top.repro["seed"])
    trace = target.invoke(inp, TargetContext(seed=top.repro["seed"]))
    reproduced = CostMeter(prices).cost(trace).total_usd
    assert min(top.samples_usd) <= reproduced <= max(top.samples_usd) * 1.01
