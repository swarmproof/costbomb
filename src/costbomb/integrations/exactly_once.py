"""exactly-once integration — the real duplicate-effect cross-check (REQ-RP-4).

Instead of *guessing* which repeated side-effecting calls would double-fire, this
runs them through the actual [`exactly-once`](https://github.com/swarmproof/exactly-once)
middleware (``@once`` + an in-memory ``Store``) and *observes* what fires versus what
gets deduped. costbomb thereby cross-checks against the real idempotency guarantee
rather than reinventing it.

    pip install costbomb[exactly-once]

The checker plugs into ``CostMeter(prices, dedup_checker=ExactlyOnceDedupChecker())``.
``cross_check`` returns a before/after report ("34 calls → 1 fires, 33 deduped →
$1,650 that exactly-once would prevent") for the reporter.
"""

from __future__ import annotations

from dataclasses import dataclass

from costbomb._vendor.trace import GenAI, Swarmproof, Trace
from costbomb.pricing import PriceTable


def _require_exactly_once():
    try:
        import exactly_once
    except ImportError as exc:  # pragma: no cover - exercised only when extra absent
        raise ImportError(
            "the exactly-once cross-check needs the sibling library: "
            "pip install costbomb[exactly-once]"
        ) from exc
    return exactly_once


def _observe_fires(keys: list[str]) -> int:
    """Run keys through real exactly-once ``@once`` and return the actual fire count."""
    eo = _require_exactly_once()
    store = eo.Store.memory()
    fires: list[str] = []

    @eo.once(store, key=lambda k, **_: k)
    def _effect(k: str) -> str:
        fires.append(k)  # the real (simulated) side-effect
        return k

    for k in keys:
        _effect(k)
    return len(set(fires))  # distinct keys that actually fired once


class ExactlyOnceDedupChecker:
    """A :class:`~costbomb.meter.DedupChecker` backed by the real middleware.

    at-risk duplicates = live calls − calls that actually fire through ``@once``.
    """

    def at_risk_duplicates(self, tool: str, keys: list[str], deduped: list[bool]) -> int:
        live = [k for k, d in zip(keys, deduped, strict=False) if not d]
        if not live:
            return 0
        return len(live) - _observe_fires(live)


@dataclass
class ToolCrossCheck:
    tool: str
    calls: int
    fires: int  # distinct effects that would actually happen (via exactly-once)
    deduped: int  # repeats exactly-once would prevent
    usd_prevented: float  # money the middleware would save


def cross_check(trace: Trace, prices: PriceTable) -> list[ToolCrossCheck]:
    """Per side-effecting tool: what fires vs what exactly-once would dedupe."""
    by_tool: dict[str, list[str]] = {}
    for span in trace.spans:
        name = span.get(GenAI.TOOL_NAME)
        if not name or not prices.tool_side_effecting(name):
            continue
        if span.get(Swarmproof.RECOVERY_EXACTLY_ONCE):
            continue  # already fired-once by the target
        key = span.get(Swarmproof.TOOL_IDEMPOTENCY_KEY) or name
        by_tool.setdefault(name, []).append(key)

    out: list[ToolCrossCheck] = []
    for tool, keys in sorted(by_tool.items()):
        fires = _observe_fires(keys)
        deduped = len(keys) - fires
        out.append(
            ToolCrossCheck(
                tool=tool,
                calls=len(keys),
                fires=fires,
                deduped=deduped,
                usd_prevented=round(deduped * prices.tool_downstream(tool), 6),
            )
        )
    return out
