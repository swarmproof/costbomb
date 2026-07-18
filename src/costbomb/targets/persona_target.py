"""PersonaTarget — the embedded (v0.1) path into stampede (REQ-TA-3, ADR-3).

In the embedded launch, costbomb ships as stampede's ``adversarial:economic`` cohort:
the fuzz engine drives a stampede agent via stampede's **agent-driver**, and the
resulting spend flows into the shared ``RunReport``. That wiring lives on the
stampede side (ARCHITECTURE §6.2) — stampede imports ``costbomb_core`` and supplies
the driver. Here we provide the thin bridge so the ``Target`` seam is demonstrably
symmetric (IT-10): give it any ``driver(input_text, ctx) -> Trace | RunRecord`` and
it becomes a costbomb ``Target``.
"""

from __future__ import annotations

from collections.abc import Callable

from costbomb._vendor.trace import Trace
from costbomb.attacks.base import Input, TargetCapabilities
from costbomb.targets.base import RunRecord, TargetContext, coerce_trace

Driver = Callable[[str, TargetContext], "Trace | RunRecord"]


class PersonaTarget:
    def __init__(
        self,
        driver: Driver,
        *,
        persona: str = "adversarial:economic",
        capabilities: TargetCapabilities | None = None,
    ) -> None:
        self._driver = driver
        self.persona = persona
        # A stampede persona can spawn and use tools; default caps reflect that.
        self._caps = capabilities or TargetCapabilities(
            has_tools=True, can_spawn=True, accepts_documents=True
        )

    def capabilities(self) -> TargetCapabilities:
        return self._caps

    def invoke(self, input: Input, ctx: TargetContext) -> Trace:
        result = self._driver(input.text, ctx)
        return coerce_trace(result, seed=ctx.seed, attack_class=input.attack_class)
