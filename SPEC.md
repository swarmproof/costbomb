# costbomb — Design Specification & PRD
### Denial-of-wallet fuzzing for agent systems
*The sharp single-purpose tool · v1.0 spec*

> **costbomb** — find the inputs that make your agent spend $500 to answer a $0.05 question. A fuzzer for economic failure: it hunts for the prompts, tool-call loops, and context explosions that blow up your bill, and gates CI on spend regressions.

---

## 1. PRD

### 1.1 Problem

Agent systems have a failure mode traditional software doesn't: **they can be made to spend unbounded money.** A crafted input can send an agent into a retry loop, a runaway tool-call chain, a context-window explosion, or a recursive sub-agent spawn — each burning tokens and API dollars. This "denial-of-wallet" class is real, under-tooled, and terrifying for anyone running agents in production with a company card attached. Nobody fuzzes *for cost*. Security fuzzers hunt crashes; costbomb hunts spend.

### 1.2 Why it wins

- **Perfect name-in-a-sentence.** "We denial-of-wallet fuzzed our agent" explains itself and spreads. Small tools with perfect names travel far.
- **Universal fear, zero tooling.** Everyone with agents in prod worries about runaway spend; there's no dedicated tool.
- **Trust-brand + finance fit** — economic security is literally money-safety.
- **Portfolio synergy:** ships first *inside* stampede's adversarial cohort, then extracts as a standalone CLI — two launches, one codebase.

### 1.3 Users & JTBD

1. **Teams running agents in production** — "Prove my agent can't be tricked into a $500 request before I expose it."
2. **CI pipelines** — "Fail the build if a change makes worst-case cost regress."
3. **Platform/infra teams** — "Set and verify spend ceilings per agent workflow."

### 1.4 Goals & non-goals

**Goals (v0.1):** given an agent endpoint/harness, generate adversarial inputs aimed at maximizing spend across known cost-explosion classes; report the worst offenders with reproduction; CI mode that gates on a spend-regression budget.

**Non-goals:** general prompt-injection/security fuzzing (adjacent, not the focus); optimizing normal-case cost (that's an observability tool's job); being an agent framework.

### 1.5 Success metrics

- North star: repos gating CI on a costbomb budget.
- The concept "denial-of-wallet" entering common usage with costbomb as its reference tool.

---

## 2. ARCHITECTURE

### 2.1 Shape

```
target agent ◀──── costbomb ────▶ cost meter (tokens × price = $)
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
   attack library  fuzz engine    reporter
   (loop, recurse, (mutate +      (worst cases,
   context-bomb,   search toward  repro, CI gate)
   tool-storm)     max spend)
```

### 2.2 Components

**A. Cost meter** — instruments the target to measure true $ per run: tokens in/out × model price, tool-call counts, wall-clock, sub-agent spawns. Provider-agnostic price table (updatable). The ground truth everything optimizes against.

**B. Attack library** — named cost-explosion classes, each a seed strategy:
- `retry-loop`: inputs that trigger endless retry/repair cycles.
- `tool-storm`: goals that provoke excessive tool calls.
- `context-bomb`: inputs that balloon the context window each turn.
- `recursion`: prompts that spawn runaway sub-agents.
- `clarification-trap`: ambiguity that traps the agent in endless clarifying turns.

**C. Fuzz engine** — mutates seed inputs and uses a search loop (evolutionary / hill-climbing) to *maximize measured spend*, keeping the highest-cost inputs. Optionally LLM-assisted mutation ("make this input more likely to cause a retry loop").

**D. Reporter** — ranks worst offenders with exact reproduction, the $ each caused, and which class triggered; **CI gate**: `costbomb --budget 0.50 --fail-on-regression` fails the build if worst-case cost exceeds budget or regresses vs baseline. Shared oxblood report renderer.

### 2.3 Tech stack

Python 3.11+; provider-agnostic model layer + price table; reuses stampede's agent-driver and trace primitives; search loop in pure Python (no heavy deps). Runs against any callable agent (HTTP endpoint, Python harness, or a stampede persona).

### 2.4 Risks & mitigations

- **Running the fuzzer itself costs money** → strict global budget cap on the fuzzing run; cheap/local models for mutation; dry-run estimation mode.
- **Overlap with stampede's adversarial persona** → intentional; costbomb *is* that logic, extracted and specialized with the search loop + CI gate. Ship inside stampede first, extract when the standalone story is clear.

---

## 3. ROADMAP

- **v0.1 (inside stampede):** attack library + cost meter as stampede's `adversarial:economic` cohort.
- **v0.2 (standalone extract):** CLI, fuzz search engine, CI gate, five attack classes, repro reports. "Show HN: costbomb – denial-of-wallet fuzzing for AI agents."
- **v0.3:** custom attack authoring; spend-ceiling policy enforcement; integration with exactly-once (loops that also cause duplicate side-effects).

## 4. LAUNCH

The essay writes itself: "Denial-of-Wallet: The Agent Attack Nobody's Testing For." Live demo: a benign-looking input that runs an agent's bill from 5 cents to 5 dollars, then costbomb finding it automatically. Trust Layer issue on economic security of agents.
