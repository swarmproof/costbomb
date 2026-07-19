"""Attack library core — the ``AttackClass`` seed-strategy interface (REQ-AL-3/4).

Every cost-explosion class (the five SPEC classes, the ⊕ five, and community
classes) implements one interface and registers into one registry, so classes are
pluggable from v0.1 without forking core (ADR-7). The four methods map to the four
jobs a class does in the search loop:

* ``seeds()``      — hand-crafted starting inputs for the class.
* ``mutate()``     — produce a variant more likely to inflate spend (template by
                     default; LLM optional).
* ``applicable()`` — can the target even exhibit this class? (skip + report honestly)
* ``signal()``     — a cheap greybox heuristic (the code-coverage analog): reward a
                     mutation that caused more turns/tools/spawns before the full,
                     expensive dollar reading converges.
"""

from __future__ import annotations

import contextlib
import hashlib
from dataclasses import dataclass
from random import Random
from typing import Protocol, runtime_checkable

from costbomb._vendor.trace import GenAI, Swarmproof, Trace


@dataclass(frozen=True)
class Input:
    """One candidate input aimed at a cost-explosion class.

    ``text`` is the natural-language goal/prompt handed to the target. ``id`` is a
    deterministic content hash so findings and baselines reference an input stably
    (REQ-RP-1). Frozen so it is hashable and safe to key the seed queue on.
    """

    text: str
    attack_class: str
    seed: int = 0
    generation: int = 0
    parent_id: str | None = None
    meta: tuple[tuple[str, str], ...] = ()  # frozen key/value extras

    @property
    def id(self) -> str:
        h = hashlib.blake2b(f"{self.attack_class}\x00{self.text}".encode(), digest_size=6)
        return h.hexdigest()

    def child(self, text: str) -> Input:
        """A mutated descendant of this input (bumps generation, records lineage)."""
        return Input(
            text=text,
            attack_class=self.attack_class,
            seed=self.seed,
            generation=self.generation + 1,
            parent_id=self.id,
            meta=self.meta,
        )


@dataclass
class TargetCapabilities:
    """What a target can do — drives ``applicable()`` (REQ-AL-5).

    Discovered from the target (its toolset, whether it can spawn sub-agents, etc.)
    or declared by the adapter. A class whose precondition is unmet is skipped and
    the report says so, rather than producing meaningless findings.
    """

    has_tools: bool = True
    tool_names: tuple[str, ...] = ()
    priced_tool_names: tuple[str, ...] = ()  # subset with a nonzero fee
    can_spawn: bool = False
    supports_reasoning: bool = False
    accepts_documents: bool = True
    # ⊕ v0.2 preconditions — a class whose precondition is unmet is skipped and the
    # report says so (REQ-AL-5), so new classes never produce meaningless findings.
    uses_cache: bool = False  # prompt caching in play → cache-bust applies
    is_routed: bool = False  # a model router chooses the model → model-escalation applies
    has_retrieval: bool = False  # RAG/retrieval tool present → retrieval-amplification applies


@runtime_checkable
class Mutator(Protocol):
    """Optional LLM-assisted mutator (REQ-FE-4). Defaults to off/local (NFR-4)."""

    def rewrite(self, text: str, instruction: str) -> str: ...


@runtime_checkable
class AttackClass(Protocol):
    """The one interface every cost-explosion class implements."""

    name: str
    description: str
    references: list[str]

    def seeds(self, caps: TargetCapabilities) -> list[Input]: ...
    def mutate(self, parent: Input, rng: Random, llm: Mutator | None = None) -> Input: ...
    def applicable(self, caps: TargetCapabilities) -> bool: ...
    def signal(self, trace: Trace) -> float: ...


