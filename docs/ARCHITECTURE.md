# costbomb — ARCHITECTURE

*System design for denial-of-wallet fuzzing. Companion to [`PRD.md`](./PRD.md) (REQ IDs referenced inline).*
*`⊕` marks design beyond the original [`SPEC.md`](../SPEC.md).*

---

## 1. System overview

costbomb is a **directed greybox fuzzer with a dollar-valued fitness function**. The loop is classic evolutionary fuzzing (seed → evaluate → select → mutate) with three agent-specific twists: the *evaluator is a real, paid agent run*; the *fitness is a spend distribution, not a scalar*; and the *mutator can be an LLM* because inputs are natural language.

Everything is organized around one invariant: **the cost meter is the oracle.** The attack library proposes candidates, the fuzz engine searches, the reporter ranks and gates — but all of them optimize against the number the meter produces. If the meter is wrong, the tool is wrong. So the meter is the most rigorously-tested, most provider-agnostic component.

```
                                  ┌─────────────────────────────────────────────┐
                                  │              costbomb-core                    │
                                  │   (pure library — no CLI, no I/O side effects)│
                                  └─────────────────────────────────────────────┘
                                                     │
   ┌──────────────┐   candidate input   ┌────────────────────────┐   trace + $   ┌──────────────┐
   │  ATTACK      │ ──────────────────▶ │      FUZZ ENGINE        │ ◀──────────── │  COST METER  │
   │  LIBRARY     │                     │  seed queue · power     │               │  Σ cost      │
   │ 5+5 classes  │ ◀───── mutate ───── │  schedule · p95 fitness │ ──── run ───▶ │  sources     │
   │ AttackClass  │                     │  stop criteria · seed   │               │  (oracle)    │
   └──────────────┘                     └────────────────────────┘               └──────┬───────┘
          ▲                                        │                                     │ prices
          │ seeds                                  │ best-N findings                     ▼
   ┌──────┴───────┐                        ┌───────▼────────┐                    ┌──────────────┐
   │ postmortems  │                        │   REPORTER +    │                    │  PRICE TABLE │
   │ incident     │                        │   CI GATE       │                    │  (JSON,      │
   │ seeds ⊕      │                        │ oxblood render  │                    │  vendored)   │
   └──────────────┘                        │ baseline diff   │                    └──────────────┘
                                           └───────┬────────┘
                                                   │ invoke(input) -> Trace
                                   ┌───────────────┼───────────────┬───────────────┐
                                   ▼               ▼               ▼               ▼
                            ┌───────────┐   ┌───────────┐   ┌───────────┐   ┌───────────┐
                            │ Persona   │   │  HTTP     │   │  Python   │   │ Mockworld │
                            │ Target    │   │  Target   │   │  Target   │   │ Target ⊕  │
                            │(stampede) │   │           │   │           │   │ (safe)    │
                            └───────────┘   └───────────┘   └───────────┘   └───────────┘
                                   │               │               │               │
                                   ▼               ▼               ▼               ▼
                              stampede swarm   agent HTTP API   ./agent.py     fake services
```

---

## 2. Component: Cost meter (`REQ-CM-*`) — the oracle

### 2.1 The cost model

True dollars for one agent run is a **sum over cost sources**, attributed to the single triggering input:

```
cost(run) =  Σ_calls [ in_tok·p_in + out_tok·p_out + think_tok·p_think + cache_r·p_cacheR + cache_w·p_cacheW ]   ← model calls
           + Σ_tools  tool_price[tool]                                                                          ← tool-call fees
           + Σ_spawns cost(child_run)                                                                           ← sub-agent spawns (recursive rollup)
```

Token-only meters miss the last two lines — which is exactly where `tool-storm` and `recursion` live. This sum is the SPEC's `tokens × price` **corrected into a real invoice** (RESEARCH gap G1).

### 2.2 Price table format (`REQ-CM-3`)

Vendored from the LiteLLM / tokencost registry, extended with tool prices. Pinned + refreshable; `--price-table` overridable.

