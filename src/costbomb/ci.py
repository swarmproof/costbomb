"""CI gate + baseline — fail the build when spend regresses (REQ-CI-*).

    costbomb run --target ./agent.py --budget 0.50 --fail-on-regression

Exit non-zero when worst-case spend exceeds ``--budget`` OR regresses versus a
committed baseline beyond tolerance. The subtle, important part is **price-drift
separation** (ADR-6, REQ-CI-3):

    regression? = worst_case_now > reprice(baseline_inputs, current_table) × (1 + tol)

Before comparing, the baseline's *recorded traces* are re-priced under the *current*
price table. A provider raising prices moves both sides together → no regression; a
genuinely more-expensive-behaving agent moves only ``worst_case_now`` → red. That is
why the baseline stores traces, not just numbers.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from costbomb._vendor.trace import Trace
from costbomb.findings import RunFindings
from costbomb.meter import CostMeter
from costbomb.pricing import PriceTable

BASELINE_FILE = ".costbomb-baseline.json"


class BaselineEntry(BaseModel):
    worst_usd: float
    input: str
    input_id: str
    seed: int
    k: int
    trace: dict = Field(default_factory=dict)  # serialized worst trace for repricing

    @property
    def repriceable(self) -> bool:
        return bool(self.trace.get("spans"))


class Baseline(BaseModel):
    price_table_version: str = "unknown"
    tolerance: float = 0.10
    per_class: dict[str, BaselineEntry] = Field(default_factory=dict)

    @classmethod
    def from_findings(cls, rf: RunFindings, *, tolerance: float = 0.10) -> Baseline:
        per_class: dict[str, BaselineEntry] = {}
        for f in rf.findings:
            per_class[f.attack_class] = BaselineEntry(
                worst_usd=f.worst_usd,
                input=f.repro.get("input", ""),
                input_id=f.repro.get("input_id", ""),
                seed=f.repro.get("seed", rf.seed),
                k=f.k,
                trace=f.worst_trace.to_dict() if f.worst_trace else {},
            )
        return cls(
            price_table_version=rf.price_table_version,
            tolerance=tolerance,
            per_class=dict(sorted(per_class.items())),
        )

    def save(self, path: str | Path = BASELINE_FILE) -> None:
        Path(path).write_text(json.dumps(self.model_dump(), indent=2, sort_keys=True) + "\n")

    @classmethod
    def load(cls, path: str | Path = BASELINE_FILE) -> Baseline:
        return cls.model_validate_json(Path(path).read_text())


class Regression(BaseModel):
    attack_class: str
    now_usd: float
    baseline_repriced_usd: float
    tolerance: float
    price_drift_separated: bool  # False → couldn't reprice (no stored trace)


class OverBudget(BaseModel):
    attack_class: str
    worst_usd: float
    budget_usd: float


class GateResult(BaseModel):
    passed: bool
    exit_code: int
    reasons: list[str] = Field(default_factory=list)
    over_budget: list[OverBudget] = Field(default_factory=list)
    regressions: list[Regression] = Field(default_factory=list)
    price_drift_absorbed: bool = False


def gate(
    rf: RunFindings,
    *,
    prices: PriceTable,
    baseline: Baseline | None = None,
    budget_usd: float | None = None,
    fail_on_regression: bool = False,
) -> GateResult:
    """Evaluate the CI gate. Never mutates its inputs."""
    budget_usd = budget_usd if budget_usd is not None else rf.budget_usd
    result = GateResult(passed=True, exit_code=0)
    meter = CostMeter(prices)

    # --- absolute budget check (REQ-CI-1, first clause) ---
    if budget_usd is not None:
        for f in rf.findings:
            if f.worst_usd > budget_usd:
                result.over_budget.append(
                    OverBudget(attack_class=f.attack_class, worst_usd=f.worst_usd, budget_usd=budget_usd)
                )

    # --- regression check with price-drift separation (REQ-CI-3) ---
    if fail_on_regression and baseline is not None:
        for f in rf.findings:
            entry = baseline.per_class.get(f.attack_class)
            if entry is None:
                continue  # new class — reported by budget check only, not a regression
            if entry.repriceable:
                repriced = meter.cost(Trace.from_dict(entry.trace), annotate=False).total_usd
                separated = True
                result.price_drift_absorbed = True
            else:
                repriced = entry.worst_usd  # fall back to raw number (no drift separation)
                separated = False
            if f.worst_usd > repriced * (1.0 + baseline.tolerance):
                result.regressions.append(
                    Regression(
                        attack_class=f.attack_class,
                        now_usd=f.worst_usd,
                        baseline_repriced_usd=repriced,
                        tolerance=baseline.tolerance,
                        price_drift_separated=separated,
                    )
                )

    # --- verdict ---
    if result.over_budget:
        result.reasons.append(
            f"{len(result.over_budget)} class(es) exceed --budget ${budget_usd:.2f}"
        )
    if result.regressions:
        result.reasons.append(f"{len(result.regressions)} class(es) regressed vs baseline")
    result.passed = not (result.over_budget or result.regressions)
    result.exit_code = 0 if result.passed else 1
    return result
