"""MockworldTarget — the safe-by-default target (REQ-TA-4, NFR-5, ADR-5).

Fuzzing for *maximum tool calls* is dangerous against a real system: `tool-storm`
and `recursion` could fire real charges or emails. So costbomb's default posture is
side-effect-free — the agent runs against [mockworld](https://github.com/swarmproof/mockworld)'s
fake services (fake Stripe, Gmail, exchange, …) where side-effects hit fakes, not
production. Unlike `HTTPTarget`, this needs **no** `--allow-side-effects`, because by
construction nothing real is touched.

The agent harness is supplied the same way as `PythonTarget` (a `module:func`); this
adapter routes it at mockworld's fakes via the run context. Full fake-service wiring
lands when mockworld ships as a package; until then the adapter runs the handler with
mockworld's world marked in the context (and, when the `mockworld` package is present,
hands it the live fake registry).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from costbomb._vendor.trace import Trace
from costbomb.attacks.base import Input, TargetCapabilities
from costbomb.targets.base import TargetContext, coerce_trace
from costbomb.targets.python_target import _load_handler


def _try_load_mockworld(world: str) -> Any | None:
    """Best-effort import of the mockworld fake-service registry for ``world``."""
    try:
        import mockworld
    except ImportError:
        return None
    factory = getattr(mockworld, "world", None) or getattr(mockworld, "World", None)
    return factory(world) if callable(factory) else None


class MockworldTarget:
    def __init__(
        self,
        handler: str | Callable[..., Any],
        *,
        world: str = "crm",
        capabilities: TargetCapabilities | None = None,
    ) -> None:
        self._handler = _load_handler(handler) if isinstance(handler, str) else handler
        self.world = world
        self._mock = _try_load_mockworld(world)
        # Side-effect-bearing classes are safe here (fakes), so tools/spawn are on.
        self._caps = capabilities or TargetCapabilities(
            has_tools=True, can_spawn=True, accepts_documents=True
        )

    @property
    def is_stub(self) -> bool:
        """True when the mockworld package isn't installed (marker-only mode)."""
        return self._mock is None

    def capabilities(self) -> TargetCapabilities:
        return self._caps

    def invoke(self, input: Input, ctx: TargetContext) -> Trace:
        # Effects go to fakes → the run is authorised without --allow-side-effects
        # (NFR-5). The world (and live fake registry, if present) ride in the context.
        extra = {**ctx.extra, "mockworld": self.world}
        if self._mock is not None:
            extra["mockworld_registry"] = self._mock
        run_ctx = replace(ctx, allow_side_effects=True, extra=extra)
        try:
            result = self._handler(input.text, run_ctx)
        except TypeError:
            result = self._handler(input.text)
        return coerce_trace(result, seed=ctx.seed, attack_class=input.attack_class)
