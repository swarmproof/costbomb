# costbomb — DELIVERY PLAN

*Milestones, WBS, sequencing, and the two-launches-one-codebase plan. Companion to [`ARCHITECTURE.md`](./ARCHITECTURE.md) and the portfolio roadmap.*
*Effort in ideal engineering-days (IED), sized for one senior engineer working alongside Xerberus (evenings/weekends cadence). `⊕` = beyond original SPEC.*

---

## 1. The strategy: two launches from one codebase

costbomb is deliberately sequenced to get **two distinct launch moments** out of a single implementation — the portfolio's highest-leverage move:

1. **Launch 1 (silent / embedded):** costbomb ships *inside* stampede as the `adversarial:economic` cohort. No separate announcement — it appears as a section of stampede's Agent Readiness Report ("the cost profile, now adversarial"). This **proves the engine on a real host** and de-risks it before it stands alone.
2. **Launch 2 (loud / standalone):** the same `costbomb-core` is extracted behind a CLI + CI gate and launched on its own — *"Show HN: costbomb — denial-of-wallet fuzzing for AI agents"* + the essay. This is where the category name lands.

The `Target` Protocol seam (ARCHITECTURE §6) is what makes this a *packaging* move rather than a rewrite. **Do not** build the CLI first; build the core inside stampede, prove it, then wrap it.

```
stampede build ──────────────────────────────▶ stampede v0.1 launch
        │                                              │
        │ costbomb-core grows in-tree                  │
        ▼                                              ▼
   v0.1 costbomb (embedded)  ───extract───▶  v0.2 costbomb (standalone CLI + CI gate)  ──▶  v0.3 (policy/ecosystem)
   Launch 1 (rides stampede)                 Launch 2 (Show HN + essay)
```

---

## 2. Milestones & definition-of-done

### M0 — Foundations (can start before stampede is done)
The parts with **no dependency on stampede** — build them first so v0.1 is fast once stampede's driver exists.
- Cost meter + price table + cost model (`REQ-CM-1..6`).
- `AttackClass` interface + the 5 SPEC classes (template mutation) (`REQ-AL-1/3/4`).
- Findings data model.
- **DoD:** meter passes accuracy tests (NFR-8, ≤1%) against recorded fixtures; 5 classes produce seeds; all unit-tested; no stampede import yet (targets stubbed with a `FakeTarget`).

### M1 — costbomb v0.1 (embedded in stampede) — *Launch 1*
- `PersonaTarget` wiring core to stampede's agent-driver (`REQ-TA-3`).
- Cost flows into stampede's Agent Readiness Report cost-profile section (`REQ-RP-2`).
- Own-budget cap (NFR-1); seedable (NFR-2).
- **DoD:** running stampede with `mix: { adversarial: 0.05 }` produces an economic-findings section with ≥1 real amplification finding + repro, staying under the run's `budget_usd`. Demoed on Cairn or the stampede demo target.

### M2 — costbomb v0.2 (standalone extract + CLI + CI gate) — *Launch 2*
- Extract `costbomb-core` to this repo; stampede depends on it as a package.
- Full **fuzz engine**: evolutionary loop + power schedule + p95 fitness + stopping criteria + surrogate pre-ranking (`REQ-FE-1/2/3/5/7`).
- **LLM-assisted mutator** (optional, cheap/local default) (`REQ-FE-4`).
- Standalone **CLI** + `HTTPTarget`/`PythonTarget`/`MockworldTarget` (`REQ-TA-1/2/4`).
- **CI gate** + baseline + price-drift separation + dry-run smoke (`REQ-CI-1..6`).
- ⊕ 5 extra attack classes (`REQ-AL-2`).
- `findings.json` + OTel export (`REQ-RP-5`).
- **DoD:** `pip install costbomb`; the 5¢→$5 demo agent is cracked automatically under the default cap; CI gate goes red on an injected regression and green after revert, without failing on a simulated price hike; determinism test passes; docs + Show HN assets ready.