```json
{
  "_meta": { "version": "2026-07-13", "source": "litellm+costbomb-ext" },
  "models": {
    "anthropic:claude-opus-4-8": {
      "input_cost_per_token":        3.0e-06,
      "output_cost_per_token":       1.5e-05,
      "reasoning_cost_per_token":    1.5e-05,
      "cache_read_cost_per_token":   3.0e-07,
      "cache_write_cost_per_token":  3.75e-06
    },
    "openai:gpt-4o-mini": { "input_cost_per_token": 1.5e-07, "output_cost_per_token": 6.0e-07 },
    "ollama:llama3":      { "input_cost_per_token": 0.0,     "output_cost_per_token": 0.0 }
  },
  "tools": {
    "web_search":  { "price_per_call": 0.005 },
    "code_exec":   { "price_per_call": 0.0 },
    "premium_api": { "price_per_call": 0.02 }
  }
}
```

### 2.3 Attachment modes (`REQ-CM-5`)

| Mode | How | Accuracy | When |
|------|-----|----------|------|
| **SDK-wrapper** (default) | Wrap the provider client; read `usage` off each response; count spawns via the driver. | Highest — real usage. | Python target, stampede persona. |
| **usage-field parse** | Target returns usage in its response payload; meter reads it. | High if the target is honest. | HTTP target that reports usage. |
| **proxy** ⊕ | Meter sits as an OpenAI-compatible proxy; all traffic flows through it. | High; language-agnostic. | v0.2, targets we can't wrap. |
| **wire-estimate** (fallback) | No usage available → tokenize the wire, estimate. | Lower; flagged `estimated`. | Last resort (Assumption A1). |

The meter writes a **per-run breakdown** (by source/model/tool) into the shared trace, and rolls **child spans** up to the parent input (`REQ-CM-4`) using stampede's parent/child trace linkage. This is why costbomb reuses trace-format rather than inventing its own.

### 2.4 Dry-run estimator (`REQ-CM-7`, surrogate for `REQ-FE-7`)

A cheap function `estimate(trace_shape) -> $` predicts a candidate's cost from its *structure* (turns, tool calls, context growth curve) without a paid run. Used two ways: (1) the fast **CI smoke mode** (NFR-7), and (2) a **surrogate pre-ranker** so the engine spends real dollars only confirming the top-K candidates.

---

## 3. Component: Attack library (`REQ-AL-*`)

### 3.1 The `AttackClass` seed-strategy interface

Every class — SPEC's five, the ⊕ five, and future community classes — implements one interface. Ships in core from v0.1 so classes are pluggable from day one (RESEARCH G8).

```python
class AttackClass(Protocol):
    name: str                     # "retry-loop"
    description: str
    references: list[str]         # postmortem / paper links (for the report)

    def seeds(self, ctx: TargetContext) -> list[Input]:
        """Hand-crafted starting inputs for this cost-explosion class."""

    def mutate(self, parent: Input, rng: Random, llm: Mutator | None) -> Input:
        """Produce a variant more likely to inflate spend. Template by default; LLM optional."""

    def applicable(self, caps: TargetCapabilities) -> bool:
        """False → engine skips this class and the report says so. e.g. recursion needs spawn capability."""

    def signal(self, trace: Trace) -> float:
        """Optional cheap heuristic (loops seen, tools called, context growth) to guide search
        before/without a full meter reading — the 'coverage feedback' analog."""
```

`applicable()` (`REQ-AL-5`) means costbomb reports honest coverage: *"skipped `recursion` — target has no spawn capability."* `signal()` is the greybox feedback signal (analogous to code-coverage in AFL) — it lets the engine reward "this mutation caused 3 more tool calls" even before the full dollar reading converges.

### 3.2 Class catalog

