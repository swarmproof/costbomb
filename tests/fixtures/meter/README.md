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

## Why price-derived ≠ invoice (the circularity trap)

A `real` fixture's `expected_usd` must be **independent of costbomb's price table**, or
MA-1 proves nothing. There are two ways to know a real run's cost, and only one is a
true oracle:

- **`invoice`** — the amount the provider actually **billed** (billing dashboard /
  invoice line). Independent of our table → the real proof of NFR-8.
- **`usage_x_published_price`** — cost recomputed from the run's token `usage` × the
  provider's *published* per-token prices. Since our table encodes those same prices,
  MA-1 against this is **partly circular**: it still catches *missed cost sources*
  (an un-metered tool, a dropped sub-agent, an ignored cache/reasoning class) and
  *wrong token counts*, but it can **not** catch a pricing error shared with the
  published sheet. Weaker evidence — track it separately.

So every `real` fixture declares `expected_usd_source`. The suite counts
invoice-grounded fixtures separately; treat the meter as fully validated (AC-1) only
when enough **`invoice`**-grounded reals pass.

## Fixture format

```json
{
  "name": "opus-single-call-plus-tool",
  "source": "synthetic",
  "expected_usd_source": "hand_computed",
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

`expected_usd_source` ∈ `invoice` | `usage_x_published_price` | `hand_computed`
(synthetic). `source` ∈ `real` | `synthetic`.

`run` is a `costbomb.targets.RunRecord` shape (calls / tool_calls / recursive spawns).
`price_table_version` must match the table the fixture was priced against; a table
refresh that changes a fixture's cost will fail the test (MA-5 golden guard) rather
than silently shift the oracle.

## Capture recipe (recording a real fixture)

1. **Run the agent once**, capturing per model call: `gen_ai.request.model`, the
   provider, and every usage field the API returns — `input_tokens`, `output_tokens`,
   and (where present) reasoning/thinking, cache-read, cache-write tokens. Capture each
   tool call by name and each spawned sub-agent's calls (recursively).
2. **Fill `run`** with that structure (the `RunRecord` shape: `calls` / `tool_calls` /
   `spawns`).
3. **Get the ground-truth cost:**
   - Preferred — note the provider's **billed** amount for this run from the billing
     dashboard; set `expected_usd` to it and `expected_usd_source: "invoice"`.
   - Fallback — recompute usage × the provider's published prices; set
     `expected_usd_source: "usage_x_published_price"` (weaker; see circularity above).
4. Set `source: "real"`, `price_table_version` to the table you'll test against, and a
   `provenance` line (provider, model, date, dashboard link).
5. Drop the JSON here. When enough **invoice**-grounded reals across providers pass at
   ≤1%, the meter is validated (AC-1) and `test_ma1_real_invoice_corpus` flips from
   skip to pass.

> A single real invoice-grounded fixture already beats zero — it turns the ≤1% claim
> from "unverified" into "verified for N runs". You do not need all 20 to start.
