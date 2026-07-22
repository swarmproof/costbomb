"""LLM-assisted mutator — cost accounting + graceful fallback (REQ-FE-4, SA-3, NFR-10)."""

from __future__ import annotations

import httpx
import pytest

from costbomb.engine import FuzzEngine, SearchConfig
from costbomb.mutator import LLMMutator
from costbomb.pricing import PriceTable
from costbomb.targets.fake import FakeTarget


class FakeMutator:
    """In-process mutator — no network. Reports a fixed per-call cost."""

    def __init__(self, *, cost: float = 0.0, fail: bool = False) -> None:
        self.last_cost_usd = 0.0
        self._cost = cost
        self._fail = fail
        self.calls = 0

    def rewrite(self, text: str, instruction: str) -> str:
        self.calls += 1
        if self._fail:
            raise RuntimeError("LLM unavailable")
        self.last_cost_usd = self._cost
        return f"{text} [llm-escalated]"


def test_use_llm_routes_mutations_through_the_mutator(prices: PriceTable) -> None:
    mut = FakeMutator()
    cfg = SearchConfig(seed=1, use_llm=True, max_spend_usd=1.0, k=2, classes=("retry-loop",))
    rf = FuzzEngine(FakeTarget(), prices=prices, config=cfg, mutator=mut).run()
    assert mut.calls > 0  # the engine used the LLM mutator
    assert rf.findings


def test_sa_3_mutator_cost_counts_against_cap(prices: PriceTable) -> None:
    # Each mutation "costs" $0.20; with a $1 cap the run must still never exceed it.
    mut = FakeMutator(cost=0.20)
    cfg = SearchConfig(seed=1, use_llm=True, max_spend_usd=1.0, k=1, classes=("retry-loop",))
    rf = FuzzEngine(FakeTarget(), prices=prices, config=cfg, mutator=mut).run()
    assert rf.own_spend_usd <= 1.0
    assert rf.stopped_reason == "budget-capped"


def test_nfr_10_llm_failure_falls_back_to_template(prices: PriceTable) -> None:
    mut = FakeMutator(fail=True)  # every rewrite raises
    cfg = SearchConfig(seed=1, use_llm=True, max_spend_usd=1.0, k=2, classes=("retry-loop",))
    rf = FuzzEngine(FakeTarget(), prices=prices, config=cfg, mutator=mut).run()
    assert mut.calls > 0
    assert rf.findings  # template mutation carried the search despite LLM failure


def test_llm_mutator_accounts_cost_from_usage() -> None:
    prices = PriceTable.default()
    mut = LLMMutator(model="openai:gpt-4o-mini", prices=prices)
    mut._account({"prompt_tokens": 1000, "completion_tokens": 500})
    mp = prices.model("openai:gpt-4o-mini")
    assert mut.last_cost_usd == pytest.approx(1000 * mp.input_cost_per_token + 500 * mp.output_cost_per_token)


def test_llm_mutator_free_model_is_zero_cost() -> None:
    mut = LLMMutator(model="ollama:llama3", prices=PriceTable.default())
    mut._account({"prompt_tokens": 9999, "completion_tokens": 9999})
    assert mut.last_cost_usd == 0.0
    assert mut._wire_model == "llama3"


def test_llm_mutator_rewrite_parses_response(monkeypatch) -> None:
    prices = PriceTable.default()
    mut = LLMMutator(model="openai:gpt-4o-mini", prices=prices)

    class _Resp:
        def raise_for_status(self) -> None: ...
        def json(self) -> dict:
            return {
                "choices": [{"message": {"content": "  rewritten harder  "}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            }

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp())
    out = mut.rewrite("do the thing", "make it worse")
    assert out == "rewritten harder"
    assert mut.last_cost_usd > 0