| Class | `seeds()` idea | `mutate()` lever | `signal()` | Ver |
|-------|----------------|------------------|-----------|-----|
| `retry-loop` | Unsatisfiable/contradictory success criterion | tighten contradiction; add "keep trying until valid" | # retry cycles | v0.1 |
| `tool-storm` | "cross-check against every source" | broaden scope; add "be exhaustive" | # tool calls | v0.1 |
| `context-bomb` | large doc + "keep full text in mind each step" | grow the retained blob; force re-summarize | context tokens/turn slope | v0.1 |
| `recursion` | "spawn a specialist per subtask, recursively" | deepen fan-out; remove base case | # spawns / depth | v0.1 |
| `clarification-trap` | just-ambiguous goal + vague user-sim | increase ambiguity; script vaguer answers | # clarifying turns | v0.1 |
| `reasoning-inflation` ⊕ | "think exhaustively, step by step" on trivia | escalate thinking directives | reasoning tokens | v0.2 |
| `model-escalation` ⊕ | feign difficulty to a router | amplify difficulty signals | $/call of chosen model | v0.2 |
| `cache-bust` ⊕ | vary a prefix byte each turn | randomize cacheable prefix | cache-miss rate | v0.2 |
| `tool-cost-asymmetry` ⊕ | force the priced tool over the free one | steer toward `premium_api` | $ from priced tools | v0.2 |
| `retrieval-amplification` ⊕ | "retrieve top-500 chunks, read all" | grow k; recursive retrieval | retrieved tokens | v0.2 |

Seeds can also come from **agent-postmortems** `cost-blowup` incidents (`REQ-AL-6`, v0.3): the incident's `trigger` becomes a seed, so you can "replay last month's real incident against your stack."

---

## 4. Component: Fuzz engine (`REQ-FE-*`)

### 4.1 The search loop

```
seeds ← ⋃ applicable_class.seeds()
queue ← seeds
best  ← {}
while not stop():                                   # REQ-FE-5: budget | plateau | wall-clock
    parent ← queue.select(power_schedule)           # REQ-FE-3: high-yield seeds get more energy
    child  ← class.mutate(parent, rng, llm)         # REQ-FE-4: template default, LLM optional
    est    ← meter.estimate(dry_run(child))         # REQ-FE-7: cheap surrogate pre-rank
    if est below top-K threshold: continue          #           don't spend real $ on losers
    fitness ← p95( meter.cost(target.invoke(child)) for _ in range(k) )   # REQ-FE-2: distribution, paid
    if fitness improves parent: queue.add(child, energy∝gain)             #           evolutionary keep
    best[class] ← max(best[class], child@fitness)
    guard: total_spend ≤ own_budget_cap             # NFR-1: the fuzzer's own hard cap
report(best)
```

### 4.2 Why these choices

- **Greybox evolutionary + power schedule** (not random, not exhaustive): the evaluator is *expensive and paid*, so sample efficiency is everything. AFLFast-style energy assignment (RESEARCH §2.4) puts real dollars where yield is highest.
- **p95 over k runs** (not one sample): the target is non-deterministic (RESEARCH §4.2); a scalar would make findings and the CI gate flap.
- **Surrogate pre-ranking**: the dry-run estimator filters candidates for free; only promising ones cost real money. This is what keeps a useful search under a $2 cap.
- **Single objective (spend)**: unlike coverage fuzzers we don't chase breadth; we chase one number. Multi-objective (spend × classes) is a v0.3+ option (MobFuzz-style).

---

## 5. Component: Reporter + CI gate (`REQ-RP-*`, `REQ-CI-*`)

### 5.1 Report (oxblood renderer, `REQ-RP-2`)
Headline: the **amplification factor** ("5¢ → $5.20 = 104×", `REQ-RP-3`). Then a ranked table: rank · class · worst-case $ · breakdown (tokens/tools/spawns) · exact repro (input + seed + config). ⊕ Side-effect flag when a storming tool has effects (exactly-once cross-check, `REQ-RP-4`). Exports `findings.json` + OTel trace (`REQ-RP-5`).

### 5.2 CI gate — the north-star surface
```
costbomb run --target ./agent.py --budget 0.50 --fail-on-regression
```
Exit non-zero if worst-case > `--budget` OR regressed vs baseline (`REQ-CI-1`). The subtle, important design decision is **price-drift separation** (`REQ-CI-3`):

