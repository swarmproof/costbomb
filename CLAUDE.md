# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status: design-phase, docs-only

There is **no source code yet** — no `pyproject.toml`, package, or tests. The repo is a
complete spec chain that any implementation must be traceable to. Do not invent build/lint/test
commands; they will exist once code lands. When you start implementing, honor the intended stack
below and wire the toolchain to match the spec (Python 3.11+, minimal deps).

**Intended stack (from the spec, not yet scaffolded):** Python 3.11+ · pure-Python search loop,
no heavy deps · provider layer = Anthropic SDK + OpenAI-compatible + Ollama · price table vendored
from LiteLLM/tokencost JSON · trace store SQLite/JSON. Package installs as `pip install costbomb`;
north-star CLI surface is `costbomb run --target <t> --budget <usd> --fail-on-regression`.

## What costbomb is

A **directed greybox fuzzer whose fitness function is dollars.** It hunts the inputs that make an
agent spend $500 to answer a $0.05 question ("denial-of-wallet"), ranks the worst offenders with
exact reproduction, and gates CI on spend regressions. Classic evolutionary fuzzing (seed →
evaluate → select → mutate) with three agent-specific twists: the evaluator is a *real, paid* agent
run; fitness is a *spend distribution*, not a scalar; the mutator *can be an LLM* because inputs are
natural language.

It is deliberately single-purpose. Non-goals (do not drift into these): general
prompt-injection/safety fuzzing, normal-case cost/FinOps dashboards, being an agent framework, or
runtime in-production spend enforcement.

## The spec chain — where the source of truth lives

Read these in order; later docs refine earlier ones and cite stable IDs (`REQ-*` functional,
`NFR-*` non-functional, `⊕` = scope beyond the original SPEC).

| Doc | Role |
|-----|------|
| `SPEC.md` | The original v1.0 pitch + PRD + architecture sketch. The seed everything traces back to. |
| `docs/RESEARCH.md` | Problem sharpening, 2026 landscape, prior art, gap analysis (`G1`..`G8`). Author-facing, not shipped. |
| `docs/PRD.md` | The binding requirements. `REQ-*`/`NFR-*` IDs here are **stable contracts** — cite them in code, commits, and tests. |
| `docs/ARCHITECTURE.md` | System design + 8 ADRs. Cross-references PRD REQ IDs inline. |
| `docs/DELIVERY-PLAN.md` | Milestones (M0–M3), WBS (W1–W30), sequencing, the two-launch plan. |
| `docs/TEST-PLAN.md` | Verification strategy; every `REQ-*`/`NFR-*` maps to ≥1 test ID. Meter-accuracy suite is dedicated. |

When implementing a work item, trace it: `WBS item → REQ/NFR IDs → test IDs`. New requirements must
map to a test — the CI job is spec'd to print an unmapped-requirement report.

## Architecture invariants (get these wrong and the tool is wrong)

**1. The cost meter is the oracle (ADR-2).** Everything optimizes against the dollar number the
meter produces; if the meter lies, the search optimizes a lie and the CI gate is meaningless. The
cost model is a **sum over sources**, *not* tokens×price:
`Σ model-call tokens (in/out/reasoning/cache-read/cache-write × price) + Σ tool-call fees + Σ recursive sub-agent spawn cost`.
The last two lines are exactly where `tool-storm` and `recursion` live — a token-only meter misses
them. The meter is the most rigorously tested, most provider-agnostic component (accuracy target
≤1%, NFR-8).

**2. The `Target` Protocol is the embedded/standalone seam (ADR-3, ARCHITECTURE §6).** This is the
single most important design decision. `costbomb-core` is a pure library that knows **only**
`invoke(input, ctx) -> Trace`. Two thin entrypoints supply the Target:
- **Embedded (v0.1, Launch 1):** `PersonaTarget` drives a stampede agent; costbomb ships *inside*
  stampede as the `adversarial:economic` cohort. Proves the engine on a real host.
- **Standalone (v0.2, Launch 2):** `HTTPTarget`/`PythonTarget`/`MockworldTarget` behind a CLI + CI gate.

