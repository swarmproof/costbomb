"""MockworldTarget — the safe-by-default target (TEST-PLAN §8 SA-2, REQ-TA-4)."""

from __future__ import annotations

from costbomb.attacks.base import Input
from costbomb.cli import _build_target
from costbomb.meter import CostMeter
from costbomb.pricing import PriceTable
from costbomb.targets.base import ModelCall, RunRecord, TargetContext
from costbomb.targets.mockworld_target import MockworldTarget

MODEL = "anthropic:claude-opus-4-8"


def _handler_capturing(seen: dict):
    def handler(text: str, ctx: TargetContext) -> RunRecord:
        seen["allow_side_effects"] = ctx.allow_side_effects
        seen["mockworld"] = ctx.extra.get("mockworld")
        return RunRecord(calls=[ModelCall(model=MODEL, provider="anthropic", input_tokens=100)])

    return handler


def test_mockworld_is_safe_without_optin() -> None:
    seen: dict = {}
    target = MockworldTarget(_handler_capturing(seen), world="crm")
    # Even though the caller did NOT opt into side-effects, the run proceeds —
    # effects go to fakes, so it's safe by construction (NFR-5 / ADR-5).
    ctx = TargetContext(seed=1, allow_side_effects=False)
    trace = target.invoke(Input(text="x", attack_class="tool-storm"), ctx)
    assert CostMeter(PriceTable.default()).cost(trace).total_usd > 0
    assert seen["allow_side_effects"] is True  # adapter authorised the fake run
    assert seen["mockworld"] == "crm"


def test_mockworld_is_stub_without_package() -> None:
    # The mockworld package isn't installed in CI → marker-only mode, still works.
    target = MockworldTarget(_handler_capturing({}), world="crm")
    assert target.is_stub is True
    assert target.capabilities().can_spawn


def test_cli_factory_builds_mockworld_target() -> None:
    target = _build_target("mock:examples/demo_agent.py:handler")
    assert isinstance(target, MockworldTarget)
    trace = target.invoke(Input(text="retry until valid", attack_class="retry-loop"),
                          TargetContext(seed=1))
    assert CostMeter(PriceTable.default()).cost(trace).total_usd > 0
