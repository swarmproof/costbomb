# Changelog

All notable changes to costbomb are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versions follow SemVer.

## [0.2.0] — 2026-09-07

First public release — the standalone extract of denial-of-wallet fuzzing.

### Added
- **Cost meter (the oracle)** — sum over sources: model tokens (input/output/reasoning/
  cache) + tool-call fees + recursive sub-agent spawn cost. Provider-agnostic price table.
- **Attack library** — 10 cost-explosion classes: `retry-loop`, `tool-storm`,
  `context-bomb`, `recursion`, `clarification-trap`, `reasoning-inflation`,
  `model-escalation`, `cache-bust`, `tool-cost-asymmetry`, `retrieval-amplification`,
  each with honest capability gating.
- **Fuzz engine** — evolutionary search, power schedule, p95-over-k fitness, surrogate
  pre-ranking, and a hard own-budget cap (never runs away).
- **CI gate** — baseline + regression detection with price-drift separation.
- **Targets** — Fake / Python / HTTP / Mockworld / Persona, behind one `Target` seam.
- **Proxy meter** — zero-instrumentation metering of a real agent via a base_url swap.
- **Richer cost model** — downstream tool-cost / blast radius, wall-clock / infra cost,
  and a duplicate-effect (exactly-once) cross-check backed by the real `exactly_once`
  library.
- **Validation** — per-biller reconciliation (`costbomb.validation`) + full-agent LLM
  and Stripe test-mode harnesses; report labels modeled vs invoice-backed slices.
- **CLI** — `costbomb run` / `baseline` / `proxy` / `attacks` / `price`, with
  `findings.json` + OTel GenAI-profile export.

### Known limitations
- The meter's ≤1% accuracy (NFR-8) is **not yet validated against real invoices**
  (`0/20` invoice-grounded fixtures) — see `docs/VALIDATION.md`. Treat as a
  well-engineered tool whose oracle is arithmetic-checked but not bill-proven.

[0.2.0]: https://github.com/swarmproof/costbomb/releases/tag/v0.2.0
