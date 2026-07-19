"""Shared fixtures. The pyramid leans on FakeTarget + scripted traces (TEST-PLAN §1)."""

from __future__ import annotations

import pytest

from costbomb._vendor.trace import Trace
from costbomb.attacks.base import Input, TargetCapabilities
from costbomb.pricing import PriceTable
from costbomb.targets.base import TargetContext
from costbomb.tracebuild import TraceBuilder


@pytest.fixture
def prices() -> PriceTable:
    return PriceTable.default()


class ConstTarget:
    """A target whose every run costs a fixed number of model tokens.

    Lets tests script exact per-run spend (IT-2 own-budget cap) independent of the
    input, so the cap behaviour is provable without a real model.
    """

    def __init__(self, *, input_tokens: int, model: str = "anthropic:claude-opus-4-8") -> None:
        self.input_tokens = input_tokens
        self.model = model

    def capabilities(self) -> TargetCapabilities:
        return TargetCapabilities(has_tools=True, can_spawn=False, accepts_documents=True)

    def invoke(self, input: Input, ctx: TargetContext) -> Trace:
        tb = TraceBuilder(ctx.seed, attack_class=input.attack_class)
        root = tb.root()
        tb.chat(root, model=self.model, provider="anthropic",
                input_tokens=self.input_tokens, output_tokens=0)
        return tb.build()


@pytest.fixture
def const_target_factory():
    return ConstTarget
