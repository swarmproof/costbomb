"""Findings model — the ranked worst-offenders (REQ-RP-1).

``RunFindings`` is what the engine returns and what the reporter, CI gate, and OTel
export all read. It carries everything needed to (a) rank offenders, (b) reproduce
each exactly, and (c) compute the headline amplification factor. It also produces
the economic fragment that merges into the shared ``RunReport.adversarial`` section
(REQ-RP-2) — costbomb owns findings, not the renderer.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from costbomb._vendor.run_report import merge_economic_section
from costbomb._vendor.trace import Trace
from costbomb.meter import CostBreakdown


def amplification(baseline_usd: float, worst_usd: float) -> float:
    """worst / baseline, guarded against a zero/near-zero baseline."""
    if baseline_usd <= 1e-9:
        return float(worst_usd / 1e-9) if worst_usd > 0 else 1.0
    return worst_usd / baseline_usd


class Finding(BaseModel):
    """One class's worst offender, with exact reproduction (REQ-RP-1)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    rank: int
    attack_class: str
    worst_usd: float
    baseline_usd: float
    amplification_factor: float
    k: int
    samples_usd: list[float] = Field(default_factory=list)
    breakdown: CostBreakdown
    estimated: bool = False
    under_sampled: bool = False  # fewer than k runs completed (cap hit mid-k), SA-4
    side_effect_risk: bool = False  # ⊕ storming/looping tool with side-effects (REQ-RP-4)
    repro: dict[str, Any] = Field(default_factory=dict)
    # In-memory only: the metered worst-case trace, for OTel export (REQ-RP-5) and
    # for the CI gate to re-price under a new table (REQ-CI-3). Excluded from JSON.
    worst_trace: Trace | None = Field(default=None, exclude=True, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "attack_class": self.attack_class,
            "worst_usd": round(self.worst_usd, 6),
            "baseline_usd": round(self.baseline_usd, 6),
            "amplification_factor": round(self.amplification_factor, 2),
            "k": self.k,
            "samples_usd": [round(s, 6) for s in self.samples_usd],
            "breakdown": {
                "model_usd": round(self.breakdown.model_usd, 6),
                "tool_usd": round(self.breakdown.tool_usd, 6),
                "spawn_usd": round(self.breakdown.spawn_usd, 6),
                "infra_usd": round(self.breakdown.infra_usd, 6),
                "duration_s": round(self.breakdown.duration_s, 4),
                "downstream_usd": round(self.breakdown.downstream_usd, 6),
                "blast_radius_usd": round(self.breakdown.blast_radius_usd, 6),
                "duplicate_effect_usd": round(self.breakdown.duplicate_effect_usd, 6),
                "duplicate_calls": self.breakdown.duplicate_calls,
                "by_model": self.breakdown.by_model,
                "by_tool": self.breakdown.by_tool,
                "n_model_calls": self.breakdown.n_model_calls,
                "n_tool_calls": self.breakdown.n_tool_calls,
                "n_spawns": self.breakdown.n_spawns,
                "side_effecting_tools": self.breakdown.side_effecting_tools,
            },
            "estimated": self.estimated,
            "under_sampled": self.under_sampled,
            "side_effect_risk": self.side_effect_risk,
            "repro": self.repro,
        }


class RunFindings(BaseModel):
    """The full result of one search."""

    run_id: str
    seed: int
    price_table_version: str
    baseline_usd: float = 0.0
    worst_usd: float = 0.0
    amplification_factor: float = 1.0
    own_spend_usd: float = 0.0
    max_spend_usd: float = 0.0
    budget_usd: float | None = None  # the CI --budget threshold, if any
    stopped_reason: str = ""
    estimated: bool = False
    findings: list[Finding] = Field(default_factory=list)
    classes_skipped: list[str] = Field(default_factory=list)

    def rank(self) -> RunFindings:
        """Sort findings by worst_usd desc and (re)assign ranks + headline numbers."""
        self.findings.sort(key=lambda f: f.worst_usd, reverse=True)
        for i, f in enumerate(self.findings, start=1):
            f.rank = i
        if self.findings:
            self.worst_usd = self.findings[0].worst_usd
            self.amplification_factor = self.findings[0].amplification_factor
        return self

    def to_findings_json(self) -> dict[str, Any]:
        """The machine-readable ``findings.json`` export (REQ-RP-5)."""
        return {
            "run_id": self.run_id,
            "seed": self.seed,
            "price_table_version": self.price_table_version,
            "baseline_usd": round(self.baseline_usd, 6),
            "worst_usd": round(self.worst_usd, 6),
            "amplification_factor": round(self.amplification_factor, 2),
            "own_spend_usd": round(self.own_spend_usd, 6),
            "max_spend_usd": round(self.max_spend_usd, 6),
            "budget_usd": self.budget_usd,
            "stopped_reason": self.stopped_reason,
            "estimated": self.estimated,
            "classes_skipped": self.classes_skipped,
            "findings": [f.to_dict() for f in self.findings],
        }

    def economic_fragment(self, adversarial: dict[str, Any] | None = None) -> dict[str, Any]:
        """Merge into a ``RunReport.adversarial`` dict (REQ-RP-2)."""
        economic = {
            "baseline_usd": round(self.baseline_usd, 6),
            "worst_usd": round(self.worst_usd, 6),
            "amplification_factor": round(self.amplification_factor, 2),
            "own_spend_usd": round(self.own_spend_usd, 6),
            "estimated": self.estimated,
            "classes_skipped": self.classes_skipped,
            "findings": [f.to_dict() for f in self.findings],
        }
        return merge_economic_section(adversarial or {}, economic)
