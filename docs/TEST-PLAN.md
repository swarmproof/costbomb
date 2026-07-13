# costbomb — TEST PLAN

*Verification strategy for a fuzzer whose oracle is money. Companion to [`PRD.md`](./PRD.md) (REQ/NFR IDs) and [`ARCHITECTURE.md`](./ARCHITECTURE.md).*
*`⊕` = tests for scope beyond the original SPEC.*

---

## 1. Testing philosophy

costbomb tests a system with two properties that break normal test intuition:
1. **The oracle costs money.** We cannot run the real evaluator thousands of times in CI. So the test pyramid leans hard on **recorded fixtures** (frozen agent runs + their true cost) and a **`FakeTarget`** whose spend is scripted and deterministic. Real paid runs are reserved for a small, gated, nightly suite.
2. **The target is non-deterministic.** Tests must assert on **distributions and bounds**, not exact equality, wherever a real LLM is involved — and must prove that costbomb's *own* determinism knobs neutralize that where promised.

The single most important thing to test is the **meter's accuracy** — it is the oracle every other component trusts. A wrong meter means the search optimizes a lie and the CI gate is meaningless.

---

## 2. Test pyramid

```
                 ▲   E2E (few, some paid, nightly)
                 │   • 5¢→$5 auto-discovery   • CI gate red/green   • own-budget-cap safety
                 │
             Integration (medium, fixtures + FakeTarget)
                 │   • engine↔meter↔target loop   • baseline diff   • report render   • adapters
                 │
        Unit (many, fast, no network)
            • cost model math   • price-table parse   • each AttackClass seeds/mutate/applicable
            • fitness p95 calc   • power schedule   • stopping criteria   • estimator
```

| Layer | Count | Speed | LLM/network | Runs in |
|-------|-------|-------|-------------|---------|
| Unit | many | ms | none | every commit |
| Integration | medium | seconds | `FakeTarget` + recorded fixtures only | every commit |
| E2E (dry) | few | seconds | none (surrogate) | every PR |
| E2E (paid) | few | minutes | real, tiny models, hard-capped | nightly / pre-release |

---

## 3. Unit tests

### 3.1 Cost model & meter (`REQ-CM-*`, NFR-8) — highest priority
- **UT-CM-1** `cost = Σ sources` math: given a fixture trace with known tokens/tools/spawns and a known price table, metered $ equals hand-computed $ to the cent.
- **UT-CM-2** ⊕ Reasoning tokens, cache-read, and cache-write are each priced at their distinct rate (not lumped into input/output).
- **UT-CM-3** Sub-agent rollup: a parent trace with 2 child spans sums child costs into the parent total (`REQ-CM-4`).
- **UT-CM-4** Tool-call fees: N calls to `premium_api` add `N × price_per_call`.
- **UT-CM-5** Price-table parse: malformed/missing model → clear error, never silent $0.
- **UT-CM-6** Unknown model → explicit "unpriced model" surfaced, not treated as free.
- **UT-CM-7** ⊕ Re-pricing: same trace under two tables yields the two expected totals (`REQ-CM-8`).
- **Acceptance:** metered $ within **≤1%** of the fixture's provider-reported cost across the fixture corpus (NFR-8).

### 3.2 Attack library (`REQ-AL-*`)
- **UT-AL-1** Each of the 10 classes: `seeds()` returns ≥1 non-empty input; `mutate()` returns a *different* input; `applicable()` returns the documented bool for a capability matrix.
- **UT-AL-2** `mutate()` is deterministic given a fixed `rng` seed (template path).
- **UT-AL-3** ⊕ `applicable()` correctly skips `recursion` when caps lack spawn, `tool-*` when caps lack tools.
- **UT-AL-4** Registry loads a plugin `AttackClass` from an entry point without core changes (`REQ-AL-4`).
- **UT-AL-5** `signal(trace)` increases monotonically with the class's target quantity (more tool calls → higher tool-storm signal).

### 3.3 Fuzz engine (`REQ-FE-*`)
- **UT-FE-1** p95 fitness: given a scripted spend distribution, computed p95 matches expected (`REQ-FE-2`).
- **UT-FE-2** Power schedule: a seed with higher observed gain receives more energy on the next round (`REQ-FE-3`).
- **UT-FE-3** Stopping criteria fire correctly for each of budget / plateau / wallclock, whichever first (`REQ-FE-5`).
- **UT-FE-4** Seed reproducibility: same `--seed` + `FakeTarget` → identical candidate sequence (NFR-2).
- **UT-FE-5** Surrogate pre-rank: candidates below the top-K estimate never trigger a (Fake) paid run (`REQ-FE-7`).

