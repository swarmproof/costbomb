# Meter-accuracy fixtures (TEST-PLAN §6 — the oracle's corpus)

Each fixture is one recorded agent run plus the **independently-known** dollar cost
of that run. `tests/test_meter_accuracy.py` asserts costbomb's meter reproduces that
cost within tolerance (NFR-8, ≤1%). Because the meter is the oracle, this corpus is
what makes the whole tool trustworthy — if the meter is wrong, the search optimizes a
lie.

## The real/synthetic distinction (read this before trusting a green run)

Every fixture declares a `source`:

- **`real`** — the run actually happened against a provider, and `expected_usd` is the
  **provider's own reported cost** (from the API `usage` + the provider's billing, or
  a real invoice line). Only `real` fixtures prove the ≤1% claim in NFR-8.
- **`synthetic`** — hand-authored. `expected_usd` was computed **independently** (by
  hand, from published per-token prices) — *not* by running costbomb's meter. These
  catch meter **arithmetic** bugs (dropped token class, double-counted spawn, wrong
  tool fee) but they do **not** prove real-invoice accuracy: a systematic modelling
  error shared by the hand calc and the meter would pass.

`test_ma1_real_invoice_corpus` **skips with a loud message** until at least
`REQUIRED_REAL` (20) real fixtures exist. A green synthetic-only run therefore means
"the arithmetic is right", **not** "validated against real bills". Do not describe the
meter as validated until that skip turns into a pass.

## Fixture format

```json
{
  "name": "opus-single-call-plus-tool",
  "source": "synthetic",
  "provider": "anthropic",
  "price_table_version": "2026-07-13",
  "expected_usd": 0.0245,
  "expected_breakdown": { "model_usd": 0.0045, "tool_usd": 0.02, "spawn_usd": 0.0 },
  "provenance": "hand-computed from the vendored 2026-07-13 table; NOT a real invoice",
  "run": {
    "calls": [
      { "model": "anthropic:claude-opus-4-8", "input_tokens": 1000, "output_tokens": 100 }
    ],
    "tool_calls": ["premium_api"],
    "spawns": []
  }
}
```

`run` is a `costbomb.targets.RunRecord` shape (calls / tool_calls / recursive spawns).
`price_table_version` must match the table the fixture was priced against; a table
refresh that changes a fixture's cost will fail the test (MA-5 golden guard) rather
than silently shift the oracle.

## Adding a real fixture

1. Run a real agent once, capturing every model call's `usage` and each tool call.
2. Record the provider's own reported cost for that run as `expected_usd`.
3. Set `source: "real"` and cite the provenance (dashboard/invoice/date).
4. Drop it here. When ≥20 real fixtures across providers exist and pass at ≤1%, the
   meter is validated (AC-1) and the readiness skip flips to a pass.
