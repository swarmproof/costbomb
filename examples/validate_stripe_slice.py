"""Validate costbomb's downstream/blast-radius slice against Stripe test-mode.

A refund bot re-charges the SAME order N times (the duplicate-charge bug). We meter it
with costbomb (predicting the blast radius + what exactly-once would prevent), actually
create the charges in Stripe **test mode**, and compare costbomb's prediction to what
Stripe's ledger recorded. Run it twice — with and without idempotency keys — to see
Stripe confirm both the exposure and the exactly-once fix.

    export STRIPE_API_KEY=sk_test_...        # TEST key only — never a live key
    python examples/validate_stripe_slice.py --charges 5 --idempotent false
    python examples/validate_stripe_slice.py --charges 5 --idempotent true
"""

from __future__ import annotations

import argparse
import sys
import time

from costbomb.integrations.stripe_reconcile import (
    StripeSliceResult,
    create_test_charge,
    sum_test_charges,
)
from costbomb.meter import CostMeter
from costbomb.pricing import PriceTable
from costbomb.targets.base import RunRecord, ToolCall

ORDER_KEY = "charge:order-R100"
CHARGE_USD = 50.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--charges", type=int, default=5)
    ap.add_argument("--idempotent", default="false", choices=["true", "false"])
    args = ap.parse_args()
    idempotent = args.idempotent == "true"

    # 1. costbomb's prediction (meter the run). charge_card is priced at $50 downstream.
    prices = PriceTable.default()
    rec = RunRecord(tool_calls=[ToolCall("charge_card", key=ORDER_KEY) for _ in range(args.charges)])
    bd = CostMeter(prices).cost(rec.to_trace(seed=0))
    with_eo = bd.blast_radius_usd - bd.duplicate_effect_usd  # exactly-once removes the dupes

    # 2. actually create the charges in Stripe test-mode.
    since = int(time.time())
    try:
        for _ in range(args.charges):
            create_test_charge(CHARGE_USD, key=ORDER_KEY, idempotent=idempotent)
        time.sleep(1)  # let the ledger settle
        stripe_usd, stripe_n = sum_test_charges(since=since)
    except ImportError as exc:
        print(exc)
        return 1
    except Exception as exc:  # noqa: BLE001 - surface Stripe/auth errors plainly
        print(f"Stripe call failed (test key set? test mode?): {exc}")
        return 1

    result = StripeSliceResult(
        predicted_blast_usd=bd.blast_radius_usd,
        predicted_with_exactly_once_usd=with_eo,
        stripe_recorded_usd=stripe_usd,
        stripe_charge_count=stripe_n,
    )
    print(f"\n=== downstream slice vs Stripe test-mode (idempotent={idempotent}) ===")
    print("  " + result.summary())
    expected = with_eo if idempotent else bd.blast_radius_usd
    ok = abs(stripe_usd - expected) < 0.01
    print(f"  Stripe {'CONFIRMS' if ok else 'DIVERGES from'} costbomb "
          f"(expected ${expected:.2f}{' — exactly-once deduped' if idempotent else ''})")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
