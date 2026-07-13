# costbomb

### Denial-of-wallet fuzzing for agent systems

> Find the inputs that make your agent spend $500 to answer a $0.05 question. A fuzzer for economic failure: it hunts the prompts, tool-call loops, and context explosions that blow up your bill, and gates CI on spend regressions.

<!-- TODO: demo GIF — a benign input running an agent's bill from 5¢ to $5, then costbomb finding it -->
<p align="center"><em>▶ demo GIF coming — costbomb automatically finding the input that runs the bill from 5¢ to $5</em></p>

> **Status:** 🚧 Ships first *inside* [stampede](https://github.com/swarmproof/stampede)'s adversarial cohort, then extracts here as a standalone CLI.

---

## Why

Agent systems have a failure mode traditional software doesn't: **they can be made to spend unbounded money.** A crafted input sends an agent into a retry loop, a runaway tool-call chain, a context-window explosion, or a recursive sub-agent spawn — each burning tokens and dollars. This "denial-of-wallet" class is real, under-tooled, and terrifying for anyone running agents in production with a company card attached. Security fuzzers hunt crashes; **costbomb hunts spend.**

## Quickstart

```bash
pip install costbomb
costbomb run --target http://localhost:9000/agent --budget 0.50
costbomb run --target ./agent.py --fail-on-regression   # CI gate on worst-case cost
```

## The attack library

Named cost-explosion classes, each a seed strategy the fuzz engine mutates toward maximum spend: `retry-loop` · `tool-storm` · `context-bomb` · `recursion` · `clarification-trap`. The reporter ranks the worst offenders with exact reproduction, the $ each caused, and which class triggered — then the **CI gate** fails the build if worst-case cost regresses.

See [`SPEC.md`](./SPEC.md) and [`ROADMAP.md`](./ROADMAP.md).

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
