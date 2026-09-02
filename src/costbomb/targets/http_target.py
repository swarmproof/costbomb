"""HTTPTarget — POST inputs to an agent HTTP endpoint (REQ-TA-1).

Metered via the target's response ``usage`` fields (usage-field parse mode). Because
this hits a real system, it is **side-effect-bearing**: ``ctx.allow_side_effects``
must be set (``--allow-side-effects``), otherwise the run is refused (NFR-5). The
default safe target is mockworld, not this.
"""

from __future__ import annotations

from typing import Any

from costbomb._vendor.trace import Trace
from costbomb.attacks.base import Input, TargetCapabilities
from costbomb.errors import SideEffectError
from costbomb.targets.base import ModelCall, RunRecord, TargetContext, ToolCall, coerce_trace


def _parse_tool(t: Any) -> str | ToolCall:
    return ToolCall(**t) if isinstance(t, dict) else t


def _parse_run_record(payload: dict[str, Any]) -> RunRecord:
    """Parse a JSON payload into a RunRecord (recursive for spawns).

    A tool call may be a bare name or an object ``{"name", "key", "deduped"}``.
    """
    calls = [ModelCall(**c) for c in payload.get("calls", [])]
    tool_calls = [_parse_tool(t) for t in payload.get("tool_calls", [])]
    spawns = [_parse_run_record(s) for s in payload.get("spawns", [])]
    return RunRecord(calls=calls, tool_calls=tool_calls, spawns=spawns)


class HTTPTarget:
    def __init__(
        self,
        url: str,
        *,
        capabilities: TargetCapabilities | None = None,
        timeout: float = 60.0,
        input_field: str = "input",
    ) -> None:
        self.url = url
        self.timeout = timeout
        self.input_field = input_field
        self._caps = capabilities or TargetCapabilities()

    def capabilities(self) -> TargetCapabilities:
        return self._caps

    def invoke(self, input: Input, ctx: TargetContext) -> Trace:
        if not ctx.allow_side_effects:
            raise SideEffectError(
                f"HTTPTarget({self.url}) hits a real endpoint; pass --allow-side-effects "
                "to authorize it, or point costbomb at a MockworldTarget (the safe default)."
            )
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - optional dep
            raise ImportError("HTTPTarget needs the 'http' extra: pip install costbomb[http]") from exc

        resp = httpx.post(self.url, json={self.input_field: input.text}, timeout=self.timeout)
        resp.raise_for_status()
        payload = resp.json()
        record = _parse_run_record(payload.get("usage", payload))
        return coerce_trace(record, seed=ctx.seed, attack_class=input.attack_class)
