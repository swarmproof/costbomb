"""TraceBuilder — mint OTel-GenAI-profile spans deterministically.

Shared by ``FakeTarget`` and the target adapters to assemble a :class:`Trace` for
one agent run. IDs come from ``(seed, counter)`` (blake2b) exactly like stampede's
Tracer, so the same input under the same seed yields a bit-identical trace (NFR-2).
Ticks are virtual, not wall-clock, for the same reason.
"""

from __future__ import annotations

from costbomb._vendor.trace import (
    GenAI,
    Span,
    SpanKind,
    Swarmproof,
    Trace,
    new_span_id,
    new_trace_id,
)


class TraceBuilder:
    def __init__(self, seed: int, *, run_id: str = "costbomb", attack_class: str = "") -> None:
        self.seed = seed
        self.run_id = run_id
        self.attack_class = attack_class
        self._counter = 0
        self._trace_id = new_trace_id(seed, self._next())
        self._spans: list[Span] = []
        self._tick = 0
        self._root_id: str | None = None

    def _next(self) -> int:
        self._counter += 1
        return self._counter

    def _tick_now(self) -> int:
        self._tick += 1
        return self._tick

    def _span(self, name: str, kind: SpanKind, parent: Span | None, operation: str) -> Span:
        span = Span(
            name=name,
            trace_id=self._trace_id,
            span_id=new_span_id(self.seed, self._next()),
            parent_span_id=parent.span_id if parent else None,
            kind=kind,
            service_name="costbomb",
            start_tick=self._tick_now(),
        )
        span.set(GenAI.OPERATION_NAME, operation)
        span.set(Swarmproof.RUN_ID, self.run_id)
        span.set(Swarmproof.RUN_SEED, self.seed)
        if self.attack_class:
            span.set(Swarmproof.ATTACK_CLASS, self.attack_class)
        span.end_tick = self._tick_now()
        self._spans.append(span)
        return span

    def root(self, *, name: str = "agent") -> Span:
        """The root ``invoke_agent`` span the triggering input attributes to."""
        span = self._span(name, SpanKind.INTERNAL, None, "invoke_agent")
        self._root_id = span.span_id
        return span

    def chat(
        self,
        parent: Span,
        *,
        model: str,
        provider: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        reasoning_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> Span:
        span = self._span("chat", SpanKind.CLIENT, parent, "chat")
        span.set(GenAI.REQUEST_MODEL, model)
        if provider:
            span.set(GenAI.PROVIDER_NAME, provider)
        span.set(GenAI.USAGE_INPUT_TOKENS, input_tokens)
        span.set(GenAI.USAGE_OUTPUT_TOKENS, output_tokens)
        if reasoning_tokens:
            span.set(Swarmproof.USAGE_REASONING_TOKENS, reasoning_tokens)
        if cache_read_tokens:
            span.set(Swarmproof.USAGE_CACHE_READ_TOKENS, cache_read_tokens)
        if cache_write_tokens:
            span.set(Swarmproof.USAGE_CACHE_WRITE_TOKENS, cache_write_tokens)
        return span

    def tool(self, parent: Span, *, tool_name: str) -> Span:
        span = self._span("execute_tool", SpanKind.CLIENT, parent, "execute_tool")
        span.set(GenAI.TOOL_NAME, tool_name)
        return span

    def spawn(self, parent: Span, *, name: str = "sub-agent") -> Span:
        """A spawned sub-agent (non-root ``invoke_agent``); attach child spans to it."""
        return self._span(name, SpanKind.INTERNAL, parent, "invoke_agent")

    def build(self, *, estimated: bool = False) -> Trace:
        if self._root_id is None:  # pragma: no cover - defensive
            raise ValueError("TraceBuilder.build() called before root()")
        return Trace(root_span_id=self._root_id, spans=self._spans, estimated=estimated)
