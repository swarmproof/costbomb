# costbomb — RESEARCH

*Problem sharpening, 2026 landscape, prior art, and gap analysis for denial-of-wallet fuzzing.*
*Status: design-phase research. Companion to [`SPEC.md`](../SPEC.md). Author-facing; not shipped in the published README.*

---

## 0. TL;DR for the impatient

- The field has a mature stack for **watching** LLM spend after it happens (Helicone, Langfuse) and a mature stack for **red-teaming for correctness/safety** (garak, PyRIT, Promptfoo). **Nobody drives an adversarial search whose fitness function is dollars.** That is costbomb's lane, and a 2026 paper says it out loud: *"No existing framework addresses the token economics of agent testing."* ([AgentAssay, arXiv 2603.02601](https://arxiv.org/html/2603.02601))
- "Denial of Wallet" (DoW) is a **named, peer-reviewed threat class** — but every published treatment is about **serverless/FaaS billing**, not agents. costbomb can legitimately own the *agentic* definition of the term. ([arXiv 2104.08031](https://arxiv.org/pdf/2104.08031), [arXiv 2508.19284](https://arxiv.org/abs/2508.19284))
- The incidents are real and expensive: a **$47,000 / 11-day** multi-agent ping-pong loop (Nov 2025) and a **1.67 billion token / ~$16–50k** Claude Code recursion (Jul 2025). These aren't hypotheticals — they're fuzz seeds. ([Waxell](https://dev.to/waxell/the-47000-agent-loop-why-token-budget-alerts-arent-budget-enforcement-389i), [getunblocked](https://getunblocked.com/blog/agent-auto-loop-token-cost/))
- The academic lineage costbomb should claim: **sponge examples** (Shumailov et al., 2021) — inputs crafted to maximize a model's *energy/latency*. costbomb is sponge examples for the agent economy: inputs crafted to maximize *dollars*, one abstraction layer up (tokens + tool calls + sub-agents, not FLOPs).

---

## 1. The problem, sharpened

The SPEC frames it correctly but softly. Let me sharpen the thesis into three claims a skeptic must accept:

**Claim 1 — Cost is an uncapped attack surface, structurally distinct from crashes.**
Traditional software has a bounded blast radius per request: a bad input crashes a handler, returns a 500, or corrupts one row. An agent's blast radius per input is **unbounded in dollars** because the agent chooses how much work to do. One input can trigger an arbitrary-length chain of model calls, tool calls, and sub-agent spawns. The cost is a function of the agent's *behavior*, not the input's *size* — a 20-token prompt can provoke a 1.6-billion-token response chain.

**Claim 2 — The failure is invisible to every existing quality gate.**
An agent under a denial-of-wallet attack **succeeds**. No exception, no non-zero exit, no failed assertion, no red test. It returns a correct answer — it just charged you $500 to do it. This is why fuzzers that hunt crashes (`libFuzzer`, `AFL`), evals that hunt wrong answers (`agentevals`), and injection scanners that hunt policy violations (`garak`) all sail straight past it. As one 2026 write-up puts it: *"an AI agent can 'succeed' (no crash, no error code) while completely failing at its job."* ([witness.ai](https://witness.ai/blog/ai-fuzzing/)) The oracle everyone else uses is the wrong oracle. **costbomb's oracle is the invoice.**

**Claim 3 — Alerting is not defense, and neither is a per-call cap.**
The field's current answer is budget *alerts* (Helicone fires at 50/80/95%) and per-request token caps. Both are post-hoc or per-hop. They do not answer the pre-production question: *"does an input exist that makes my agent spend 100× the expected amount, and what is it?"* You cannot alert your way out of a $47k loop that ran for 11 days ([Waxell](https://dev.to/waxell/the-47000-agent-loop-why-token-budget-alerts-arent-budget-enforcement-389i)). You have to **find the input before you ship**, and you have to **gate CI so a refactor doesn't reintroduce it**. That is a fuzzing-and-regression problem, not an observability problem.

**Reframed one-liner (sharper than the SPEC's):**
> Observability tells you what your agent *did* spend. costbomb tells you what your agent *can be made* to spend — and fails your build when that number gets worse.

---

## 2. The 2026 landscape (named tools, URLs, and exactly where each stops)

I bucket the field into four camps. costbomb sits in the empty intersection of "adversarial search" and "cost as the objective."

### 2.1 Camp A — Cost observability / FinOps for LLMs (measure spend, passively)

| Tool | What it does | Where it stops (the gap costbomb fills) |
|------|--------------|------------------------------------------|
| **Helicone** | Proxy-based logging; per-request/user/model cost attribution; budget alerts at 50/80/95%; OSS cost repo with 300+ model prices. ([docs.helicone.ai](https://docs.helicone.ai/guides/cookbooks/cost-tracking)) | **Passive & reactive.** Measures production traffic that already happened. No adversarial input generation, no search, no pre-prod gate. Its price repo is a *reusable asset* for costbomb's meter. |
| **Langfuse** | Span-tracing; per-observation token+cost; OTel GenAI exporter; breakdown by usage type. ([langfuse.com](https://langfuse.com/docs/observability/features/token-and-cost-tracking)) | Same: it renders the trace tree *after* a run. costbomb's trace format is deliberately OTel-compatible so its findings **export into** Langfuse. Complement, not competitor. |
| **LangSmith / Portkey / TokenMix / nOps** | Framework-native tracing; gateway routing; cost-optimization advisories. ([particula.tech](https://particula.tech/blog/helicone-vs-langfuse-vs-langsmith-llm-observability), [nOps](https://www.nops.io/blog/llm-cost-optimization-tools/)) | Optimize the **normal-case** bill (cheaper model, caching). costbomb optimizes the **worst-case** bill. Different tail of the distribution. |
| **Waxell / TrueFoundry / LeanOps** | *Runtime* token-budget **enforcement** — hard stop, not alert; 3-layer rate-limiting gateways. ([waxell.ai](https://waxell.ai/blog/ai-agent-token-budget-enforcement), [TrueFoundry](https://www.truefoundry.com/blog/rate-limiting-ai-agents-preventing-llm-api-exhaustion)) | These are the **runtime seatbelt**; costbomb is the **crash test**. They enforce a ceiling in prod; costbomb *discovers what the ceiling should be* and proves inputs that would hit it. Natural downstream integration (v0.3 spend-ceiling policy emits their config). |

**Takeaway:** the entire FinOps camp is *read-only on real traffic*. None of them generate the adversarial input. costbomb's cost meter can and should **reuse their price data** (LiteLLM/Helicone JSON) rather than reinvent it.

### 2.2 Camp B — LLM/agent security red-teaming (adversarial, but the objective is a policy violation)

| Tool | What it does | Why it is not costbomb |
|------|--------------|------------------------|
| **garak** (NVIDIA) | LLM vuln scanner, 120+ probe modules: prompt injection, jailbreak (DAN), encoding bypass, data leak, toxicity. The "scanner." ([appsecsanta](https://appsecsanta.com/ai-security-tools/garak-vs-promptfoo)) | Fixed probe catalog; **oracle = "did the model emit something unsafe?"** No search loop, no dollar objective. costbomb borrows its *probe-catalog packaging idea* but swaps the oracle for spend. |
| **PyRIT** (Microsoft) | Flexible attack-chain framework — converters, scoring, multi-turn orchestration. The "Metasploit." ([ransomnews](https://ransomnews.com/red-team-llm-app-garak-pyrit-promptfoo-tutorial/)) | Its scorers grade *harm/success*, never *cost*. **Architecturally the closest cousin** — a PyRIT scorer that returned `$ spent` would be halfway to costbomb. Nobody has built that scorer. That absence *is* the white space. |
| **Promptfoo** | Eval + red-team harness, CI-friendly, many providers. ([bestaiweb](https://www.bestaiweb.ai/how-to-red-team-an-llm-with-promptfoo-pyrit-and-garak-in-2026/)) | Assertion-based (contains/latency/cost-*threshold*), but cost is a **pass/fail assertion on a fixed test**, not a **search variable being maximized**. It checks a number; costbomb *hunts* the number. |
| **MCPTox / MCP-ITP** | Benchmarks for MCP tool-poisoning across real servers. ([arXiv 2508.14925](https://arxiv.org/html/2508.14925v1)) | Attack the *server's* trust boundary. Overlaps costbomb only at `tool-storm` — but their objective is exfiltration/unsafe-action, not burning the caller's wallet. |

**Takeaway:** the security camp has the *machinery* (probes, converters, search) but always points it at a **safety oracle**. Swap the oracle to `$` and you have costbomb. That swap is non-trivial (see §4) and nobody has shipped it.

### 2.3 Camp C — Agent evaluation / regression (correctness objective)

`agentevals`, `LangWatch`, `IntellAgent`, `LiveMCP-101`, **AgentAssay** (arXiv 2603.02601). These grade **task success/quality**. AgentAssay is notable because it *worries about the token cost of testing* (efficient regression) — but as a **constraint to minimize on its own harness**, not an **attack objective to maximize on the target**. It even states the gap explicitly: *"No existing framework addresses the token economics of agent testing."* That sentence is costbomb's charter, read the other way around. ([arXiv 2603.02601](https://arxiv.org/html/2603.02601))

### 2.4 Camp D — Fuzzing search theory (the engine, no LLM cost context)

The greybox-fuzzing literature is the intellectual toolbox for the search loop:
- **Coverage-guided greybox fuzzing** (AFL): mutation-based fuzzer using a simple evolutionary algorithm; maintains a queue scored by a fitness function. ([emergentmind](https://www.emergentmind.com/topics/coverage-guided-fuzzing))
- **Power schedules / energy assignment** (AFLFast, MOpt-AFL): dynamically allocate more mutation "energy" to high-yield seeds via Markov-chain / bandit / reward schemes. ([ACM 3559550](https://dl.acm.org/doi/fullHtml/10.1145/3551349.3559550))
- **Directed & multi-objective fuzzing** (V-Fuzz, MobFuzz): steer the search toward a *specific objective* rather than blanket coverage. ([V-Fuzz arXiv 1901.01142](https://arxiv.org/pdf/1901.01142), [MobFuzz arXiv 2401.15956](https://arxiv.org/pdf/2401.15956))

**costbomb's translation:** replace "code coverage" with "**measured $ spend**" as the fitness function, keep the seed-queue + power-schedule + mutation machinery, and add an **optional LLM mutator** (which classic fuzzers lack) because agent inputs are natural language, not byte strings. This is a *directed, single-objective (spend) greybox fuzzer for a probabilistic target* — a genuinely novel point in the design space.

### 2.5 The white-space map

```
                    OBJECTIVE
              correctness/safety            dollars ($)
            ┌────────────────────────┬────────────────────────┐
  passive / │ agentevals, LangWatch, │ Helicone, Langfuse,     │
  measure   │ Promptfoo (assert)     │ LangSmith (FinOps)      │
            ├────────────────────────┼────────────────────────┤
  active /  │ garak, PyRIT, MCPTox   │  ███  costbomb  ███      │
  search    │ (red-team)             │  (EMPTY BEFORE US)      │
            └────────────────────────┴────────────────────────┘
```
The bottom-right cell is empty. That is the entire product thesis in one diagram.

---

## 3. Prior art on "denial of wallet"

The term is **not** ours to coin — it is ours to *port to agents*. Provenance matters for the launch essay (don't claim invention; claim the agentic definition).

| Source | Contribution | Relevance |
|--------|-------------|-----------|
| **Economic Denial of Sustainability (EDoS)**, ~2008–2010 | The ancestor: attacks that inflate a victim's cloud bill rather than deny availability. | costbomb's great-grandparent. Cite for lineage. |
| **"Denial of Wallet — Defining a Looming Threat to Serverless Computing"**, Kelly et al., 2021 ([arXiv 2104.08031](https://arxiv.org/pdf/2104.08031) / [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S221421262100079X)) | **Coined "Denial of Wallet"** for FaaS: exploits pay-per-use to burn money *without* degrading service — explicitly distinct from DoS. | The canonical citation. Note the key property: **DoW leaves the service up**; only the bill moves. Exactly the agent case. |
| **"A Comprehensive Review of DoW Attacks in Serverless Architectures"**, 2025 ([arXiv 2508.19284](https://arxiv.org/abs/2508.19284)) | First dedicated survey; taxonomy of techniques, financial impact, detection/mitigation. Calls the field *"infant... lack of awareness."* | Confirms the term is established **but confined to serverless**. The agent domain is untouched — our opening. |
| **ML detection of DoW** (Nature Sci. Reports 2025, ×2) ([1](https://www.nature.com/articles/s41598-025-87636-x), [2](https://www.nature.com/articles/s41598-025-01178-w)) | RNN/attention detectors for DoW *traffic* in FaaS. | All **detection** work, all serverless. None **generate** the attack, none touch agents. |
| **Sponge Examples**, Shumailov et al., 2021 (Euro S&P) | Inputs optimized to **maximize energy consumption & latency** of a neural net (defeat early-exit, inflate token count in NMT/vision). | **The true academic parent of costbomb.** costbomb generalizes sponge examples from *FLOPs/latency of one model* to *dollars across a whole agent* (tokens × price + tool calls + sub-agents). Lead the essay with this lineage — it gives the tool academic credibility. |
| **LLMEffiChecker** and NMT overhead attacks (2022–2023) | Adversarial inputs that inflate LLM inference cost/latency at the single-model level. | Confirms "maximize model cost" is a studied objective — but **only for one model call**, never for a **multi-step agent** with tools and a real invoice. costbomb is the agent-level generalization. |

**Positioning statement for the launch:** *"Denial of Wallet was defined for serverless in 2021. Sponge examples showed you can craft inputs that make a model burn energy. costbomb is what happens when you point that idea at an agent with a company card: an input that makes the whole system — model calls, tool calls, sub-agents — spend $500 to answer a $0.05 question, found automatically."*

---

## 4. Why this is technically hard (and why that's a moat, not a warning)

Naming the hard parts up front — these shape the ARCHITECTURE.

1. **The oracle is expensive to evaluate.** In classic fuzzing, running a candidate is ~free (microseconds). Here, *evaluating one candidate means actually running an agent and paying for it.* The search must be sample-efficient (few, high-yield evaluations) and the fuzzer must respect its **own** budget cap. This is why a blind random fuzzer is useless and a *directed* search + cheap surrogate estimation matters.
2. **The target is non-deterministic.** The same input yields different spend across runs (temperature, tool flakiness). Fitness must be a **distribution**, not a scalar — measure `p95 spend over k seeded runs`, not one sample. Determinism knobs (seeded, temp=0, fixed model) make findings reproducible and CI-stable.
3. **Spend has multiple additive sources.** True cost = tokens×price **+** tool-call fees **+** sub-agent spawn cost **+** (optionally) wall-clock/compute. A meter that only counts tokens misses `tool-storm` and `recursion` entirely. The meter is the crown jewel; if it's wrong, the whole search optimizes a lie.
4. **Attribution across sub-agents.** A recursion attack spawns children; their spend must roll up to the triggering input. Requires the trace format to carry parent/child spans (which stampede's trace-format already does — reuse).
5. **You must not actually cause harm while fuzzing.** Maximizing tool calls could fire real side-effects (charges, emails). costbomb must run against **mockworld** or a dry/sandbox mode by default, and integrate **exactly-once** semantics awareness so `tool-storm`/`recursion` findings note duplicate-side-effect risk.

Each of these is a reason nobody has shipped it, and a reason it's defensible once we do.

---

## 5. Users & jobs-to-be-done (expanded from SPEC §1.3)

| # | Persona | Job-to-be-done | Trigger moment | Success = |
|---|---------|----------------|----------------|-----------|
| U1 | **Agent product engineer** (has agents in prod, company card attached) | "Prove no input can make my agent spend 100× before I expose it to users." | Pre-launch hardening; after a scary invoice. | A ranked list of worst-case inputs + the $ each caused, reproducible. |
| U2 | **Platform / infra / SRE team** | "Set a defensible spend ceiling per workflow and verify it holds." | Setting org-wide agent budget policy. | A policy file (`spend_ceiling`) + proof current agent stays under it. |
| U3 | **CI / release engineer** | "Fail the build if a change makes worst-case cost regress." | Every PR. | A CI gate: `costbomb --fail-on-regression` red on a spend regression. |
| U4 | **Security / red-team** ⊕ | "Add economic attacks to our agent red-team, not just injection." | Pentest / adversarial eval engagement. | A `adversarial:economic` report alongside garak/PyRIT output. |
| U5 | **stampede user** (embedded path) | "Include economic adversaries in my swarm run." | Running stampede pre-prod. | The Agent Readiness Report's cost-profile section, powered by costbomb. |
| U6 | **FinOps / eng manager** ⊕ | "Quantify our tail-risk exposure in dollars for the risk register." | Budgeting / board reporting. | A worst-case $ number per agent, tracked over time. |
| U7 | **Framework maintainer** ⊕ | "Regression-test our orchestrator against economic pathologies." | Framework release. | costbomb in the framework's own CI; recursion/loop guards proven. |
| U8 | **Incident responder** (agent-postmortems tie-in) ⊕ | "Reproduce last month's cost-blowup incident as a repeatable test." | Post-incident. | A postmortem `cost-blowup` incident replayed as a costbomb seed. |

---

## 6. Comprehensive use-case catalog

Grouped by attack class, with the *mechanism* and a *concrete example*. This is the raw material for the attack library (PRD §, ARCHITECTURE §). ⊕ marks classes/uses beyond the SPEC's original five.

### 6.1 The five SPEC attack classes
| Class | Mechanism (what balloons the meter) | Concrete example input |
|-------|-------------------------------------|------------------------|
| **retry-loop** | Provoke endless retry/repair cycles — each retry is a full priced call. | A request whose success criterion is unsatisfiable ("return a JSON that validates against this contradictory schema"), so the agent repairs → retries → repairs forever. Real analog: the $47k Analyzer/Verifier ping-pong. |
| **tool-storm** | Goal that provokes excessive/expensive tool calls. | "Cross-check this claim against *every* source you can find" → hundreds of search/tool invocations, each billed. |
| **context-bomb** | Input that balloons the context window every turn (context accumulation is *the* documented driver — [getunblocked](https://getunblocked.com/blog/why-ai-agents-burn-tokens/)). | Paste a large doc + "keep the full text in mind and re-summarize after each step," so every step re-sends a growing context; step-30 inputs hit 80k+ tokens. |
| **recursion** | Prompt that spawns runaway sub-agents. | "Break this into subtasks and spawn a specialist agent for each; have each do the same" → exponential fan-out. Real analog: Claude Code 1.67B-token recursion. |
| **clarification-trap** | Ambiguity that traps the agent in endless clarifying turns. | A goal engineered to be *just* ambiguous enough that the agent asks, you (a scripted user-sim) answer vaguely, it asks again — infinite billed turns. |

### 6.2 Attack classes beyond the SPEC ⊕
| Class ⊕ | Mechanism | Why add it |
|---------|-----------|------------|
| **reasoning-inflation** ⊕ | Trigger max extended-thinking / chain-of-thought budget on a trivial question. | 2026 reasoning models bill thinking tokens; "think very carefully, step by step, exhaustively" is a cheap way to 10× a request. Not covered by the five. |
| **model-escalation** ⊕ | Manipulate a router/orchestrator into routing to the most expensive model. | Many agents route by "difficulty"; feign difficulty → get Opus-tier pricing for a trivial task. Pure dollar attack, invisible to token-count-only meters. |
| **cache-bust** ⊕ | Defeat prompt-caching so every call pays full input price. | Vary a prefix byte each turn → cache miss every time → input cost 10×. Directly attacks the main 2026 cost-savings mechanism. |
| **tool-cost-asymmetry** ⊕ | Steer toward the *priced* tool when a free one suffices. | If one tool calls a paid API (e.g., a $/call search), craft goals that force it repeatedly. Requires per-tool pricing in the meter. |
| **retrieval-amplification** ⊕ | Force large-`k` / recursive RAG fetches. | "Retrieve the top 500 chunks and read them all" → huge input tokens per step. Sub-case of context-bomb but worth a named seed. |

### 6.3 Cross-cutting uses (product surfaces, not attack classes)
- **U-a Baseline + regression:** record worst-case $ as a committed baseline; CI fails on regression (the north-star use).
- **U-b Budget discovery:** run to convergence, report the empirical worst case → informs the runtime enforcement ceiling (feeds Waxell/TrueFoundry-style enforcers).
- **U-c Incident replay:** import an agent-postmortems `cost-blowup` incident as a seed; prove your fix holds. ⊕
- **U-d exactly-once cross-check:** flag `tool-storm`/`recursion` findings where the storming tool has side-effects → duplicate-charge risk, not just spend. ⊕
- **U-e Provider what-if:** re-price a recorded run against a different provider's table ("what would this cost on GPT vs Claude?"). ⊕

---

## 7. Gap analysis

### 7.1 Gaps in the *field* (market gaps costbomb fills)
1. **No adversarial search with a dollar objective** — the empty cell in §2.5. (Primary.)
2. **No pre-production DoW discovery for agents** — all DoW work is serverless + detection, not agentic + generation.
3. **No spend-regression CI gate** — Promptfoo asserts a cost *threshold* on fixed tests; nobody gates on *worst-case-found-by-search* vs a baseline.
4. **No true multi-source cost meter as a standalone** — observability tools meter inside their own proxy; there's no portable meter you point at *any* agent (HTTP/Python/persona) that sums tokens+tools+sub-agents.
5. **No named category** — "denial-of-wallet fuzzing" as a product category does not exist. First-mover on the name.

### 7.2 Gaps in the *SPEC* (things the spec under-specifies — I'll resolve these in PRD/ARCHITECTURE)
| # | Spec gap | Resolution direction |
|---|----------|---------------------|
| G1 | Meter counts "tokens × price" but the spec's own attacks (`tool-storm`, `recursion`) need **per-tool** and **per-spawn** pricing. | Meter must be a **sum over cost sources**, not just tokens. Price table gains `tool_prices` + spawn accounting. (ARCH §cost-meter) |
| G2 | Non-determinism unaddressed — spec says "search toward max spend" as if spend were a scalar. | Fitness = **p95 over k runs**; seedable; determinism knobs. (PRD NFR + ARCH) |
| G3 | "LLM-assisted mutation" mentioned but its **own** cost isn't in the budget math. | Mutator spend counts against the fuzzer's global cap; default to cheap/local model; template mutators need no LLM. (ARCH) |
| G4 | Embedded-vs-standalone "shared core" asserted but boundary undefined. | Define `costbomb-core` (meter + attacks + engine, no I/O) vs two entrypoints (stampede cohort adapter / standalone CLI). (ARCH §boundary) |
| G5 | No **stopping criterion** for the search. | Stop on: budget exhausted, plateau (no improvement in N generations), or wall-clock. (ARCH §engine) |
| G6 | Safety of *running* attacks (real side-effects) only lightly noted. | Default target = mockworld/dry-run; require `--allow-side-effects` to hit anything real; surface exactly-once risk. (PRD NFR) |
| G7 | Missing attack classes (§6.2) — reasoning-inflation, model-escalation, cache-bust are 2026-specific and high-yield. | Add as first-class seeds. ⊕ |
| G8 | No **custom attack authoring** interface until v0.3, but the seed-strategy interface should exist from v0.1 so classes are pluggable. | Ship the `AttackClass` plugin interface in core from day one; "authoring" in v0.3 is just docs + external loading. |
| G9 | Price table staleness (models/prices change weekly). | Vendor LiteLLM/Helicone JSON, pin+refresh, allow `--price-table` override. (ARCH) |

---

## 8. Differentiation (the one-liner per competitor)

- **vs Helicone/Langfuse:** they show you the bill; costbomb writes the input that runs the bill up. (Measure vs attack.)
- **vs garak/PyRIT:** same search machinery, different oracle — dollars, not policy violations. A PyRIT scorer that returned `$` would *be* costbomb; nobody built it.
- **vs Promptfoo:** it asserts a cost *threshold on a fixed test*; costbomb *searches for* the worst input and gates on regression vs baseline.
- **vs runtime enforcers (Waxell/TrueFoundry):** they're the seatbelt (stop spend at runtime); costbomb is the crash test (find what would trigger it, pre-prod) and *hands them the ceiling*.
- **vs AgentAssay/agentevals:** they grade correctness (and minimize *their own* test cost); costbomb maximizes the *target's* cost as the objective.
- **vs serverless DoW research:** they detect DoW traffic in FaaS; costbomb generates DoW inputs for agents. Different layer, borrowed name.

---

## 9. Open questions (to resolve during build)

1. **Surrogate cost model?** Can we estimate a candidate's spend from its trace *shape* without a full paid run, to make the search cheaper? (Cheap heuristic estimator → only confirm top candidates with real runs.)
2. **How adversarial-realistic must seeds be?** Some attacks (recursion via "spawn sub-agents") assume the agent *can* spawn — do we detect capability first, or blindly try all classes and report which landed?
3. **LLM mutator provider default** — local Ollama (free, weaker mutations) vs cheap hosted (better, costs money against the cap)? Likely: template mutators default, LLM mutator opt-in.
4. **Baseline storage format** for the CI gate — commit a `.costbomb-baseline.json`? How to diff across price-table changes (spend went up because *prices* rose, not because the *agent* regressed → must separate).
5. **Determinism ceiling** — even at temp=0, tool flakiness and provider drift add variance. What `k` and what p-quantile give a stable-enough gate? (Empirical; TEST-PLAN covers.)
6. **Where does the meter physically attach?** Wrap the provider SDK client (most accurate), parse provider usage fields, or sit as a proxy? Probably a pluggable `CostMeter` with a wrapper as default and proxy as an adapter.
7. **Category ownership** — do we register/define "denial-of-wallet" in awesome-agent-reliability and agent-postmortems taxonomy (`cost-blowup`) so the term propagates? (Portfolio play — yes.)

---

## 10. Sources

Cost observability / enforcement:
- Helicone cost tracking — https://docs.helicone.ai/guides/cookbooks/cost-tracking
- Langfuse token & cost tracking — https://langfuse.com/docs/observability/features/token-and-cost-tracking
- Helicone vs Langfuse vs LangSmith (2026) — https://particula.tech/blog/helicone-vs-langfuse-vs-langsmith-llm-observability
- LLM cost optimization tools (nOps, 2026) — https://www.nops.io/blog/llm-cost-optimization-tools/
- AI agent token budget enforcement (Waxell) — https://waxell.ai/blog/ai-agent-token-budget-enforcement
- Rate limiting AI agents (TrueFoundry) — https://www.truefoundry.com/blog/rate-limiting-ai-agents-preventing-llm-api-exhaustion

Incidents:
- The $47,000 agent loop (Waxell) — https://dev.to/waxell/the-47000-agent-loop-why-token-budget-alerts-arent-budget-enforcement-389i
- The auto-loop tax / Claude Code recursion (getunblocked) — https://getunblocked.com/blog/agent-auto-loop-token-cost/
- Why AI agents burn tokens (getunblocked) — https://getunblocked.com/blog/why-ai-agents-burn-tokens/
- AI agents don't crash, they spend (sanj.dev) — https://sanj.dev/post/llm-cost-control

Security red-teaming / fuzzing:
- Garak vs Promptfoo (2026) — https://appsecsanta.com/ai-security-tools/garak-vs-promptfoo
- Red-team LLM apps: garak, PyRIT, Promptfoo — https://ransomnews.com/red-team-llm-app-garak-pyrit-promptfoo-tutorial/
- Best AI red-teaming tools 2026 — https://netguardia.com/security-operations/software-tools/the-best-ai-red-teaming-tools-of-2026-from-garak-to-promptfoo/
- What is AI fuzzing (witness.ai) — https://witness.ai/blog/ai-fuzzing/
- Agentic chaos engineering / AI fuzzing (2026) — https://www.buildmvpfast.com/blog/agentic-chaos-engineering-ai-fuzzing-bug-hunting-security-2026
- MCPTox benchmark — https://arxiv.org/html/2508.14925v1
- MCP Tool Poisoning (OWASP) — https://owasp.org/www-community/attacks/MCP_Tool_Poisoning

Eval / cost-aware testing:
- AgentAssay (token-efficient regression) — https://arxiv.org/html/2603.02601
- Hallucination costs millions (adversarial financial benchmark) — https://arxiv.org/html/2510.00332v1

Fuzzing search theory:
- Coverage-guided greybox fuzzing — https://www.emergentmind.com/topics/coverage-guided-greybox-fuzzing
- Power-schedule optimization — https://dl.acm.org/doi/fullHtml/10.1145/3551349.3559550
- V-Fuzz (vulnerability-oriented evolutionary) — https://arxiv.org/pdf/1901.01142
- MobFuzz (multi-objective) — https://arxiv.org/pdf/2401.15956

Denial-of-Wallet prior art:
- DoW — defining a looming threat to serverless (2021) — https://arxiv.org/pdf/2104.08031
- Comprehensive review of DoW attacks (2025) — https://arxiv.org/abs/2508.19284
- ML detection of DoW (Nature Sci. Reports) — https://www.nature.com/articles/s41598-025-87636-x

Price tables:
- LiteLLM model_prices_and_context_window.json — https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json
- LiteLLM token usage / cost_per_token — https://docs.litellm.ai/docs/completion/token_usage
- tokencost (AgentOps, 400+ LLMs) — https://github.com/AgentOps-AI/tokencost
- tokencost.dev — https://tokencost.dev/

*Sponge Examples (Shumailov et al., 2021) and LLMEffiChecker cited from domain knowledge as the academic lineage for cost/energy-maximizing adversarial inputs.*
