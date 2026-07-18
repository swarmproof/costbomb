"""Fuzz engine — directed search toward maximum spend (REQ-FE-*).

A greybox evolutionary loop: seed → evaluate → keep highest-cost → mutate → repeat,
with three deliberate choices (ARCHITECTURE §4.2):

* **Power schedule** — higher-yield seeds get more mutation energy (AFLFast-style),
  because the evaluator is *paid* and sample efficiency is everything (REQ-FE-3).
* **p95 over k** — fitness is a distribution statistic, not one sample, so a
  non-deterministic target doesn't make findings or the CI gate flap (ADR-1).
* **Surrogate pre-ranking** — the cheap estimator filters candidates for free; only
  the promising ones cost real money (ADR-4, REQ-FE-7).

Wrapped around all of it is the **own-budget cap** (NFR-1): the tool that finds
runaway spend must never run away itself. The cap is checked *before* each paid run,
so a candidate's k runs are never left half-executed past the cap (SA-4, E2E-4).
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from random import Random

from costbomb._vendor.trace import Trace
from costbomb.attacks.base import AttackRegistry, Input, TargetCapabilities
from costbomb.attacks.base import registry as default_registry
from costbomb.estimator import Estimator
from costbomb.findings import Finding, RunFindings, amplification
from costbomb.meter import CostBreakdown, CostMeter
from costbomb.pricing import PriceTable
from costbomb.targets.base import Target, TargetContext


@dataclass
class SearchConfig:
    seed: int = 1337
    max_spend_usd: float = 2.0  # NFR-1 — the fuzzer's own hard cap
    budget_usd: float | None = None  # CI --budget threshold (recorded for the gate)
    k: int = 5  # runs per candidate; fitness = p95 over these
    max_generations: int = 200
    plateau_generations: int = 40  # stop after this many with no improvement
    wall_clock_s: float | None = None
    top_k_ratio: float = 0.5  # surrogate: pay only for est in the top fraction
    min_history_before_prune: int = 8
    cap_safety: float = 1.25  # headroom on the cap reservation so it holds strictly (NFR-1)
    classes: tuple[str, ...] | None = None  # None → all applicable
    use_llm: bool = False
    dry_run: bool = False  # estimate only, zero paid calls (REQ-CI-4, NFR-7)
    allow_side_effects: bool = False
    benign_input: str = "What is 2 + 2? Answer in one word."
    p95: float = 0.95


@dataclass
class _Candidate:
    input: Input
    class_name: str
    fitness: float = 0.0
    energy: float = 1.0


@dataclass
class _EvalResult:
    samples: list[float]
    worst_breakdown: CostBreakdown
    used_usd: float
    hit_cap: bool
    estimated: bool
    worst_trace: Trace | None = None

    @property
    def under_sampled(self) -> bool:
        return self.hit_cap and len(self.samples) > 0


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * pct
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return s[int(k)]
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


class FuzzEngine:
    def __init__(
        self,
        target: Target,
        *,
        prices: PriceTable,
        config: SearchConfig | None = None,
        registry: AttackRegistry | None = None,
        meter: CostMeter | None = None,
        estimator: Estimator | None = None,
        mutator: object | None = None,
        now: Callable[[], float] | None = None,
        run_id: str = "costbomb-run",
    ) -> None:
        self.target = target
        self.prices = prices
        self.config = config or SearchConfig()
        self.registry = registry or default_registry
        self.meter = meter or CostMeter(prices)
        self.estimator = estimator or Estimator(prices)
        self.mutator = mutator
        self.now = now or time.monotonic
        self.run_id = run_id

        self._rng = Random(self.config.seed)
        self._own_spend = 0.0
        self._max_run_cost = 0.0  # largest single real run seen — the cap reservation
        self._est_history: list[float] = []

    # ---- public API ----

    def run(self) -> RunFindings:
        cfg = self.config
        caps = self.target.capabilities()
        classes = self._select_classes(caps)
        skipped = self.registry.skipped(caps)

        result = RunFindings(
            run_id=self.run_id,
            seed=cfg.seed,
            price_table_version=self.prices.version,
            max_spend_usd=cfg.max_spend_usd,
            budget_usd=cfg.budget_usd,
            classes_skipped=skipped,
            estimated=cfg.dry_run,
        )

        baseline = self._baseline_cost()
        result.baseline_usd = baseline

        best: dict[str, tuple[Input, _EvalResult]] = {}
        queue: list[_Candidate] = []
        start = self.now()

        def stop() -> str:
            if self._own_spend >= cfg.max_spend_usd:
                return "budget-capped"
            if cfg.wall_clock_s is not None and (self.now() - start) >= cfg.wall_clock_s:
                return "wall-clock"
            return ""

        # ---- Phase 1: seed each applicable class ----
        for cls in classes:
            for seed_input in cls.seeds(caps):
                res = self._evaluate(seed_input)
                self._own_spend += res.used_usd
                if res.samples:
                    self._consider(best, seed_input, res)
                    queue.append(
                        _Candidate(seed_input, cls.name, fitness=_percentile(res.samples, cfg.p95))
                    )
                if res.hit_cap:
                    result.stopped_reason = "budget-capped"
                    return self._finalize(result, best, baseline)
            if reason := stop():
                result.stopped_reason = reason
                return self._finalize(result, best, baseline)

        # ---- Phase 2: evolve ----
        gen = 0
        since_improve = 0
        while gen < cfg.max_generations:
            if reason := stop():
                result.stopped_reason = reason
                break
            if since_improve >= cfg.plateau_generations:
                result.stopped_reason = "plateau"
                break
            gen += 1

            if not queue:
                break
            parent = self._select(queue)
            cls = self.registry.get(parent.class_name)
            child = cls.mutate(parent.input, self._rng, self.mutator if cfg.use_llm else None)
            self._own_spend += float(getattr(self.mutator, "last_cost_usd", 0.0) or 0.0)

            est = self.estimator.estimate_input(child)
            self._est_history.append(est)
            if self._prune(est):
                continue  # surrogate says loser — don't spend real $ (REQ-FE-7)

            res = self._evaluate(child)
            self._own_spend += res.used_usd
            if res.samples and self._consider(best, child, res):
                since_improve = 0
                fitness = _percentile(res.samples, cfg.p95)
                gain = max(0.0, fitness - parent.fitness)
                parent.energy += 1.0 + gain / max(baseline, 1e-6)  # AFLFast-style reward
                queue.append(_Candidate(child, parent.class_name, fitness, energy=parent.energy))
            else:
                since_improve += 1
            if res.hit_cap:
                result.stopped_reason = "budget-capped"
                break

        if not result.stopped_reason:
            result.stopped_reason = "exhausted" if gen >= cfg.max_generations else "plateau"
        return self._finalize(result, best, baseline)

    # ---- internals ----

    def _select_classes(self, caps: TargetCapabilities):  # type: ignore[no-untyped-def]
        applicable = self.registry.applicable(caps)
        if self.config.classes is None:
            return applicable
        wanted = set(self.config.classes)
        return [c for c in applicable if c.name in wanted]

    def _baseline_cost(self) -> float:
        """Cost of an innocent input — the denominator of the amplification factor."""
        benign = Input(text=self.config.benign_input, attack_class="baseline", seed=self.config.seed)
        if self.config.dry_run:
            return self.estimator.estimate_input(benign)
        res = self._evaluate(benign, k=1)
        self._own_spend += res.used_usd
        return res.samples[0] if res.samples else 0.0

    def _evaluate(self, input: Input, *, k: int | None = None) -> _EvalResult:
        cfg = self.config
        k = k if k is not None else cfg.k

        if cfg.dry_run:
            est = self.estimator.estimate_input(input)
            trace = None  # structural only
            bd = CostBreakdown(total_usd=est, model_usd=est, estimated=True)
            return _EvalResult([est], bd, used_usd=0.0, hit_cap=False, estimated=True)

        samples: list[float] = []
        worst_bd = CostBreakdown()
        worst_trace: Trace | None = None
        used = 0.0
        # Reserve the larger of the candidate's estimate and the worst real run seen,
        # so the guard is backed by an observed upper bound — a predictor that
        # under-estimates must never be able to breach the cap (NFR-1, E2E-4).
        reservation = max(self.estimator.estimate_input(input), self._max_run_cost, 1e-6) * cfg.cap_safety
        for i in range(k):
            # Cap guard: never *start* a run we cannot afford (SA-4, E2E-4).
            if self._own_spend + used + reservation > cfg.max_spend_usd:
                return _EvalResult(
                    samples, worst_bd, used, hit_cap=True, estimated=False, worst_trace=worst_trace
                )
            ctx = TargetContext(
                seed=cfg.seed,
                run_index=i,
                attack_class=input.attack_class,
                allow_side_effects=cfg.allow_side_effects,
            )
            trace = self.target.invoke(input, ctx)
            bd = self.meter.cost(trace)
            samples.append(bd.total_usd)
            used += bd.total_usd
            self._max_run_cost = max(self._max_run_cost, bd.total_usd)
            if bd.total_usd >= worst_bd.total_usd:
                worst_bd = bd
                worst_trace = trace
        return _EvalResult(
            samples, worst_bd, used, hit_cap=False, estimated=worst_bd.estimated,
            worst_trace=worst_trace,
        )

    def _consider(
        self, best: dict[str, tuple[Input, _EvalResult]], input: Input, res: _EvalResult
    ) -> bool:
        """Record if this beats the class's current best. Returns True if improved."""
        fitness = _percentile(res.samples, self.config.p95)
        prev = best.get(input.attack_class)
        prev_fit = _percentile(prev[1].samples, self.config.p95) if prev else -1.0
        if fitness > prev_fit:
            best[input.attack_class] = (input, res)
            return True
        return False

    def _select(self, queue: list[_Candidate]) -> _Candidate:
        """Power-schedule selection: probability ∝ energy (REQ-FE-3)."""
        weights = [max(c.energy, 1e-6) for c in queue]
        return self._rng.choices(queue, weights=weights, k=1)[0]

    def _prune(self, est: float) -> bool:
        cfg = self.config
        if len(self._est_history) < cfg.min_history_before_prune:
            return False
        threshold = _percentile(self._est_history, cfg.top_k_ratio)
        return est < threshold

    def _finalize(
        self,
        result: RunFindings,
        best: dict[str, tuple[Input, _EvalResult]],
        baseline: float,
    ) -> RunFindings:
        result.own_spend_usd = round(self._own_spend, 10)
        for class_name, (input, res) in best.items():
            worst = _percentile(res.samples, self.config.p95)
            bd = res.worst_breakdown
            side_effect_risk = bd.n_tool_calls > 0 and any(v > 0 for v in bd.by_tool.values())
            result.findings.append(
                Finding(
                    rank=0,
                    attack_class=class_name,
                    worst_usd=worst,
                    baseline_usd=baseline,
                    amplification_factor=amplification(baseline, worst),
                    k=len(res.samples),
                    samples_usd=res.samples,
                    breakdown=bd,
                    estimated=res.estimated,
                    under_sampled=res.under_sampled,
                    side_effect_risk=side_effect_risk,
                    worst_trace=res.worst_trace,
                    repro={
                        "input": input.text,
                        "input_id": input.id,
                        "attack_class": class_name,
                        "seed": self.config.seed,
                        "generation": input.generation,
                        "parent_id": input.parent_id,
                        "k": self.config.k,
                        "price_table_version": self.prices.version,
                    },
                )
            )
        return result.rank()
