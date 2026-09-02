"""Proxy meter — zero-instrumentation metering of a real agent (REQ-CM-5c).

The lowest-friction way to meter an agent you didn't write: point its model
``base_url`` at costbomb and every LLM call flows through here. costbomb reads the
provider's own ``usage`` off each response, prices it, and attributes it to the run
the fuzzer is currently driving — **no code changes to the agent, no log-pulling.**

This module is the *pure* core: parse OpenAI- and Anthropic-shaped responses into
metered spans and bracket them into a :class:`Trace`. The forwarding HTTP server
(``costbomb proxy``) is a thin shell around it (see ``proxy_server.py``); everything
that decides *dollars* lives here and is unit-tested against recorded payloads.
"""

from __future__ import annotations

import time
from typing import Any

from costbomb._vendor.trace import Span, Trace
from costbomb.meter import CostBreakdown, CostMeter
from costbomb.pricing import PriceTable
from costbomb.targets.base import ModelCall
from costbomb.tracebuild import TraceBuilder


def _model_key(model: str, provider: str) -> str:
    return model if ":" in model else f"{provider}:{model}"


def parse_openai_usage(response: dict[str, Any]) -> ModelCall:
    """Read token usage from an OpenAI-compatible chat/completions response.

    Handles the 2026 fields: ``prompt_tokens_details.cached_tokens`` and
    ``completion_tokens_details.reasoning_tokens``. Works for any OpenAI-compatible
    provider (OpenAI, Ollama's ``/v1``, together, …); pass ``provider`` to key the
    price table correctly.
    """
    usage = response.get("usage", {}) or {}
    prompt = int(usage.get("prompt_tokens", 0) or 0)
    completion = int(usage.get("completion_tokens", 0) or 0)
    cached = int((usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0)
    reasoning = int((usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) or 0)
    provider = response.get("_provider", "openai")
    model = response.get("model", "")
    # Cached prompt tokens are billed at the cache-read rate, not the input rate.
    return ModelCall(
        model=_model_key(model, provider),
        provider=provider,
        input_tokens=max(0, prompt - cached),
        output_tokens=completion,
        reasoning_tokens=reasoning,
        cache_read_tokens=cached,
    )


def parse_anthropic_usage(response: dict[str, Any]) -> ModelCall:
    """Read token usage from an Anthropic Messages response.

    Maps ``cache_read_input_tokens`` → cache-read and ``cache_creation_input_tokens``
    → cache-write. (Anthropic accounts thinking tokens within ``output_tokens``, so
    there is no separate reasoning field to split out.)
    """
    usage = response.get("usage", {}) or {}
    provider = response.get("_provider", "anthropic")
    model = response.get("model", "")
    return ModelCall(
        model=_model_key(model, provider),
        provider=provider,
        input_tokens=int(usage.get("input_tokens", 0) or 0),
        output_tokens=int(usage.get("output_tokens", 0) or 0),
        cache_read_tokens=int(usage.get("cache_read_input_tokens", 0) or 0),
        cache_write_tokens=int(usage.get("cache_creation_input_tokens", 0) or 0),
    )


def detect_and_parse(response: dict[str, Any]) -> ModelCall:
    """Auto-detect the response shape and parse its usage."""
    usage = response.get("usage", {}) or {}
    if "choices" in response or "prompt_tokens" in usage:
        return parse_openai_usage(response)
    if "input_tokens" in usage:
        return parse_anthropic_usage(response)
    raise ValueError("unrecognized LLM response shape: no OpenAI/Anthropic usage found")


class ProxyMeter:
    """Brackets a run's LLM calls into a metered :class:`Trace`.

    Usage::

        pm = ProxyMeter(PriceTable.default())
        pm.start_run(attack_class="retry-loop")
        # ... every model response the agent gets is fed to pm.record(...) ...
        trace = pm.finish_run()
        cost  = pm.cost(trace)

    ``record`` accepts a raw provider response dict (as the forwarding server sees
    it) or a ready :class:`ModelCall`.
    """

    def __init__(self, prices: PriceTable, *, seed: int = 0, run_id: str = "proxy") -> None:
        self.prices = prices
        self.seed = seed
        self.run_id = run_id
        self.meter = CostMeter(prices)
        self._tb: TraceBuilder | None = None
        self._root: Span | None = None
        self._t0: float = 0.0
        self.calls_recorded = 0

    def start_run(self, *, attack_class: str = "") -> None:
        self._tb = TraceBuilder(self.seed, run_id=self.run_id, attack_class=attack_class)
        self._root = self._tb.root()
        self._t0 = time.perf_counter()  # real wall-clock → infra cost (Delivery 2)

    def record(self, response: dict[str, Any] | ModelCall) -> ModelCall:
        """Record one model call into the current run (auto-starts a run if needed)."""
        if self._tb is None or self._root is None:
            self.start_run()
        assert self._tb is not None and self._root is not None
        call = response if isinstance(response, ModelCall) else detect_and_parse(response)
        self._tb.chat(
            self._root,
            model=call.model,
            provider=call.provider,
            input_tokens=call.input_tokens,
            output_tokens=call.output_tokens,
            reasoning_tokens=call.reasoning_tokens,
            cache_read_tokens=call.cache_read_tokens,
            cache_write_tokens=call.cache_write_tokens,
        )
        self.calls_recorded += 1
        return call

    def record_tool(self, tool_name: str) -> None:
        """Record a tool call in the current run (if the proxy sees tool invocations)."""
        if self._tb is None or self._root is None:
            self.start_run()
        assert self._tb is not None and self._root is not None
        self._tb.tool(self._root, tool_name=tool_name)

    def finish_run(self) -> Trace:
        """Close the current run and return its metered trace."""
        if self._tb is None or self._root is None:
            self.start_run()
        assert self._tb is not None
        trace = self._tb.build(duration_s=max(0.0, time.perf_counter() - self._t0))
        self._tb = None
        self._root = None
        return trace

    def cost(self, trace: Trace) -> CostBreakdown:
        return self.meter.cost(trace)
