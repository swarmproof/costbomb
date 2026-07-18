"""Target adapters — the embedded/standalone seam (ADR-3, REQ-TA-5).

``costbomb-core`` knows exactly one thing about the system under test::

    Target.invoke(input, ctx) -> Trace

That single contract is what lets the *same* engine run embedded inside stampede
(``PersonaTarget`` driving a stampede agent) and standalone behind the CLI
(``HTTP``/``Python``/``Mockworld`` targets). Extraction from stampede is therefore
a packaging move, not a rewrite.

Note this is an *agent-run-level* seam — one ``invoke`` is one whole agent run and
returns its full cost trace. It is deliberately distinct from stampede's
*tool-call-level* ``TargetAdapter.invoke(ToolCall)``; ``PersonaTarget`` bridges the
two by driving a stampede agent and metering the run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from costbomb._vendor.trace import Trace
from costbomb.attacks.base import Input, TargetCapabilities
from costbomb.tracebuild import TraceBuilder


@dataclass
class TargetContext:
    """Per-invocation context handed to a target (seedable, REQ-FE-6)."""

    seed: int = 0
    run_index: int = 0  # which of the k repeated runs (fitness is p95 over k)
    attack_class: str = ""
    allow_side_effects: bool = False  # NFR-5: real side-effects require opt-in
    extra: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class Target(Protocol):
    """The one interface the fuzz engine drives."""

    def capabilities(self) -> TargetCapabilities: ...
    def invoke(self, input: Input, ctx: TargetContext) -> Trace: ...


# --- the honest instrumentation contract for non-stampede targets ----------


@dataclass
class ModelCall:
    """One model call an agent made, as it would report its own usage."""

    model: str
    provider: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class RunRecord:
    """What a Python/HTTP target returns so costbomb can meter it truthfully.

    This is the ``usage-field parse`` attachment mode (REQ-CM-5b): the agent tells
    costbomb what it spent — model calls, tool calls, and (recursively) spawned
    sub-agents. costbomb converts it to a :class:`Trace`; the meter does the rest.
    An agent already emitting the OTel GenAI trace can return a ``Trace`` directly.
    """

    calls: list[ModelCall] = field(default_factory=list)
    tool_calls: list[str] = field(default_factory=list)
    spawns: list[RunRecord] = field(default_factory=list)

    def to_trace(self, *, seed: int, attack_class: str = "", estimated: bool = False) -> Trace:
        tb = TraceBuilder(seed, attack_class=attack_class)
        root = tb.root()
        self._emit(tb, root)
        return tb.build(estimated=estimated)

    def _emit(self, tb: TraceBuilder, parent) -> None:  # type: ignore[no-untyped-def]
        for call in self.calls:
            tb.chat(
                parent,
                model=call.model,
                provider=call.provider,
                input_tokens=call.input_tokens,
                output_tokens=call.output_tokens,
                reasoning_tokens=call.reasoning_tokens,
                cache_read_tokens=call.cache_read_tokens,
                cache_write_tokens=call.cache_write_tokens,
            )
        for tool in self.tool_calls:
            tb.tool(parent, tool_name=tool)
        for sub in self.spawns:
            sub_root = tb.spawn(parent)
            sub._emit(tb, sub_root)


def coerce_trace(
    result: Trace | RunRecord, *, seed: int, attack_class: str = "", estimated: bool = False
) -> Trace:
    """Accept either a ready ``Trace`` or a ``RunRecord`` and return a ``Trace``."""
    if isinstance(result, Trace):
        return result
    if isinstance(result, RunRecord):
        return result.to_trace(seed=seed, attack_class=attack_class, estimated=estimated)
    raise TypeError(
        f"target must return a Trace or RunRecord, got {type(result).__name__}. "
        "Instrument your agent to report its usage (see costbomb.targets.RunRecord)."
    )