```
regression?  =  worst_case_now  >  reprice(baseline_inputs, current_table) × (1 + tolerance)
```
We re-run the *baseline's inputs* under the *current price table* before comparing. So a provider raising prices does **not** fail your build (that's not your agent regressing) — only a genuinely more-expensive-behaving agent does. Baseline (`.costbomb-baseline.json`, `REQ-CI-2`) is committed and only ever updated intentionally (`costbomb baseline update`, `REQ-CI-6`).

### 5.3 `.costbomb-baseline.json` sketch
```json
{
  "price_table_version": "2026-07-13",
  "per_class": {
    "retry-loop":   { "worst_usd": 0.42, "input_ref": "findings/retry-loop-7a3f.json", "seed": 1337, "k": 5 },
    "context-bomb": { "worst_usd": 1.08, "input_ref": "findings/context-bomb-91c2.json", "seed": 1337, "k": 5 }
  },
  "tolerance": 0.10
}
```

---

## 6. The embedded-vs-standalone boundary (`G6`) — the core design decision

**One codebase, one core, two thin entrypoints.** This is how the SPEC's "two launches, one codebase" becomes real.

```
                         ┌──────────────────────────────────────────────┐
                         │                costbomb-core                   │
                         │  (pure Python library — zero CLI, zero I/O)    │
                         │                                                │
                         │  • CostMeter (+ price table)                   │
                         │  • AttackLibrary (AttackClass registry)        │
                         │  • FuzzEngine (search, seedable)               │
                         │  • Reporter (findings model + oxblood render)  │
                         │  • Target (Protocol: invoke(input)->Trace)     │
                         └───────────────┬───────────────┬───────────────┘
                                         │               │
                    ┌────────────────────┘               └────────────────────┐
                    ▼                                                          ▼
        ┌───────────────────────────┐                        ┌───────────────────────────┐
        │  ENTRYPOINT A (v0.1)       │                        │  ENTRYPOINT B (v0.2)       │
        │  stampede cohort adapter   │                        │  standalone CLI            │
        │                            │                        │                            │
        │  adversarial:economic      │                        │  `costbomb run ...`        │
        │  • wraps FuzzEngine as a   │                        │  • argparse/click front    │
        │    stampede persona        │                        │  • HTTP/Python/Mockworld   │
        │  • PersonaTarget → the     │                        │    target factory          │
        │    stampede agent-driver   │                        │  • CI gate + baseline I/O  │
        │  • feeds cost into the     │                        │  • standalone report file  │
        │    Agent Readiness Report  │                        │                            │
        └───────────────────────────┘                        └───────────────────────────┘
```

### 6.1 The contract that makes both work
The **`Target` Protocol** is the seam. `costbomb-core` only knows `invoke(input, ctx) -> Trace`. 
- **Embedded (A):** `PersonaTarget` implements `invoke` by driving a stampede agent via stampede's **agent-driver**; spend flows into stampede's **report-renderer** as the cost-profile section. costbomb-core is a *dependency inside stampede's repo* — literally `stampede/adversarial/economic/` importing `costbomb_core`.
- **Standalone (B):** `HTTPTarget`/`PythonTarget`/`MockworldTarget` implement the same `invoke`. The CLI is a thin wrapper: parse args → build a Target → call `FuzzEngine.run()` → render report → set exit code.

### 6.2 What lives where (no duplication)
| Concern | Location | Rationale |
|---------|----------|-----------|
| Meter, attacks, engine, findings model | `costbomb-core` | The IP; identical in both launches. |
| trace-format, persona-pack, report-renderer, agent-driver | **stampede** (shared primitive, vendored) | Portfolio rule: build in first consumer, extract at stampede v0.2. costbomb *consumes*, doesn't own. |
| `PersonaTarget` | stampede side (imports core) | Only the embedded path needs it. |
| `HTTP/Python/Mockworld` targets, CLI, CI gate, baseline files | standalone `costbomb` repo | Only the standalone path needs these. |

