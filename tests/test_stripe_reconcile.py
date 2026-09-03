"""Stripe-slice reconciliation — downstream/blast-radius vs a real payment ledger.

Uses a fake `stripe` module that mimics the real idempotency-key behaviour, so the
reconciliation logic is proven offline. The live proof needs `sk_test_...` keys.
"""

from __future__ import annotations

import sys
import types

import pytest

from costbomb.meter import CostMeter
from costbomb.pricing import PriceTable
from costbomb.targets.base import RunRecord, ToolCall


class _PI:
    def __init__(self, pid: str, amount: int) -> None:
        self.id = pid
        self.amount = amount
        self.status = "succeeded"
        self.livemode = False


def _fake_stripe() -> types.ModuleType:
    mod = types.ModuleType("stripe")

    class PaymentIntent:
        _by_key: dict[str, _PI] = {}
        _all: list[_PI] = []
        _n = 0

        @classmethod
        def create(cls, *, amount: int, idempotency_key: str | None = None, **kw) -> _PI:
            if idempotency_key and idempotency_key in cls._by_key:
                return cls._by_key[idempotency_key]  # Stripe dedupes on the key
            cls._n += 1
            pi = _PI(f"pi_{cls._n}", amount)
            if idempotency_key:
                cls._by_key[idempotency_key] = pi
            cls._all.append(pi)
            return pi

        @classmethod
        def list(cls, **kw):  # noqa: A003
            paging = types.SimpleNamespace(auto_paging_iter=lambda: iter(list(cls._all)))
            return paging

    mod.PaymentIntent = PaymentIntent  # type: ignore[attr-defined]
    return mod


@pytest.fixture
def stripe_mod(monkeypatch):
    mod = _fake_stripe()
    monkeypatch.setitem(sys.modules, "stripe", mod)
    return mod


def test_without_idempotency_stripe_records_every_charge(stripe_mod) -> None:
    from costbomb.integrations.stripe_reconcile import create_test_charge, sum_test_charges

    for _ in range(5):  # same order, NO key → 5 distinct charges (the bug)
        create_test_charge(50.0, key="charge:order-1", idempotent=False)
    usd, n = sum_test_charges()
    assert (usd, n) == (250.0, 5)


def test_with_idempotency_stripe_dedupes(stripe_mod) -> None:
    from costbomb.integrations.stripe_reconcile import create_test_charge, sum_test_charges

    for _ in range(5):  # same order + key → Stripe collapses to ONE charge
        create_test_charge(50.0, key="charge:order-1", idempotent=True)
    usd, n = sum_test_charges()
    assert (usd, n) == (50.0, 1)


def test_costbomb_prediction_matches_stripe_ledger(stripe_mod) -> None:
    from costbomb.integrations.stripe_reconcile import create_test_charge, sum_test_charges

    prices = PriceTable.default()
    rec = RunRecord(tool_calls=[ToolCall("charge_card", key="charge:order-1") for _ in range(5)])
    bd = CostMeter(prices).cost(rec.to_trace(seed=0))

    # No idempotency: Stripe records the full blast radius costbomb predicted.
    for _ in range(5):
        create_test_charge(50.0, key="charge:order-1", idempotent=False)
    usd, _ = sum_test_charges()
    assert usd == pytest.approx(bd.blast_radius_usd)  # $250

    # exactly-once (idempotent): Stripe records only what costbomb said would survive.
    stripe_mod.PaymentIntent._by_key.clear()
    stripe_mod.PaymentIntent._all.clear()
    for _ in range(5):
        create_test_charge(50.0, key="charge:order-1", idempotent=True)
    usd2, _ = sum_test_charges()
    assert usd2 == pytest.approx(bd.blast_radius_usd - bd.duplicate_effect_usd)  # $50
