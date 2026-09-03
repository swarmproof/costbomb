# Validating costbomb's meter — per biller, honestly

costbomb's reported dollars are a **sum across different billers**. No single invoice
proves the whole number, so validation is per-slice: meter one slice, fetch what its
biller actually charged, compare within 1% (`costbomb.validation.reconcile`).

## The slices and who bills each

| Slice | Field | Billed by | How to validate | Status |
|-------|-------|-----------|-----------------|--------|
| Model tokens | `model_usd` | the LLM provider | full agent run → provider dashboard | **invoice-backable** (harness ready) |
| Provider tool fees | part of `tool_usd` | the LLM provider | same run's dashboard | invoice-backable |
| Local/external tool fees | part of `tool_usd` | that tool's vendor | the vendor's bill | modeled |
| Downstream consequence | `downstream_usd` / `blast_radius_usd` | e.g. Stripe | agent → Stripe **test-mode** → dashboard | invoice-backable (harness ready) |
| Duplicate-effect | `duplicate_effect_usd` | e.g. Stripe | same Stripe test run + `exactly_once` | verified vs real `exactly_once` lib |
| Wall-clock / infra | `infra_usd` | your cloud | run duration × the cloud's per-second rate | modeled |

**A green run is not "the meter is proven" — it's "the *invoice-backed* slices are
proven."** `total_usd` is only fully invoice-backed once the LLM slice passes; the
downstream slice needs its own (Stripe) reconciliation.

## LLM slice — full-agent, invoice-backed

Runs the multi-turn tool-using ReAct agent (`examples/react_agent.py`) through the
proxy so the **whole agent** is metered, not isolated calls.

```bash
# free plumbing/capture proof (local Ollama — proves a full agent is captured, $0 bill):
costbomb proxy --upstream http://localhost:11434 --port 8100 \
    --price-table examples/prices_mistral_small.json &
python examples/validate_llm_slice.py --model mistral-small:latest

# invoice-backed proof (paid): run on a FRESH api key so the dashboard isolates this
# run's cost, then pass it:
costbomb proxy --upstream https://api.openai.com --port 8100 &
python examples/validate_llm_slice.py --model gpt-4o-mini --billed-usd <dashboard $>
```

Needs: a provider key + a few cents. Emits a `source: "real"`,
`expected_usd_source: "invoice"` fixture into `tests/fixtures/meter/` and flips the
`0/20 invoice-grounded` gate toward a pass.

## Downstream slice — Stripe test-mode

Runs an agent whose side-effecting tool actually creates **test-mode** Stripe charges
(no real money), then reconciles costbomb's `blast_radius_usd` / `duplicate_effect_usd`
against the charges Stripe's API reports (`examples/validate_stripe_slice.py`).

```bash
export STRIPE_API_KEY=sk_test_...   # TEST key only
python examples/validate_stripe_slice.py
```

Needs: Stripe **test** keys (free). Proves the "money moved" number against a real
payment ledger — the validation an LLM invoice can never give.
