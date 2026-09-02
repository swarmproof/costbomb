"""Price table — the provider-agnostic $ source of truth (REQ-CM-3, NFR-3).

Vendored from the LiteLLM / tokencost registry and extended with reasoning/cache
token classes and per-tool-call fees. Nothing in the engine or meter hardcodes a
provider price; it all flows through here so a table swap re-prices everything
(REQ-CM-8, the CI gate's price-drift separation).

Design rule (UT-CM-5/6): an unknown *model* is a loud error, never a silent $0 —
a meter that treats an unpriced model as free would make the search optimize a lie.
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class UnpricedModelError(KeyError):
    """Raised when a model id is missing from the price table (never silent $0)."""


class ModelPrice(BaseModel):
    """Per-token prices for one model. Missing classes default to 0.0.

    The five 2026 token classes (REQ-CM-2): input, output, reasoning/thinking,
    cache-read, and cache-write are each priced distinctly — not lumped together.
    """

    input_cost_per_token: float = 0.0
    output_cost_per_token: float = 0.0
    reasoning_cost_per_token: float = 0.0
    cache_read_cost_per_token: float = 0.0
    cache_write_cost_per_token: float = 0.0


class ToolPrice(BaseModel):
    """Cost of one tool call.

    ``price_per_call`` is the *direct* fee costbomb's target pays to invoke the tool
    (an API charge). ``downstream_usd`` is the *consequence* cost each call causes in
    the real world — the money a ``charge_card`` moves, the cost of an email blast —
    the true denial-of-wallet blast radius (Delivery 1). ``side_effecting`` marks a
    tool whose calls have real effects (feeds duplicate-charge detection, Delivery 3).
    """

    price_per_call: float = 0.0
    downstream_usd: float = 0.0
    side_effecting: bool = False


class PriceTable(BaseModel):
    """A loaded, versioned price table. Immutable once built."""

    version: str = "unknown"
    source: str = "unknown"
    models: dict[str, ModelPrice] = Field(default_factory=dict)
    tools: dict[str, ToolPrice] = Field(default_factory=dict)
    # Wall-clock/compute cost per second (GPU-seconds, serverless duration). Default 0
    # so time-based cost is opt-in and existing tables/baselines are unaffected.
    infra_usd_per_second: float = 0.0

    # ---- construction ----

    @classmethod
    def default(cls) -> PriceTable:
        """Load the vendored ``data/prices.json`` shipped with the package."""
        text = resources.files("costbomb.data").joinpath("prices.json").read_text()
        return cls.from_json(text)

    @classmethod
    def from_path(cls, path: str | Path) -> PriceTable:
        """Load a user-supplied table (``--price-table``)."""
        return cls.from_json(Path(path).read_text())

    @classmethod
    def from_json(cls, text: str) -> PriceTable:
        raw: dict[str, Any] = json.loads(text)
        meta = raw.get("_meta", {})
        return cls(
            version=meta.get("version", "unknown"),
            source=meta.get("source", "unknown"),
            models={k: ModelPrice(**v) for k, v in raw.get("models", {}).items()},
            tools={k: ToolPrice(**v) for k, v in raw.get("tools", {}).items()},
            infra_usd_per_second=float((raw.get("infra") or {}).get("usd_per_second", 0.0)),
        )

    # ---- lookup ----

    def model(self, model_id: str) -> ModelPrice:
        """Prices for ``model_id`` (e.g. ``anthropic:claude-opus-4-8``).

        Raises :class:`UnpricedModelError` for an unknown model — the meter must
        never silently treat an unpriced model as free (UT-CM-6).
        """
        try:
            return self.models[model_id]
        except KeyError as exc:
            known = ", ".join(sorted(self.models)) or "(none)"
            raise UnpricedModelError(
                f"model {model_id!r} not in price table {self.version!r}; "
                f"known models: {known}. Add it or pass --price-table."
            ) from exc

    def tool_price(self, tool_name: str) -> float:
        """Fee for one call to ``tool_name``. Unknown tools default to $0.

        Unlike models, an absent tool is genuinely free by default (most tools are);
        the meter flags a call whose tool is unpriced so coverage stays honest.
        """
        entry = self.tools.get(tool_name)
        return entry.price_per_call if entry else 0.0

    def has_tool(self, tool_name: str) -> bool:
        return tool_name in self.tools

    def tool_downstream(self, tool_name: str) -> float:
        """Real-world consequence cost of one call (the blast radius). 0 if unknown."""
        entry = self.tools.get(tool_name)
        return entry.downstream_usd if entry else 0.0

    def tool_side_effecting(self, tool_name: str) -> bool:
        entry = self.tools.get(tool_name)
        return bool(entry and entry.side_effecting)