### 3.4 Estimator (`REQ-CM-7`)
- **UT-EST-1** Estimated $ correlates with true $ on the fixture corpus (Spearman ρ above a documented threshold); estimator is a *ranker*, so rank correlation matters more than absolute error.

---

## 4. Integration tests (fixtures + `FakeTarget`, no real spend)

- **IT-1 Full loop:** engine drives `FakeTarget` (scripted to spend more on inputs containing an "escalate" token); after N generations, best-found input contains the escalation pattern and reported $ exceeds the seed's $. Proves search *climbs*.
- **IT-2 Own-budget cap (NFR-1):** `FakeTarget` scripted to spend $0.50/run, cap = $2.00 → engine stops after ≤4 runs, reports partial results, **never exceeds cap**. (The headline safety test — see also E2E-4.)
- **IT-3 Baseline diff (`REQ-CI-1/2`):** given a baseline and a worse current run → gate returns non-zero; given an equal/better run → zero.
- **IT-4 Price-drift separation (`REQ-CI-3`) ⊕:** hold the agent's *behavior* fixed, raise all prices 2× in the table → gate stays **green** (re-priced baseline moves with it). Then worsen behavior at old prices → gate goes **red**. Proves the gate measures agent regression, not price drift.
- **IT-5 Adapters (`REQ-TA-*`):** each adapter's `invoke` returns a well-formed `Trace` with a cost breakdown against a local stub server / stub module / mockworld stub.
- **IT-6 Report render (`REQ-RP-*`):** findings model → oxblood HTML + terminal; amplification factor headline present; repro block round-trips (re-running the repro on `FakeTarget` reproduces the $).
- **IT-7 Export (`REQ-RP-5`):** `findings.json` schema-validates; OTel trace imports into a Langfuse-shaped consumer.
- **IT-8 No-LLM mode (NFR-10):** with LLM mutator disabled, template attacks + dry-run estimator still produce findings and still gate.
- **IT-9 ⊕ exactly-once cross-check (`REQ-RP-4`):** a `tool-storm` finding on a side-effecting tool is flagged as duplicate-charge risk in the report.
- **IT-10 ⊕ Embedded path:** `PersonaTarget` (with a fake stampede driver) feeds cost into a stampede-report stub — proves the `Target` seam works both ways (ARCHITECTURE §6).

---

## 5. End-to-end scenarios (Given/When/Then)

### E2E-1 — The signature demo: 5¢ → $5, found automatically  *(paid, nightly)*
> **Given** a demo agent that answers a trivial question for ~$0.05, but that can be lured into a retry-loop,
> **And** costbomb configured with the 5 attack classes, `--seed 1337`, `--max-spend 2.00`,
> **When** I run `costbomb run --target ./demo_agent.py`,
> **Then** within its own budget cap it reports at least one input whose p95 spend is **≥ $2.50 (≥50× amplification)**,
> **And** the report names the triggering class (`retry-loop`),
> **And** the reported repro, re-run, reproduces a spend within the p95 confidence band.

*This is the launch demo and the primary efficacy acceptance test (PRD §7).*

### E2E-2 — CI gate goes red on a regression, green on revert  *(dry + paid variants)*
> **Given** a repo with a committed `.costbomb-baseline.json`,
> **When** a PR changes the agent so a `context-bomb` input now costs 3× the baseline,
> **Then** `costbomb run --fail-on-regression` exits **non-zero** and names the regressed class,
> **And** when the change is reverted, the same command exits **zero**.

### E2E-3 — A price hike does NOT fail the build  *(fixtures — deterministic)*  ⊕
> **Given** a green baseline,
> **When** the provider price table is bumped 2× but the agent is unchanged,
> **Then** the gate stays **green** (the re-priced baseline absorbs the price move).

### E2E-4 — The fuzzer refuses to overspend  *(paid, nightly — the safety test)*  ★
> **Given** `--max-spend 1.00` and a target that costs ~$0.30/run,
> **When** the search runs to a stopping criterion,
> **Then** total real spend across the whole run is **≤ $1.00**,
> **And** the run halts gracefully with partial results labelled "budget-capped",
> **And** no single candidate's `k` runs are left half-executed past the cap.

*A cost tool that blows its own budget is disqualifying — this test gates every release.*