class BaseAttack:
    """Convenience base with sensible defaults; classes override what differs.

    Subclasses set ``name``/``description``/``references`` and implement ``seeds``
    and ``mutate``. ``applicable`` defaults to True and ``signal`` to 0.0.
    """

    name: str = "base"
    description: str = ""
    references: list[str] = []

    def seeds(self, caps: TargetCapabilities) -> list[Input]:  # pragma: no cover - abstract
        raise NotImplementedError

    def mutate(self, parent: Input, rng: Random, llm: Mutator | None = None) -> Input:  # pragma: no cover
        raise NotImplementedError

    def applicable(self, caps: TargetCapabilities) -> bool:
        return True

    def signal(self, trace: Trace) -> float:
        return 0.0

    # shared helpers for template mutation ----------------------------------

    def _seed_input(self, text: str, seed: int = 0) -> Input:
        return Input(text=text, attack_class=self.name, seed=seed)

    def _apply(self, parent: Input, text: str, rng: Random, llm: Mutator | None, hint: str) -> Input:
        """Return a child input, using the LLM mutator when supplied else template."""
        if llm is not None:
            # LLM failures fall back to the template text already computed (NFR-10).
            with contextlib.suppress(Exception):
                text = llm.rewrite(parent.text, hint)
        return parent.child(text)


class AttackRegistry:
    """Discoverable registry of attack classes (REQ-AL-4)."""

    def __init__(self) -> None:
        self._classes: dict[str, AttackClass] = {}

    def register(self, attack: AttackClass) -> AttackClass:
        self._classes[attack.name] = attack
        return attack

    def get(self, name: str) -> AttackClass:
        return self._classes[name]

    def all(self) -> list[AttackClass]:
        return [self._classes[k] for k in sorted(self._classes)]

    def names(self) -> list[str]:
        return sorted(self._classes)

    def applicable(self, caps: TargetCapabilities) -> list[AttackClass]:
        return [a for a in self.all() if a.applicable(caps)]

    def skipped(self, caps: TargetCapabilities) -> list[str]:
        return [a.name for a in self.all() if not a.applicable(caps)]


# The process-wide registry. Attack modules register into it on import; the
# standalone entrypoint imports `costbomb.attacks` to populate it.
registry = AttackRegistry()


# ---- signal helpers shared by classes (the greybox feedback quantities) ----


def count_turns(trace: Trace) -> int:
    """Model calls = agent turns (retry-loop / clarification-trap signal)."""
    return len(trace.by_operation("chat")) + len(
        [s for s in trace.spans if s.get(GenAI.USAGE_INPUT_TOKENS) is not None]
    )


def count_tool_calls(trace: Trace) -> int:
    """execute_tool spans (tool-storm signal)."""
    return len([s for s in trace.spans if s.get(GenAI.TOOL_NAME)])


def count_spawns(trace: Trace) -> int:
    """Non-root invoke_agent spans (recursion signal)."""
    return len(
        [
            s
            for s in trace.spans
            if s.get(GenAI.OPERATION_NAME) == "invoke_agent" and s.span_id != trace.root_span_id
        ]
    )


def total_input_tokens(trace: Trace) -> int:
    """Summed input tokens across turns (context-bomb / retrieval-amplification signal)."""
    return sum(int(s.get(GenAI.USAGE_INPUT_TOKENS, 0) or 0) for s in trace.spans)


def total_reasoning_tokens(trace: Trace) -> int:
    """Summed reasoning/thinking tokens (reasoning-inflation signal)."""
    return sum(int(s.get(Swarmproof.USAGE_REASONING_TOKENS, 0) or 0) for s in trace.spans)


def total_cache_write_tokens(trace: Trace) -> int:
    """Summed cache-write (miss) tokens (cache-bust signal)."""
    return sum(int(s.get(Swarmproof.USAGE_CACHE_WRITE_TOKENS, 0) or 0) for s in trace.spans)


def total_output_tokens(trace: Trace) -> int:
    """Summed output tokens (model-escalation proxy signal)."""
    return sum(int(s.get(GenAI.USAGE_OUTPUT_TOKENS, 0) or 0) for s in trace.spans)
