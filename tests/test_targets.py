"""Target adapters — the seam works both ways (TEST-PLAN §4 IT-5/10, §8 SA-2)."""

from __future__ import annotations

import pytest

from costbomb.attacks.base import Input, TargetCapabilities
from costbomb.errors import SideEffectError
from costbomb.meter import CostMeter
from costbomb.pricing import PriceTable
from costbomb.targets.base import ModelCall, RunRecord, TargetContext, coerce_trace
from costbomb.targets.http_target import HTTPTarget
from costbomb.targets.persona_target import PersonaTarget
from costbomb.targets.python_target import PythonTarget

MODEL = "anthropic:claude-opus-4-8"


def test_runrecord_meters_truthfully(prices: PriceTable) -> None:
    rec = RunRecord(
        calls=[ModelCall(model=MODEL, provider="anthropic", input_tokens=1000, output_tokens=100)],
        tool_calls=["premium_api", "premium_api"],
        spawns=[RunRecord(calls=[ModelCall(model=MODEL, provider="anthropic", input_tokens=500)])],
    )
    bd = CostMeter(prices).cost(rec.to_trace(seed=1))
    expected = (1000 * 3e-6 + 100 * 1.5e-5) + (500 * 3e-6) + 2 * 0.02
    assert bd.total_usd == pytest.approx(expected)
    assert bd.n_spawns == 1 and bd.n_tool_calls == 2


def test_it_5_python_target_invoke_returns_trace(prices: PriceTable) -> None:
    def handler(text: str, ctx=None) -> RunRecord:  # type: ignore[no-untyped-def]
        return RunRecord(calls=[ModelCall(model=MODEL, provider="anthropic",
                                          input_tokens=len(text) * 10, output_tokens=20)])

    target = PythonTarget(handler, capabilities=TargetCapabilities(has_tools=False))
    trace = target.invoke(Input(text="fuzz me", attack_class="retry-loop"), TargetContext(seed=7))
    assert CostMeter(prices).cost(trace).total_usd > 0


def test_it_10_persona_target_bridges_a_driver(prices: PriceTable) -> None:
    # A fake stampede driver — proves the Target seam is symmetric (ARCHITECTURE §6).
    def driver(text: str, ctx: TargetContext) -> RunRecord:
        return RunRecord(calls=[ModelCall(model=MODEL, provider="anthropic", input_tokens=2000)])

    target = PersonaTarget(driver)
    trace = target.invoke(Input(text="x", attack_class="recursion"), TargetContext(seed=1))
    assert CostMeter(prices).cost(trace).total_usd == pytest.approx(2000 * 3e-6)
    assert target.capabilities().can_spawn


def test_sa_2_http_target_refuses_without_side_effect_optin() -> None:
    target = HTTPTarget("https://example.com/agent")
    ctx = TargetContext(seed=1, allow_side_effects=False)
    with pytest.raises(SideEffectError):
        target.invoke(Input(text="x", attack_class="tool-storm"), ctx)


def test_coerce_trace_rejects_bad_return() -> None:
    with pytest.raises(TypeError):
        coerce_trace("not a trace", seed=1)  # type: ignore[arg-type]
