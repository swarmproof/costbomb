# costbomb — Product Requirements Document

*v1.0 design PRD. Companion to [`SPEC.md`](../SPEC.md), grounded in [`RESEARCH.md`](./RESEARCH.md).*
*Requirement IDs are stable contracts: `REQ-*` functional, `NFR-*` non-functional. `⊕` marks scope beyond the original SPEC.*

---

## 1. Vision

> **costbomb finds the input that makes your agent spend $500 to answer a $0.05 question — before a user (or an attacker) does — and fails your build when that number gets worse.**

It is a **directed fuzzer whose fitness function is dollars.** Where security fuzzers hunt crashes and eval harnesses hunt wrong answers, costbomb hunts **maximum measured spend** across named cost-explosion classes, ranks the worst offenders with exact reproduction, and gates CI on spend regressions. It ships first *inside* stampede as the `adversarial:economic` cohort, then extracts as a standalone CLI — two launches, one codebase.

**Product personality:** the sharp single-purpose tool. It does one thing — maximize and gate spend — and refuses to become an observability platform or an agent framework.

---

## 2. Goals & non-goals

### 2.1 Goals
- **G1** Given any callable agent (HTTP endpoint, Python harness, or stampede persona), generate adversarial inputs that **maximize true measured spend** across the attack library.
- **G2** Meter **true dollars** per run = tokens×price **+** tool-call fees **+** sub-agent spawn cost, provider-agnostic, attributable to the triggering input.
- **G3** Rank the worst offenders with **exact, replayable reproduction** and the class that triggered each.
- **G4** Provide a **CI gate**: fail the build when worst-case spend exceeds a budget or **regresses vs a committed baseline**.
- **G5** Run **safely and cheaply**: a hard cap on the fuzzer's *own* spend, dry-run estimation, and side-effect-free defaults.
- **G6** ⊕ Ship as a **shared core** with two thin entrypoints (embedded-in-stampede + standalone CLI) so both launches run one implementation.