### M3 — costbomb v0.3 (policy + ecosystem)
- Custom attack authoring UX + external loading (`REQ-AL-4` UX).
- Spend-ceiling policy + enforcer-config emit (`REQ-SP-1/2`).
- exactly-once duplicate-effect cross-check (`REQ-RP-4`).
- agent-postmortems incident-as-seed (`REQ-AL-6`); provider what-if re-pricing (`REQ-CM-8`).
- **DoD:** a postmortem `cost-blowup` incident replays as a seed and reproduces; a `spend_ceiling` policy gates a workflow; a community-authored attack class loads without forking.

---

## 3. Work breakdown structure (WBS)

| ID | Work item | Milestone | Effort (IED) | Depends on |
|----|-----------|-----------|-------------|------------|
| W1 | Price table: vendor LiteLLM/tokencost JSON, extend with tool/reasoning/cache fields, refresh script | M0 | 1.0 | — |
| W2 | CostMeter: sum-over-sources model, breakdown, attribution | M0 | 2.5 | W1, trace-format |
| W3 | Meter attachment: SDK-wrapper + usage-parse modes | M0 | 1.5 | W2 |
| W4 | `AttackClass` interface + registry + `signal()` | M0 | 1.0 | — |
| W5 | 5 SPEC attack classes (seeds + template mutate + applicable) | M0 | 3.0 | W4 |
| W6 | Findings data model + `FakeTarget` for tests | M0 | 1.0 | — |
| W7 | Dry-run estimator (surrogate) | M0/M2 | 2.0 | W2 |
| W8 | `PersonaTarget` → stampede agent-driver | M1 | 1.5 | W2, stampede driver |
| W9 | Cost-profile section in stampede report | M1 | 1.0 | W8, report-renderer |
| W10 | Own-budget cap + seeding plumbing | M1 | 1.0 | W2 |
| W11 | FuzzEngine: seed queue + evolutionary loop | M2 | 3.0 | W5, W6 |
| W12 | Power schedule (AFLFast-style energy) | M2 | 1.5 | W11 |
| W13 | p95-over-k fitness + variance handling | M2 | 1.5 | W11 |
| W14 | Stopping criteria (budget/plateau/wallclock) | M2 | 0.5 | W11 |
| W15 | LLM-assisted mutator (Ollama/cheap default) | M2 | 2.0 | W5 |
| W16 | Core extraction → `costbomb-core` package; stampede depends on it | M2 | 2.0 | W1–W10 |
| W17 | CLI (argparse/click) + target factory | M2 | 1.5 | W16 |
| W18 | `HTTPTarget` + `PythonTarget` | M2 | 2.0 | W17 |
| W19 | `MockworldTarget` (safe default) ⊕ | M2 | 1.5 | W17, mockworld |
| W20 | CI gate: baseline I/O + regression logic + price-drift separation | M2 | 2.5 | W16 |
| W21 | Dry-run CI smoke mode | M2 | 1.0 | W7, W20 |
| W22 | 5 extra attack classes ⊕ | M2 | 3.0 | W4, W5 |
| W23 | findings.json + OTel export | M2 | 1.0 | W6 |
| W24 | oxblood standalone report file | M2 | 1.0 | W6, report-renderer |
| W25 | Custom attack authoring docs + external loading | M3 | 1.5 | W4 |
| W26 | Spend-ceiling policy + enforcer-config emit ⊕ | M3 | 2.0 | W20 |
| W27 | exactly-once duplicate-effect cross-check ⊕ | M3 | 1.5 | exactly-once |
| W28 | postmortem incident-as-seed ⊕ | M3 | 1.0 | agent-postmortems schema |
| W29 | Provider what-if re-pricing ⊕ | M3 | 0.5 | W1 |
| W30 | Docs, README demo GIF, essay, Show HN assets | M2 | 2.0 | M2 features |

**Rough totals:** M0 ≈ 12 IED · M1 ≈ 3.5 IED · M2 ≈ 24 IED · M3 ≈ 6.5 IED. Standalone (M0+M1+M2) ≈ **40 IED** — consistent with the portfolio's "S–M" sizing given heavy primitive reuse from stampede.

---

## 4. Sequencing & dependencies on stampede

costbomb is gated by stampede in exactly two places; everything else is independent.

