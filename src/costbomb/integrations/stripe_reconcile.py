"""Stripe integration — validate the downstream/blast-radius slice (REQ-RP-4).

The "money moved" costbomb models (`downstream_usd`, `blast_radius_usd`,
`duplicate_effect_usd`) is billed by Stripe, not the LLM provider — so it's validated
against Stripe's own ledger, in **test mode** (no real money). This module drives a
side-effecting agent's charges through Stripe test-mode and reconciles what costbomb
*predicted* against what Stripe *actually recorded*.

Because Stripe has native **idempotency keys**, it also validates the exactly-once
cross-check for real: charge one order N times without a key → Stripe records N
(matches `blast_radius_usd`); with a key → Stripe records 1 (matches "exactly-once
would prevent the rest").

    pip install costbomb[stripe]   # then export STRIPE_API_KEY=sk_test_...
"""

from __future__ import annotations

from dataclasses import dataclass


def _require_stripe():
    try:
        import stripe
    except ImportError as exc:  # pragma: no cover - only when extra absent
        raise ImportError(
            "the Stripe reconciliation needs the sibling extra: pip install costbomb[stripe]"
        ) from exc
    return stripe


def create_test_charge(amount_usd: float, *, key: str, idempotent: bool) -> str:
    """Create ONE test-mode PaymentIntent. Returns its id.

    ``idempotent=True`` passes ``idempotency_key=key`` so Stripe collapses repeats of
    the same order into a single charge — the real exactly-once guarantee.
    """
    stripe = _require_stripe()
    kwargs: dict = {"amount": int(round(amount_usd * 100)), "currency": "usd",
                    "payment_method": "pm_card_visa", "confirm": True,
                    "automatic_payment_methods": {"enabled": True, "allow_redirects": "never"}}
    opts = {"idempotency_key": key} if idempotent else {}
    intent = stripe.PaymentIntent.create(**kwargs, **opts)
    return intent.id


def sum_test_charges(*, since: int | None = None) -> tuple[float, int]:
    """Total USD and count of **test-mode** succeeded PaymentIntents (Stripe's ledger)."""
    stripe = _require_stripe()
    total_cents = 0
    count = 0
    params: dict = {"limit": 100}
    if since is not None:
        params["created"] = {"gte": since}
    for pi in stripe.PaymentIntent.list(**params).auto_paging_iter():
        if getattr(pi, "livemode", False):
            continue  # never count real charges
        if getattr(pi, "status", "") == "succeeded":
            total_cents += int(getattr(pi, "amount", 0) or 0)
            count += 1
    return total_cents / 100.0, count


@dataclass
class StripeSliceResult:
    predicted_blast_usd: float  # costbomb blast_radius / downstream
    predicted_with_exactly_once_usd: float  # after the duplicate cross-check removes dupes
    stripe_recorded_usd: float  # what Stripe's ledger actually shows
    stripe_charge_count: int

    def summary(self) -> str:
        return (
            f"costbomb predicted ${self.predicted_blast_usd:.2f} blast radius "
            f"(${self.predicted_with_exactly_once_usd:.2f} with exactly-once) — "
            f"Stripe recorded ${self.stripe_recorded_usd:.2f} across "
            f"{self.stripe_charge_count} test charge(s)"
        )