**Extraction path:** v0.1 core lives in-tree in stampede; v0.2 it graduates to this repo as `costbomb-core` + CLI, and stampede depends on it as a package. Because the seam was `Target` from day one, extraction is a *packaging* move, not a rewrite (RESEARCH G4).

---

## 7. Target adapters (`REQ-TA-*`)

| Adapter | `invoke` implementation | Metering | Safety |
|---------|-------------------------|----------|--------|
| `PersonaTarget` (v0.1) | Drive a stampede agent via agent-driver | SDK-wrapper | Runs in stampede's sandbox |
| `HTTPTarget` (v0.2) | POST input to agent endpoint | usage-field parse / proxy | `--allow-side-effects` required for real endpoints |
| `PythonTarget` (v0.2) | Import + call `module:handler` | SDK-wrapper | Same |
| `MockworldTarget` ⊕ (v0.2) | Run against mockworld fake services | SDK-wrapper | **Default safe target** — side-effects hit fakes (NFR-5) |

---

## 8. Tech stack

Python 3.11+; pure-Python search loop (no heavy deps, NFR-6); provider layer = Anthropic SDK + OpenAI-compatible + Ollama (NFR-3); price table vendored from LiteLLM/tokencost JSON; trace store SQLite/JSON; report via shared oxblood renderer; findings export as `findings.json` + OTel. LLM mutator defaults to Ollama/cheap model or off (NFR-4).

---

## 9. Architecture Decision Records

**ADR-1 — Fitness = p95 spend over k runs, not a single sample.**
*Context:* targets are non-deterministic. *Decision:* every candidate is run `k` times; fitness is the p95. *Consequence:* stable findings and a non-flaky CI gate at the cost of `k`× spend per candidate — mitigated by surrogate pre-ranking so only top-K get the full `k` runs.

**ADR-2 — Cost meter is a sum over sources, not tokens×price.**
*Context:* SPEC's token-only formula misses tool-storm and recursion. *Decision:* meter = model tokens + tool fees + recursive sub-agent rollup. *Consequence:* price table needs tool prices; trace needs parent/child spans (reuse stampede's). This is what makes 3 of the 5 attack classes measurable at all.

**ADR-3 — `Target` Protocol is the embedded/standalone seam.**
*Context:* two launches, one codebase. *Decision:* core depends only on `invoke(input)->Trace`; entrypoints supply the Target. *Consequence:* extraction from stampede is a packaging change, not a rewrite; both launches provably share one engine.

**ADR-4 — Surrogate estimator gates real spend.**
*Context:* the evaluator is expensive; a $2 cap must still yield a useful search. *Decision:* a dry-run estimator pre-ranks candidates; only top-K get paid confirmation runs. *Consequence:* dramatically better sample efficiency; estimator accuracy becomes a tracked metric (TEST-PLAN).

**ADR-5 — Default target is side-effect-free (mockworld/dry).**
*Context:* maximizing tool calls could fire real charges/emails. *Decision:* real systems require explicit `--allow-side-effects`; default is mockworld/dry-run. *Consequence:* safe-by-default; ties costbomb to mockworld and surfaces exactly-once risk in findings.

**ADR-6 — CI gate separates price drift from agent regression.**
*Context:* provider prices change weekly; a naive gate would fail builds on price hikes. *Decision:* re-price baseline inputs under the current table before comparing. *Consequence:* the gate measures *agent* regression only; requires storing baseline inputs, not just numbers.

**ADR-7 — Attack classes are pluggable from v0.1, authoring UX ships v0.3.**
*Context:* SPEC defers "custom attack authoring" to v0.3. *Decision:* the `AttackClass` interface + registry ship in core immediately; v0.3 only adds docs + external loading UX. *Consequence:* no refactor to add classes later; the ⊕ classes and community classes drop in cleanly.

**ADR-8 — Vendor price data + shared primitives; don't build or over-couple.**
*Context:* prices churn; portfolio primitives are still stabilizing. *Decision:* vendor LiteLLM/tokencost price JSON (refreshable) and vendor stampede primitives until stampede v0.2. *Consequence:* no premature `agent-reliability-core` coupling; matches the portfolio's "vendor first, extract later" rule.