**Build the core inside stampede first, then wrap it — do NOT build the CLI first.** The seam makes
extraction a *packaging* move, not a rewrite. A `FakeTarget`-only test suite must prove core has
zero stampede import.

**3. Own-budget cap is existential (NFR-1, ADR-5).** The fuzzer enforces a hard cap on its *own*
spend (`--max-spend`, default ~$2). A cost tool that blows its own budget is disqualifying — this
gates every release (E2E-4). Corollaries: side-effect-free by default (real systems need explicit
`--allow-side-effects`; default target is mockworld/dry); a dry-run **surrogate estimator**
pre-ranks candidates so real dollars are spent only confirming the top-K (ADR-4).

**4. Fitness = p95 spend over k runs, not a single sample (ADR-1).** Targets are non-deterministic;
a scalar would make findings and the CI gate flap. Every candidate runs `k` times (default 5).

**5. CI gate separates price drift from agent regression (ADR-6).** Re-price the baseline's stored
*inputs* under the current price table before comparing, so a provider price hike does not fail the
build — only a genuinely more-expensive-behaving agent does. This is why the baseline
(`.costbomb-baseline.json`) stores inputs, not just numbers, and is updated only intentionally.

## Shared contracts are vendored, not owned (ADR-8)

These live in the sibling **stampede** repo and are the authoritative contracts. costbomb *consumes*
them verbatim — never fork or reinvent them:
- **trace-format** = the OpenTelemetry GenAI semantic-conventions profile (`gen_ai.*` spans + the
  `swarmproof.*` cost/attack extension). Not a bespoke schema. Sub-agent cost rolls up via OTel
  parent/child span linkage.
- **report-renderer / `RunReport` model** = costbomb owns no renderer; it populates a `RunReport`
  economic-findings section, rendered as oxblood HTML + terminal. Embedded and standalone render
  from the identical model.
- **persona-pack** = `apiVersion: swarmproof.dev/persona/v1`; the `adversarial:economic` persona is
  authored in this schema.
- **agent-driver** = the shared agent execution driver `PersonaTarget` calls.

Portfolio rule: vendor first (LiteLLM price JSON, stampede primitives), extract later. Don't create
premature shared-core coupling. costbomb is one of seven projects in the **Swarm Proof** toolkit
(see README table).

## The attack library

Named cost-explosion classes, each an `AttackClass` implementing
`seeds()` / `mutate()` / `applicable()` / `signal()` (pluggable via registry from v0.1). `applicable()`
lets the engine honestly skip classes the target can't exhibit (e.g. `recursion` with no spawn
capability) and report the skip. `signal()` is the greybox feedback analog to code coverage.

- **v0.1 (5 SPEC classes):** `retry-loop`, `tool-storm`, `context-bomb`, `recursion`, `clarification-trap`.
- **v0.2 (⊕ 5 more):** `reasoning-inflation`, `model-escalation`, `cache-bust`, `tool-cost-asymmetry`, `retrieval-amplification`.

## Testing philosophy (when tests exist)

Two properties break normal test intuition: the oracle costs money, and the target is
non-deterministic. So the pyramid leans on **recorded fixtures** (frozen runs + true cost) and a
scripted deterministic **`FakeTarget`**; real paid runs are a small gated nightly suite. Assert on
distributions/bounds where a real LLM is involved. The meter-accuracy corpus (≥20 recorded runs
across providers, ≤1% error) is the highest-priority suite.

## Contributing conventions

- **Conventional Commits** (`feat:`, `fix:`, `docs:`, `refactor:`, `chore:`, ...), atomic, imperative
  mood, no AI attribution. Commit progressively as you go, not in one batch. (See `CONTRIBUTING.md`.)
- Toolkit principles: provider-agnostic (no single-vendor hard dep), honest over impressive (document
  boundaries, don't overpromise), watchable & reproducible (seedable, screenshot-worthy outputs).
- License: Apache-2.0. Citable via `CITATION.cff`.