### 2.2 Non-goals
- **NG1** General prompt-injection / safety fuzzing (garak/PyRIT's job — costbomb *complements*, exports alongside).
- **NG2** Optimizing normal-case cost / FinOps dashboards (Helicone/Langfuse's job).
- **NG3** Being an agent framework or orchestration runtime (stampede *drives* agents; costbomb *attacks* their economics).
- **NG4** Runtime, in-production spend enforcement (Waxell/TrueFoundry's job — costbomb *discovers the ceiling*, then can *emit their config* ⊕, but does not sit in the request path).
- **NG5** Guaranteeing it finds *the* global worst input — it is a heuristic search, not a solver. It finds *bad* inputs and gates on *regression*, honestly.

---

## 3. Personas (from RESEARCH §5)

| ID | Persona | Primary need | Entry surface |
|----|---------|--------------|---------------|
| P1 | Agent product engineer | Pre-launch worst-case proof | CLI `costbomb run` |
| P2 | Platform / SRE | Defensible spend ceiling | CLI + policy file |
| P3 | CI / release engineer | Regression gate | CLI `--fail-on-regression` in CI |
| P4 ⊕ | Security / red-team | Economic attacks in the red-team | CLI + report export to garak/PyRIT-adjacent format |
| P5 | stampede user | Economic adversaries in a swarm | `adversarial:economic` cohort in `stampede.yaml` |
| P6 ⊕ | FinOps / eng manager | Tail-risk $ for the risk register | Report summary number |

---

## 4. Functional requirements

### 4.1 Cost meter (`REQ-CM-*`) — the ground truth

| ID | Requirement | Priority |
|----|-------------|----------|
| REQ-CM-1 | Meter MUST compute per-run cost as a **sum over cost sources**: `Σ(input_tokens×in_price + output_tokens×out_price)` per model call **+** `Σ tool_call_price` **+** `Σ sub_agent_spawn_cost`. | v0.1 |
| REQ-CM-2 | Meter MUST support ⊕ **reasoning/thinking tokens** and ⊕ **cache-read vs cache-write** token classes at their distinct prices (2026 pricing reality). | v0.1 |
| REQ-CM-3 | Pricing MUST come from a **provider-agnostic price table** (JSON) keyed by model id, with fields `input_cost_per_token`, `output_cost_per_token`, `cache_read_cost_per_token`, `reasoning_cost_per_token`, `tool_prices{}`. Vendored from the LiteLLM/tokencost registry, refreshable, `--price-table` overridable. | v0.1 |
| REQ-CM-4 | Meter MUST attribute all spend — including **sub-agent/child spans** — to the single triggering input via OTel parent/child span linkage, emitted in stampede's authoritative trace-format: the **OpenTelemetry GenAI semantic-conventions profile** (`gen_ai.*` spans + the `swarmproof.*` cost/attack extension), not a bespoke schema. | v0.1 |
| REQ-CM-5 | Meter MUST support three attachment modes: (a) **SDK-wrapper** (wrap the provider client, read usage), (b) **usage-field parse** (read provider response usage), (c) ⊕ **proxy** adapter. Default: SDK-wrapper. | v0.1 (a/b), v0.2 (c) |
| REQ-CM-6 | Meter MUST emit a per-run **cost breakdown** (by source, by model, by tool) into the trace, not just a total. | v0.1 |
| REQ-CM-7 | Meter MUST provide a **dry-run estimator**: predict a candidate's cost from trace *shape* without a paid run, flagged as estimated. | v0.2 |
| REQ-CM-8 | ⊕ Meter MUST support **re-pricing** a recorded run against a different price table (provider what-if). | v0.3 |

### 4.2 Attack library (`REQ-AL-*`) — named cost-explosion classes

| ID | Requirement | Priority |
|----|-------------|----------|
| REQ-AL-1 | Ship the five SPEC classes as seed strategies: `retry-loop`, `tool-storm`, `context-bomb`, `recursion`, `clarification-trap`. | v0.1 |
| REQ-AL-2 | ⊕ Ship additional 2026-relevant classes: `reasoning-inflation`, `model-escalation`, `cache-bust`, `tool-cost-asymmetry`, `retrieval-amplification` (see RESEARCH §6.2). | v0.2 |
| REQ-AL-3 | Each attack class MUST implement a common `AttackClass` interface: `seeds() -> [Input]`, `mutate(input, rng) -> Input`, `applicable(target_caps) -> bool`. | v0.1 |
| REQ-AL-4 | Attack classes MUST be **pluggable** — discoverable via entry points / a registry so external classes load without forking. | v0.1 (interface), v0.3 (docs+authoring UX) |
| REQ-AL-5 | ⊕ `applicable()` MUST let the engine **skip classes the target can't exhibit** (e.g., skip `recursion` if the target can't spawn) and report which were skipped. | v0.2 |
| REQ-AL-6 | ⊕ Import an **agent-postmortems `cost-blowup` incident** as a seed ("replay last month's incident"). | v0.3 |

### 4.3 Fuzz engine (`REQ-FE-*`) — search toward max spend

| ID | Requirement | Priority |
|----|-------------|----------|
| REQ-FE-1 | Engine MUST run a **directed search** that maximizes measured spend: seed → evaluate → keep highest-cost → mutate → repeat. Baseline strategy: greybox evolutionary loop with a seed queue (AFL-style), fitness = spend. | v0.2 |
| REQ-FE-2 | Fitness MUST be a **distribution-aware statistic** (default `p95 spend over k runs`, `k` configurable), not a single sample — the target is non-deterministic. | v0.2 |
| REQ-FE-3 | Engine MUST apply a **power schedule** — allocate more mutation energy to higher-yield seeds (AFLFast-style reward). | v0.2 |
| REQ-FE-4 | Engine MUST support **template mutators** (no LLM) as default and ⊕ an **optional LLM-assisted mutator** ("make this input more likely to cause a retry loop"). | v0.1 (template), v0.2 (LLM) |
| REQ-FE-5 | Engine MUST have explicit **stopping criteria**: global budget exhausted, plateau (no improvement in N generations), or wall-clock limit — whichever first. | v0.2 |
| REQ-FE-6 | Engine MUST be **seedable** (`--seed`) for reproducible searches. | v0.1 |
| REQ-FE-7 | ⊕ Engine SHOULD use the **dry-run estimator (REQ-CM-7)** as a cheap surrogate to pre-rank candidates, confirming only top-K with real paid runs (sample efficiency). | v0.2 |

### 4.4 Reporter (`REQ-RP-*`)

| ID | Requirement | Priority |
|----|-------------|----------|
| REQ-RP-1 | Rank worst offenders with: the $ each caused, the **breakdown by source**, the **class** that triggered, and **exact reproduction** (the input + seed + run config). | v0.1 |
| REQ-RP-2 | Populate the shared **`RunReport`** model with an economic-findings section and render it via the shared **report-renderer** (oxblood HTML + terminal). costbomb owns no renderer; embedded and standalone paths render from the identical `RunReport`. | v0.1 |
| REQ-RP-3 | Report MUST show the **amplification factor** ("5¢ baseline → $5.20 worst case = 104×") as the headline number. | v0.1 |
| REQ-RP-4 | ⊕ Report MUST flag findings where a storming/looping tool has **side-effects** → duplicate-charge risk (exactly-once cross-check). | v0.3 |
| REQ-RP-5 | ⊕ Report MUST be **exportable** to the shared trace-format (the OTel GenAI profile: `gen_ai.*` + `swarmproof.*`, for Langfuse/OTel-backend import) and a machine-readable `findings.json`. | v0.2 |

### 4.5 CI gate (`REQ-CI-*`)

| ID | Requirement | Priority |
|----|-------------|----------|
| REQ-CI-1 | `costbomb run --budget <USD> --fail-on-regression` MUST exit non-zero when worst-case found spend **exceeds `--budget`** OR **regresses vs the committed baseline** beyond a tolerance. | v0.2 |
| REQ-CI-2 | MUST read/write a committed **baseline** (`.costbomb-baseline.json`) recording worst-case spend per class + the price-table version used. | v0.2 |
| REQ-CI-3 | ⊕ Regression check MUST **separate price-driven from agent-driven** changes — re-price the baseline's inputs under the current table before comparing, so a provider price hike doesn't fail the build. | v0.2 |
| REQ-CI-4 | MUST provide a `--dry-run` (no-LLM/heuristic) **CI smoke mode** that runs in seconds for fast PR checks. | v0.2 |
| REQ-CI-5 | MUST ship a copy-paste **GitHub Actions** snippet and a non-zero-exit contract documented for any CI. | v0.2 |
| REQ-CI-6 | ⊕ `costbomb baseline update` MUST regenerate the baseline intentionally (never auto-updated on regression). | v0.2 |

### 4.6 Spend-ceiling policy (`REQ-SP-*`) ⊕

| ID | Requirement | Priority |
|----|-------------|----------|
| REQ-SP-1 | ⊕ `spend_ceiling` policy: declare a max $/run per workflow; costbomb proves whether any found input breaches it. | v0.3 |
| REQ-SP-2 | ⊕ Emit an **enforcement config** for runtime enforcers (token-budget/rate-limit gateways) derived from the discovered ceiling. | v0.3 |

### 4.7 Target adapters (`REQ-TA-*`)

| ID | Requirement | Priority |
|----|-------------|----------|
| REQ-TA-1 | `HTTPTarget`: POST inputs to an agent HTTP endpoint; meter via response usage fields or wrapped client. | v0.2 |
| REQ-TA-2 | `PythonTarget`: import and call a Python agent harness (`./agent.py:handler`); meter via SDK-wrapper. | v0.2 |
| REQ-TA-3 | `PersonaTarget`: run as a stampede `adversarial:economic` persona against a stampede target (the embedded path). | v0.1 |
| REQ-TA-4 | ⊕ `MockworldTarget`: default safe target — run attacks against mockworld's fake services so side-effects never hit real systems. | v0.2 |
| REQ-TA-5 | Adapter interface: `invoke(input, run_ctx) -> Trace` where `Trace` carries the cost breakdown. | v0.1 |

---

## 5. Non-functional requirements

| ID | Requirement | Rationale |
|----|-------------|-----------|
| NFR-1 **Own-budget cap** | The fuzzer MUST enforce a hard cap on its **own** total spend (`--max-spend`, default e.g. $2.00); it stops before exceeding it and reports partial results. The tool that finds runaway spend must not itself run away. | Existential — a cost tool that blows the budget is dead on arrival. |
| NFR-2 **Determinism** | Same `--seed` + same price table + `temp=0` + fixed model MUST yield the same search trajectory and reproducible findings (modulo target non-determinism, quantified by `k`). | CI stability; reproducible repro. |
| NFR-3 **Provider-agnostic** | Any OpenAI-compatible endpoint + Anthropic SDK + Ollama; pricing purely table-driven — no provider hardcoded in logic. | Portfolio standard; avoids lock-in. |
| NFR-4 **Local-friendly / cheap mutation** | LLM-assisted mutation MUST default to a cheap/local model (Ollama) or be disabled; template mutators need no LLM at all. | Keeps the fuzzer's own cost near zero. |
| NFR-5 **Side-effect safety** | Default target is side-effect-free (mockworld/dry). Hitting a real system requires explicit `--allow-side-effects`. `tool-storm`/`recursion` findings note duplicate-effect risk. | Fuzzing for max tool calls could fire real charges/emails. |
| NFR-6 **No heavy deps** | Search loop in pure Python; core has minimal dependencies; store defaults to SQLite/JSON. | Portfolio standard; easy install. |
| NFR-7 **Fast CI mode** | `--dry-run` smoke completes in < ~10s with no paid calls. | PR gate must be fast. |
| NFR-8 **Portable meter accuracy** | Metered $ MUST match provider-reported cost within a documented tolerance (target ≤ 1% on token costs given a correct table). | The meter is the oracle; if it lies, the search optimizes a lie. |
| NFR-9 ⊕ **Trace-format compatibility** | Emit the shared, authoritative trace-format — the **OpenTelemetry GenAI semantic-conventions profile** (`gen_ai.*` spans + the `swarmproof.*` extension) — so findings interoperate natively with stampede, Langfuse, and any OTel GenAI backend. No generic or bespoke schema. | Portfolio interop. |
| NFR-10 **Graceful degradation** | With no LLM available, template attacks + dry-run estimation still run and still gate CI. | mcp-probe-style no-LLM baseline. |

---

## 6. Complete feature set by tier

| Tier | Feature | REQ refs | Attack classes |
|------|---------|----------|----------------|
| **v0.1 — inside stampede** | Cost meter (tokens+tools+spawns, breakdown, attribution); `AttackClass` interface; 5 SPEC classes as seed strategies (template mutation only); `PersonaTarget`; shared `RunReport` findings section (report-renderer); own-budget cap; seedable. | CM-1..6, AL-1/3/4(iface), FE-4(template)/6, RP-1/2/3, TA-3/5, NFR-1/2/3/6/9 | retry-loop, tool-storm, context-bomb, recursion, clarification-trap |
| **v0.2 — standalone extract + CLI + CI gate** | Standalone CLI; full **fuzz search engine** (evolutionary + power schedule + p95 fitness + LLM mutator + stopping criteria + surrogate); `HTTPTarget`/`PythonTarget`/`MockworldTarget`; **CI gate** + baseline + price-separation + dry-run smoke; findings.json/OTel export; dry-run estimator; ⊕ 5 extra attack classes. | CM-5(c)/7, AL-2/5, FE-1/2/3/4(LLM)/5/7, RP-5, CI-1..6, TA-1/2/4, NFR-4/5/7/8/10 | + reasoning-inflation, model-escalation, cache-bust, tool-cost-asymmetry, retrieval-amplification |
| **v0.3 — policy + ecosystem** | Custom attack authoring (docs+external loading); **spend-ceiling policy** + enforcer-config emit; **exactly-once** duplicate-effect cross-check; **agent-postmortems** incident-as-seed; provider what-if re-pricing. | AL-4(UX)/6, RP-4, SP-1/2, CM-8 | + community/custom classes |

---

## 7. Success metrics

| Metric | Target | Source |
|--------|--------|--------|
| **North star** | # repos gating CI on a costbomb budget (`.costbomb-baseline.json` committed). | PORTFOLIO north star. |
| Category | "denial-of-wallet" entering common usage with costbomb as reference tool; term registered in awesome-agent-reliability + agent-postmortems taxonomy. | SPEC §1.5. |
| Discovery efficacy | On a known-vulnerable demo agent, costbomb finds a ≥50× amplification input within its default own-budget cap, unattended. | TEST-PLAN acceptance. |
| Meter accuracy | Metered $ within ≤1% of provider-reported cost on token costs (correct table). | NFR-8. |
| Two-launch | Both the stampede `adversarial:economic` cohort and the standalone CLI run the same `costbomb-core`. | G6. |
| Adoption depth | ≥3 external repos with costbomb in CI within 60 days of standalone launch; ≥1 community attack class contributed. | Launch goal. |

---

## 8. Dependencies

- **stampede** (shared core home) — costbomb consumes these now-authoritative contracts verbatim, does not fork them:
  - **trace-format** = the OpenTelemetry GenAI semantic-conventions profile (`gen_ai.*` + `swarmproof.*` extension).
  - **persona-pack** = `apiVersion: swarmproof.dev/persona/v1`; the `adversarial:economic` persona + its attack-library playbook are authored in this schema.
  - **report-renderer** = the shared `RunReport` model rendered to oxblood HTML + terminal.
  - **agent-driver** = the shared agent execution/driver used by `PersonaTarget`.
  costbomb v0.1 lives *inside* stampede's repo/cohort; extraction depends on these APIs stabilizing (~stampede v0.2).
- **Price data**: LiteLLM `model_prices_and_context_window.json` / tokencost registry (vendored, refreshable).
- **mockworld**: default safe target for side-effect-bearing attacks (v0.2).
- **exactly-once**: duplicate-side-effect cross-check (v0.3).
- **agent-postmortems**: `cost-blowup` incident seeds (v0.3).
- **Provider layer**: Anthropic SDK + OpenAI-compatible + Ollama (provider-agnostic).

## 9. Assumptions & constraints

- **A1** The target exposes enough usage data to meter accurately (usage fields or a wrappable client). If not, costbomb falls back to token-counting the wire and estimating — documented as lower-accuracy.
- **A2** Prices change frequently; the table is versioned and the CI gate separates price drift from agent regression (REQ-CI-3).
- **A3** The search is heuristic (NG5) — success = finding *bad* inputs and gating *regressions*, not proving a global optimum.
- **A4** Running attacks costs money; the own-budget cap (NFR-1) is the primary safety and adoption constraint — every feature is designed to stay under it.
- **A5** Some attacks assume target capabilities (spawning, tools); `applicable()` gates them and the report states coverage honestly.
- **C1** Portfolio constraints: Apache-2.0, Python 3.11+, minimal deps, provider-agnostic, local-friendly.
