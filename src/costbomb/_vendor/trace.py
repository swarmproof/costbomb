"""trace-format — a profile of the OpenTelemetry GenAI semantic conventions.

VENDORED from ``stampede/trace/schema.py`` (the authoritative source, ADR-1/ADR-8).
Standard ``gen_ai.*`` attribute names are kept exactly as OTel defines them; the
``swarmproof.*`` namespace layers the extensions OTel has no concept of (per-span
USD cost, persona, attack metadata). costbomb adds only cost-specific keys, all
inside ``swarmproof.*`` — it never invents a top-level namespace (NFR-9).

IDs are generated deterministically from ``(seed, counter)`` via blake2b, never
from wall-clock or ``random`` — that is what makes seeded searches bit-identical
(NFR-2).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class GenAI:
    """Standard OTel GenAI semantic-convention attribute keys (unchanged names)."""

    OPERATION_NAME = "gen_ai.operation.name"  # "chat" | "execute_tool" | "invoke_agent"
    PROVIDER_NAME = "gen_ai.provider.name"  # "anthropic" | "openai" | "ollama"
    REQUEST_MODEL = "gen_ai.request.model"
    REQUEST_TEMPERATURE = "gen_ai.request.temperature"
    USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
    USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
    AGENT_ID = "gen_ai.agent.id"
    AGENT_NAME = "gen_ai.agent.name"
    AGENT_DESCRIPTION = "gen_ai.agent.description"
    TOOL_NAME = "gen_ai.tool.name"
    TOOL_CALL_ID = "gen_ai.tool.call.id"
    TOOL_TYPE = "gen_ai.tool.type"


class Swarmproof:
    """The ``swarmproof.*`` extension namespace — additions over OTel GenAI.

    The first block mirrors stampede's registry verbatim. The ``# costbomb`` block
    is costbomb's cost extension: token classes OTel has not standardized (reasoning,
    cache read/write) and the per-span cost breakdown the meter and reporter share.
    """

    SPAN_SIDE = "swarmproof.span.side"  # "agent" | "target"
    RUN_ID = "swarmproof.run.id"
    RUN_SEED = "swarmproof.run.seed"
    PERSONA_NAME = "swarmproof.persona.name"
    PERSONA_PACK = "swarmproof.persona.pack"
    AGENT_TEMPERAMENT = "swarmproof.agent.temperament"
    GOAL_ID = "swarmproof.goal.id"
    DECISION_REASONING = "swarmproof.decision.reasoning"
    COST_USD = "swarmproof.cost.usd"
    RECOVERY_EXACTLY_ONCE = "swarmproof.recovery.exactly_once"
    AGENT_STATE = "swarmproof.agent.state"

    # --- costbomb cost extension (still swarmproof.*, ADR-2 / REQ-CM-2/6) ---
    USAGE_REASONING_TOKENS = "swarmproof.usage.reasoning_tokens"
    USAGE_CACHE_READ_TOKENS = "swarmproof.usage.cache_read_tokens"
    USAGE_CACHE_WRITE_TOKENS = "swarmproof.usage.cache_write_tokens"
    COST_SOURCE = "swarmproof.cost.source"  # "model" | "tool" | "spawn"
    COST_ESTIMATED = "swarmproof.cost.estimated"  # True → not a paid reading
    TOOL_PRICE_USD = "swarmproof.tool.price_usd"  # per-tool-call fee at run time
    ATTACK_CLASS = "swarmproof.attack.class"  # which AttackClass produced the input
    ATTACK_SEED = "swarmproof.attack.seed"


class SpanKind(StrEnum):
    """OTel span kinds. CLIENT = agent-side call, SERVER = target handler."""

    INTERNAL = "INTERNAL"
    CLIENT = "CLIENT"
    SERVER = "SERVER"


class CostSource(StrEnum):
    """The three cost sources the meter sums over (ADR-2)."""

    MODEL = "model"
    TOOL = "tool"
    SPAWN = "spawn"


REDACT_KEYS = ("api_key", "authorization", "rpc_url", "secret", "token", "password")
REDACT_PLACEHOLDER = "«redacted»"


def _hex(seed: int, counter: int, nbytes: int) -> str:
    """Deterministic id: blake2b over ``seed:counter`` → ``nbytes`` of hex."""
    h = hashlib.blake2b(f"{seed}:{counter}".encode(), digest_size=nbytes)
    return h.hexdigest()


def new_trace_id(seed: int, counter: int) -> str:
    """A 16-byte (32 hex char) W3C trace-id, deterministic in (seed, counter)."""
    return _hex(seed, counter, 16)


def new_span_id(seed: int, counter: int) -> str:
    """An 8-byte (16 hex char) W3C span-id, deterministic in (seed, counter)."""
    return _hex(seed ^ 0x5A5A5A5A, counter, 8)


def _redact(key: str, value: Any) -> Any:
    lowered = key.lower()
    # Usage token *counts* (gen_ai.usage.*_tokens, swarmproof.usage.*_tokens) are
    # numeric telemetry, never secrets — exempt them so the "token" denylist entry
    # (meant for auth_token/access_token) doesn't clobber `input_tokens`.
    if ".usage." in lowered or lowered.endswith("_tokens"):
        return value
    if any(bad in lowered for bad in REDACT_KEYS):
        return REDACT_PLACEHOLDER
    return value


@dataclass
class Span:
    """One trace-format span. Maps 1:1 onto an OTel span at export time.

    ``attributes`` uses the exact ``gen_ai.*`` / ``swarmproof.*`` keys above. Token
    counts and per-span cost live here; the meter reads them, never guesses.
    """

    name: str
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    kind: SpanKind = SpanKind.INTERNAL
    service_name: str = "costbomb"
    start_tick: int = 0
    end_tick: int = 0
    attributes: dict[str, Any] = field(default_factory=dict)
    status: str = "OK"  # "OK" | "ERROR"
    status_message: str = ""

    def set(self, key: str, value: Any) -> Span:
        """Set an attribute, redacting anything that looks secret (NFR-SEC)."""
        self.attributes[key] = _redact(key, value)
        return self

    def get(self, key: str, default: Any = None) -> Any:
        return self.attributes.get(key, default)

    @property
    def duration_ticks(self) -> int:
        return max(0, self.end_tick - self.start_tick)


@dataclass
class Trace:
    """The spans of a single agent run, rooted at the triggering input.

    This is a convenience container over the vendored ``Span`` model — *not* a new
    format. The spans are the OTel GenAI profile; ``Trace`` just groups the ones the
    meter must sum and roll up for one ``Target.invoke(input)`` (REQ-CM-4).
    """

    root_span_id: str
    spans: list[Span] = field(default_factory=list)
    # Set True when any span's cost is estimated rather than metered from real usage
    # (wire-estimate fallback or dry-run). Surfaces in the report as `estimated`.
    estimated: bool = False

    def add(self, span: Span) -> Span:
        self.spans.append(span)
        return span

    def children_of(self, span_id: str) -> list[Span]:
        return [s for s in self.spans if s.parent_span_id == span_id]

    def by_operation(self, operation: str) -> list[Span]:
        return [s for s in self.spans if s.get(GenAI.OPERATION_NAME) == operation]
