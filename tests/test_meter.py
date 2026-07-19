"""Cost-meter accuracy — the oracle (TEST-PLAN §3.1, §6). Highest priority."""

from __future__ import annotations

import pytest

from costbomb.meter import CostMeter
from costbomb.pricing import PriceTable, UnpricedModelError
from costbomb.tracebuild import TraceBuilder

MODEL = "anthropic:claude-opus-4-8"  # in 3e-6, out 1.5e-5, reason 1.5e-5, cr 3e-7, cw 3.75e-6


def _tb(seed: int = 1) -> TraceBuilder:
    return TraceBuilder(seed)


def test_ut_cm_1_sum_over_sources_to_the_cent(prices: PriceTable) -> None:
    tb = _tb()
    root = tb.root()
    tb.chat(root, model=MODEL, provider="anthropic", input_tokens=1000, output_tokens=100)
    tb.tool(root, tool_name="premium_api")  # 0.02
    sub = tb.spawn(root)
    tb.chat(sub, model=MODEL, provider="anthropic", input_tokens=500, output_tokens=50)
    bd = CostMeter(prices).cost(tb.build())

    expected_model = (1000 * 3.0e-6 + 100 * 1.5e-5) + (500 * 3.0e-6 + 50 * 1.5e-5)
    assert bd.model_usd == pytest.approx(expected_model)
    assert bd.tool_usd == pytest.approx(0.02)
    assert bd.total_usd == pytest.approx(expected_model + 0.02)
    assert bd.model_usd + bd.tool_usd == pytest.approx(bd.total_usd)  # invariant


def test_ut_cm_2_reasoning_and_cache_priced_distinctly(prices: PriceTable) -> None:
    tb = _tb()
    root = tb.root()
    tb.chat(root, model=MODEL, provider="anthropic", input_tokens=0, output_tokens=0,
            reasoning_tokens=1000, cache_read_tokens=1000, cache_write_tokens=1000)
    bd = CostMeter(prices).cost(tb.build())
    assert bd.total_usd == pytest.approx(1000 * 1.5e-5 + 1000 * 3.0e-7 + 1000 * 3.75e-6)


def test_ut_cm_3_subagent_rollup(prices: PriceTable) -> None:
    tb = _tb()
    root = tb.root()
    for _ in range(2):
        sub = tb.spawn(root)
        tb.chat(sub, model=MODEL, provider="anthropic", input_tokens=1000, output_tokens=0)
    bd = CostMeter(prices).cost(tb.build())
    assert bd.n_spawns == 2
    assert bd.spawn_usd == pytest.approx(2 * 1000 * 3.0e-6)
    assert bd.total_usd == pytest.approx(bd.spawn_usd)  # all cost is inside spawns


def test_ut_cm_4_tool_fees_scale(prices: PriceTable) -> None:
    tb = _tb()
    root = tb.root()
    for _ in range(5):
        tb.tool(root, tool_name="premium_api")
    bd = CostMeter(prices).cost(tb.build())
    assert bd.n_tool_calls == 5
    assert bd.tool_usd == pytest.approx(5 * 0.02)


def test_ut_cm_6_unknown_model_is_loud_never_free(prices: PriceTable) -> None:
    tb = _tb()
    root = tb.root()
    tb.chat(root, model="openai:gpt-does-not-exist", provider="openai",
            input_tokens=1000, output_tokens=100)
    with pytest.raises(UnpricedModelError):
        CostMeter(prices).cost(tb.build())


def test_ut_cm_7_reprice_same_trace_two_tables(prices: PriceTable) -> None:
    tb = _tb()
    root = tb.root()
    tb.chat(root, model=MODEL, provider="anthropic", input_tokens=1000, output_tokens=0)
    trace = tb.build()

    hiked = PriceTable.default()
    for m in hiked.models.values():
        m.input_cost_per_token *= 2
    base = CostMeter(prices).cost(trace, annotate=False).total_usd
    repriced = CostMeter(prices).reprice(trace, hiked).total_usd
    assert repriced == pytest.approx(base * 2)


def test_ma_5_price_table_parse_roundtrips() -> None:
    pt = PriceTable.default()
    assert pt.version == "2026-07-13"
    assert pt.model(MODEL).input_cost_per_token == 3.0e-6
    assert pt.tool_price("premium_api") == 0.02
    assert pt.tool_price("free_unknown_tool") == 0.0  # unknown tool → free, not error