```
stampede primitives needed:   agent-driver ──▶ W8 (PersonaTarget)   [M1 blocker]
                              trace-format ──▶ W2 (meter attribution) [M0 — but format is published early in stampede]
                            report-renderer ──▶ W9, W24               [M1/M2]
                              persona-pack ──▶ adversarial persona     [M1]

Critical path to Launch 2:
  W1→W2→W3 ─┐
  W4→W5 ────┼─▶ W11→W12/W13/W14 ─▶ W16 ─▶ W17→W18/W19 ─▶ W20→W21 ─▶ W30 ─▶ Launch 2
  W6 ───────┘        (W7 feeds W11)
```

**Key insight:** M0 (12 IED — the meter + attacks + estimator) has **zero hard dependency on stampede** (uses `FakeTarget` + recorded fixtures). Build it in parallel while stampede's driver matures. Only M1's `PersonaTarget` truly blocks on stampede. This means costbomb can be ~60% built before stampede v0.1 ships — matching the portfolio timeline (costbomb embedded ~Wk 6–13, extract ~Wk 14).

**Portfolio timing (from PORTFOLIO-ROADMAP):**
- Wk 6–13: build M0 + M1 alongside stampede → Launch 1 rides stampede v0.1.
- ~Wk 14: M2 extract → Launch 2 (standalone Show HN).
- Post-launch: M3 as ecosystem siblings (mockworld, exactly-once, postmortems) mature.

---

## 5. Definition-of-done checklist (per milestone gate)

Every milestone must pass before the next starts:
- [ ] All REQ-IDs for the tier implemented and traceable to a test (TEST-PLAN).
- [ ] Meter accuracy ≤1% on the tier's fixtures (NFR-8).
- [ ] Own-budget cap provably holds (NFR-1) — a chaos test that tries to overspend is stopped.
- [ ] Determinism: same seed → same trajectory (NFR-2).
- [ ] No provider hardcoded outside the price table (NFR-3).
- [ ] Runs with no LLM available (template + dry-run) (NFR-10).
- [ ] Portfolio standards: Apache-2.0, CITATION.cff, README demo, sibling links.

---

## 6. Launch checklist (Launch 2 — standalone)

**Essay:** *"Denial-of-Wallet: The Agent Attack Nobody's Testing For."* Structure: the $47k loop story → the sponge-examples lineage → the empty white-space cell (RESEARCH §2.5) → the 5¢→$5 live demo → "gate it in CI."
- [ ] Essay drafted, ties to a Trust Layer issue on economic security of agents.
- [ ] **Demo GIF** (README above-the-fold): a benign input runs a demo agent 5¢→$5, then costbomb finds it automatically under its own cap. < 90 seconds.
- [ ] `pip install costbomb` works clean; quickstart ≤ 10 lines.
- [ ] CI gate GitHub Action snippet copy-pasteable; a public demo repo shows it going red/green.
- [ ] `findings.json` + OTel export demoed importing into Langfuse (interop proof).
- [ ] "denial-of-wallet" registered in awesome-agent-reliability + agent-postmortems `cost-blowup` taxonomy (category-ownership play).
- [ ] Show HN post; r/LocalLLaMA + r/mcp; TLDR AI / Latent Space submissions.
- [ ] Cross-links live: stampede README points to the extracted CLI; costbomb README points home.
- [ ] 3–5 seeded `good-first-issue`s (e.g., "add a `cache-bust` variant", "port price table refresh to a GH Action").

---

## 7. Risks to the plan & mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| stampede slips → M1 blocked | Launch 1 delayed | M0 is stampede-independent (FakeTarget); build it fully first, so only the thin `PersonaTarget` waits. |
| Search too costly to be useful under $2 cap | Core value prop fails | Surrogate estimator (W7) pre-ranks; only top-K get paid runs. Prototype this **early** in M0, not M2. |
| Non-determinism makes CI gate flap | Adoption killer | p95-over-k (W13) + determinism tests; document recommended `k`. |
| Price table staleness | Wrong meter | Refresh script (W1) + `--price-table` override + price-drift-separated gate (W20). |
| Extraction reveals hidden stampede coupling | M2 rewrite | `Target` Protocol enforced from M0; a `FakeTarget`-only test suite proves core has no stampede import. |
| Meter can't attach to a target | Some targets unusable | Layered modes (SDK-wrap → usage-parse → proxy → wire-estimate); document accuracy per mode. |