### E2E-5 — Determinism  *(fixtures)*
> **Given** identical `--seed`, price table, `temp=0`, fixed model, and `FakeTarget`,
> **When** I run the search twice,
> **Then** the candidate sequence, findings, and reported $ are **identical** (NFR-2).

### E2E-6 — No-LLM CI smoke is fast  *(dry)*
> **Given** `--dry-run`,
> **When** `costbomb run` executes in CI,
> **Then** it completes in **< 10s**, places **zero paid calls**, and still emits a gate result (NFR-7).

### E2E-7 — Embedded launch parity  *(fixtures)*  ⊕
> **Given** the stampede `adversarial:economic` cohort using `costbomb-core`,
> **When** a stampede run executes with that cohort,
> **Then** the Agent Readiness Report contains an economic-findings section produced by the **same** engine the standalone CLI uses (one codebase, ARCHITECTURE §6).

### E2E-8 — Incident replay  *(fixtures)*  ⊕
> **Given** an agent-postmortems `cost-blowup` incident imported as a seed,
> **When** costbomb runs it against a still-vulnerable target,
> **Then** it reproduces an amplification, and against a patched target it does **not** — proving the fix.

---

## 6. Cost-meter accuracy test suite (dedicated — the oracle)

Because the meter is the oracle, it gets its own corpus and CI job:
- **Fixture corpus:** ≥20 recorded real agent runs across providers (Anthropic, OpenAI-compatible, Ollama-free), each with the provider's own reported cost captured at record time.
- **MA-1** Metered $ vs provider-reported $: **≤1% error** on token costs per fixture (NFR-8).
- **MA-2** Breakdown correctness: per-source sums equal the total.
- **MA-3** Attribution: multi-agent fixtures roll child spend to the right parent.
- **MA-4** ⊕ Cache/reasoning fixtures priced correctly (2026 token classes).
- **MA-5** Regression guard: a golden-file test so a price-table refresh that changes a fixture's cost is caught and reviewed, not silently absorbed.

---

## 7. Non-determinism & variance testing

- **ND-1** Characterize target variance: run a fixed input against a real tiny model `k` times; record the spend distribution; confirm p95 is more stable than max across repeats.
- **ND-2** Choose `k`: empirically find the smallest `k` where the p95 gate flips <5% of the time on an unchanged agent (the flakiness budget). Document the recommended `k` (default candidate: 5).
- **ND-3** Gate-flap test: run E2E-2's *green* case 20× nightly; it must stay green ≥19/20 (documents real-world gate stability).

---

## 8. Safety & abuse testing

- **SA-1** (=E2E-4) Own-budget cap holds under adversarial target spend.
- **SA-2** Side-effect default (NFR-5): without `--allow-side-effects`, an attack that would call a real side-effecting tool is routed to mockworld/dry or blocked — proven by a spy that asserts the real tool was never invoked.
- **SA-3** LLM-mutator cost accounting (`REQ-FE-4`, NFR-4): the mutator's *own* spend counts against `--max-spend`; with mutator on a paid model, SA-1's cap still holds inclusive of mutation cost.
- **SA-4** Graceful cap-hit mid-`k`: killing the run at the cap never leaves a reported finding backed by fewer than `k` completed runs (label it "under-sampled" instead).

---

## 9. Acceptance criteria (release gates)

A release is shippable only when all hold:

| # | Criterion | Test |
|---|-----------|------|
| AC-1 | Meter accuracy ≤1% on the corpus | MA-1 |
| AC-2 | 5¢→$5 demo cracked automatically ≥50× under default cap | E2E-1 |
| AC-3 | CI gate red-on-regression / green-on-revert / green-on-price-hike | E2E-2, E2E-3 |
| AC-4 | Own-budget cap never exceeded (incl. mutator cost) | E2E-4, SA-1, SA-3 |
| AC-5 | Determinism holds with knobs set | E2E-5, UT-FE-4 |
| AC-6 | Dry-run CI smoke < 10s, zero paid calls | E2E-6 |
| AC-7 | Side-effect-free by default | SA-2 |
| AC-8 | Gate flakiness ≤5% at recommended `k` | ND-3 |
| AC-9 | ⊕ Embedded and standalone run the same core | E2E-7, IT-10 |
| AC-10 | No-LLM mode still gates | IT-8 |

**Coverage traceability:** every `REQ-*`/`NFR-*` in the PRD maps to ≥1 test ID above; the CI job prints an unmapped-requirement report so new requirements can't ship untested.
