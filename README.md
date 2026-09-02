# costbomb

### Denial-of-wallet fuzzing for agent systems

> Find the inputs that make your agent spend $500 to answer a $0.05 question. A fuzzer for economic failure: it hunts the prompts, tool-call loops, and context explosions that blow up your bill, and gates CI on spend regressions.

<!-- TODO: demo GIF — a benign input running an agent's bill from 5¢ to $5, then costbomb finding it -->
<p align="center"><em>▶ demo GIF coming — costbomb automatically finding the input that runs the bill from 5¢ to $5</em></p>

> **Status:** 🚧 `v0.2` in progress. `costbomb-core` is implemented and runnable standalone (below). It ships first *inside* [stampede](https://github.com/swarmproof/stampede)'s `adversarial:economic` cohort (the embedded path), and this repo is the standalone extract. See [Two launches, one codebase](#two-launches-one-codebase).

---

## Why

Agent systems have a failure mode traditional software doesn't: **they can be made to spend unbounded money.** A crafted input sends an agent into a retry loop, a runaway tool-call chain, a context-window explosion, or a recursive sub-agent spawn — each burning tokens and dollars. This "denial-of-wallet" class is real, under-tooled, and terrifying for anyone running agents in production with a company card attached. Security fuzzers hunt crashes; **costbomb hunts spend.**

The failure is invisible to every other quality gate: an agent under a denial-of-wallet attack **succeeds** — no exception, no failed assertion, no red test. It just charged you $500. The oracle everyone else uses is the wrong oracle. **costbomb's oracle is the invoice.**

## Quickstart

```bash
# v0.2 — from source (not yet on PyPI):
git clone https://github.com/swarmproof/costbomb && cd costbomb
python -m venv .venv && .venv/bin/pip install -e .

# Crack the bundled 5¢→$5 demo agent automatically, under a $2 self-cap:
costbomb run --target examples/demo_agent.py:handler
```

```
╭───────────────────── costbomb · denial-of-wallet ─────────────────────╮
│ 0.10¢ → $0.21 = 211× amplification                                    │
╰────────────── seed 1337 · own spend $1.83 · budget-capped ────────────╯
 #  class              worst $   ×    breakdown (model / tool / spawn)   flags
 1  retry-loop          $0.21   211×  $0.19 / $0.02 / 0.00¢              side-effect
 2  tool-storm          $0.08    …    …
 …
 skipped (target can't exhibit): recursion
```

Point it at your own agent (Python harness or HTTP endpoint), and gate CI on it:

```bash
costbomb run --target ./agent.py:handler --seed 1337          # explore
costbomb baseline update --target ./agent.py:handler          # commit .costbomb-baseline.json
costbomb run --target ./agent.py:handler --fail-on-regression # CI gate on spend regressions
costbomb run --target ./agent.py:handler --dry-run            # fast, zero-paid-call CI smoke
costbomb run --target ./agent.py:handler --use-llm            # optional LLM-assisted mutation (local Ollama by default)
costbomb run --target mock:./agent.py:handler                 # safe default: side-effects hit mockworld fakes, no --allow-side-effects
```

Template mutation is the default and needs no LLM. `--use-llm` lets a cheap/local model rewrite candidates toward more spend — and its own token cost is charged against the same `--max-spend` cap (the fuzzer can't secretly overspend on mutation), with automatic fallback to template mutation if the model is unavailable.

Your agent's handler returns what it *spent* (a `RunRecord` of model calls, tool calls, and sub-agent spawns), or emits the OTel GenAI trace directly. costbomb meters that truthfully — see [`examples/demo_agent.py`](./examples/demo_agent.py).

## The attack library

Named cost-explosion classes, each a seed strategy the fuzz engine mutates toward maximum spend:
`retry-loop` · `tool-storm` · `context-bomb` · `recursion` · `clarification-trap`.
Each declares whether it `applies()` to your target, so coverage is honest ("skipped `recursion` — target has no spawn capability"). The reporter ranks the worst offenders with exact reproduction, the $ each caused (broken down by model / tool / spawn), and which class triggered — then the **CI gate** fails the build if worst-case cost regresses.

## How it works

A **directed greybox fuzzer with a dollar-valued fitness function** (seed → evaluate → select → mutate), with three agent-specific twists:

- **The cost meter is the oracle** — true dollars is a *sum over sources*: model tokens (input/output/reasoning/cache) **+** tool-call fees **+** recursive sub-agent spawn cost. A token-only meter misses exactly where `tool-storm` and `recursion` live.
- **Wall-clock / infra cost** — set an `infra.usd_per_second` rate in the price table and costbomb prices a run's *duration* (GPU-seconds, serverless time) into `total_usd`. The "$47k over 11 days" shape where time, not tokens, is the cost. On the demo slow agent, a 20s loop costs $0.20 of compute against a ~0.2¢ token bill.
- **Blast radius, not just the token bill** — a side-effecting tool (`charge_card`, `place_order`) carries a `downstream_usd` consequence cost in the price table. costbomb reports both the agent's **direct bill** (`total_usd`) and the **blast radius** (`blast_radius_usd` = direct + real money moved), and can *search* for the worst blast radius with `--fitness blast_radius_usd`. On the demo refund agent, a 0.07¢ bill hides an **$1,700** blast radius.
- **Exactly-once / duplicate-charge risk** — when a loop re-fires a side-effecting tool for the *same business key* (34 charges to one order), costbomb costs the repeats as `duplicate_effect_usd`. It dedupes on business identity (34 charges to 34 *different* orders is $0, not a bug), honors calls the agent already deduped, and — with `pip install costbomb[exactly-once]` — **cross-checks against the real [`exactly-once`](https://github.com/swarmproof/exactly-once) middleware** (running the calls through `@once`) rather than guessing: *"$1,650 in duplicate effects — charge_card×34, only 1 intended"*.
- **Fitness is p95 over k runs**, not one sample — the target is non-deterministic, so a scalar would make findings and the CI gate flap.
- **A surrogate estimator pre-ranks candidates** so real dollars are spent only confirming the promising ones — and the whole search runs under a **hard cap on the fuzzer's own spend** (`--max-spend`, default $2). The tool that finds runaway spend must never run away itself.

The CI gate **separates price drift from agent regression** (REQ-CI-3): it re-prices the baseline's recorded inputs under the current price table before comparing, so a provider raising prices doesn't fail your build — only a genuinely more-expensive-behaving agent does.

### GitHub Actions

```yaml
# .github/workflows/costbomb.yml
name: costbomb
on: [pull_request]
jobs:
  denial-of-wallet:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install costbomb
      - run: costbomb run --target ./agent.py:handler --fail-on-regression --dry-run
```

## Two launches, one codebase

costbomb is deliberately one core with two thin entrypoints (the `Target` protocol is the seam):

1. **Embedded (launch 1):** `costbomb-core` runs *inside* stampede as the `adversarial:economic` cohort — its findings appear as the economic section of stampede's Agent Readiness Report. This proves the engine on a real host.
2. **Standalone (launch 2):** the same core, extracted behind this CLI + CI gate — *"denial-of-wallet fuzzing for AI agents."*

Because the seam is `Target.invoke(input) -> Trace` from day one, extraction is a *packaging* move, not a rewrite. costbomb consumes stampede's shared contracts (the OTel GenAI trace profile, the `RunReport` model, the persona-pack schema) verbatim — vendored under [`src/costbomb/_vendor/`](./src/costbomb/_vendor/) until stampede publishes them as a package. See [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) §6.

## Metering a real agent (no instrumentation)

Real agents aren't `./agent.py:handler` files — they're live services, framework
graphs, MCP servers, or product sessions. costbomb needs two things from any of them:
to **drive** it with adversarial inputs, and to **meter** what each run costs. The
low-friction way to meter is the **proxy** — point your agent's model `base_url` at
costbomb and every LLM call is metered automatically, with **zero code changes**:

```bash
costbomb proxy --upstream https://api.anthropic.com --port 8100
# then set your agent's model base_url to http://127.0.0.1:8100
```

```
   your agent (unchanged)
        │  base_url → costbomb proxy      ← one env var; the whole integration
        ▼
   costbomb meter ── forwards ──▶  Anthropic / OpenAI / any compatible upstream
        │  reads real usage per call (input/output/reasoning/cache), prices it
        ▼
   fuzzer drives inputs via your agent's existing endpoint; brackets each run
```

- **In-process agents** (a framework graph, direct-SDK code): use `ProxyTarget` — it
  brackets one driven input as one metered run while the agent's calls flow through a
  shared `ProxyMeter`. No `RunRecord`, no handler.
- **Out-of-process agents** (HTTP/MCP service): run `costbomb proxy`; the fuzzer
  brackets a run with `POST /costbomb/run/start` … `/finish`, and calls carrying an
  `x-costbomb-run` header are attributed to it.

Because fuzzing has to *try* inputs (you can't find the worst input from passive
logs), costbomb always drives the agent through the interface it already exposes —
but metering never requires touching the agent's code. A useful side effect: a proxy
sitting in front of a real provider records real usage, which is exactly what the
meter-accuracy corpus needs (below).

## Validation status (read before trusting the numbers)

costbomb is **implemented and internally consistent, not yet validated against reality.**
Being honest about this matters more for a cost tool than for most software: the whole
product rests on the meter being right, and that claim isn't proven yet.

| Proven (synthetic / unit) | Not yet validated (needs real runs) |
|---|---|
| Cost-meter **arithmetic** — token classes, tool fees, sub-agent roll-up (meter-accuracy harness, synthetic fixtures) | **Meter ≤1% vs a real provider invoice (NFR-8)** — needs ≥20 recorded real runs; the corpus test currently **skips** at `0/20` |
| Hard own-budget cap holds across seeds (incl. LLM-mutation cost) | The 5¢→$5 story on a **real** LLM agent — only the scripted demo agent is cracked so far |
| Determinism, gate red/green + price-drift-separation **logic** | Gate non-flakiness at recommended `k` on a **real** non-deterministic target |
| Side-effect-free default; no-LLM/dry-run mode | Embedded path against a **real** stampede agent (`PersonaTarget` tested with a fake driver); `MockworldTarget` / `LLMMutator` against real backends (stub / mocked) |

Until the real meter-accuracy corpus exists and passes, treat costbomb as a
well-engineered prototype whose oracle is unproven. See
[`tests/fixtures/meter/README.md`](./tests/fixtures/meter/README.md) to add real fixtures.

## Design docs

[`SPEC.md`](./SPEC.md) · [`docs/PRD.md`](./docs/PRD.md) (REQ/NFR IDs) · [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) (ADRs) · [`docs/DELIVERY-PLAN.md`](./docs/DELIVERY-PLAN.md) · [`docs/TEST-PLAN.md`](./docs/TEST-PLAN.md) · [`CLAUDE.md`](./CLAUDE.md).

## Development

```bash
pip install -e ".[dev]"
pytest            # unit → integration → e2e + meter-accuracy corpus, mapped to the test plan
ruff check src tests
```

## Part of the Swarm Proof toolkit

*Trust infrastructure for the agent economy — seven projects, one thesis.*

| Project | What it does |
|---------|--------------|
| [stampede](https://github.com/swarmproof/stampede) | Point a herd of realistic agents at your system before real ones arrive |
| [mockworld](https://github.com/swarmproof/mockworld) | A synthetic internet for agents — fake Stripe, Gmail, exchange, instantly |
| [mcp-probe](https://github.com/swarmproof/mcp-probe) | The CI quality suite for MCP servers — lint, contract-test, benchmark, load |
| **costbomb** ← *you are here* | Denial-of-wallet fuzzing — find the inputs that make your agent spend $500 |
| [exactly-once](https://github.com/swarmproof/exactly-once) | Idempotency middleware so agent side-effects fire once |
| [agent-postmortems](https://github.com/swarmproof/agent-postmortems) | A structured incident database + post-mortem standard for agent failures |
| [awesome-agent-reliability](https://github.com/swarmproof/awesome-agent-reliability) | The curated map of the field |

## License

[Apache-2.0](./LICENSE). Strict global budget cap on the fuzzing run itself; cheap/local models for mutation. Citable via [`CITATION.cff`](./CITATION.cff).
