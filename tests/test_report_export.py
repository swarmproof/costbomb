"""Reporter + exports (TEST-PLAN §4 IT-6/7, REQ-RP-2/3/5)."""

from __future__ import annotations

from rich.console import Console

from costbomb.engine import FuzzEngine, SearchConfig
from costbomb.export import findings_json, otel_spans
from costbomb.pricing import PriceTable
from costbomb.report import headline, render_terminal
from costbomb.targets.fake import FakeTarget


def _rf(prices: PriceTable):
    return FuzzEngine(FakeTarget(), prices=prices, config=SearchConfig(seed=1337, k=3, max_spend_usd=2.0)).run()


def test_it_6_report_renders_headline_and_table(prices: PriceTable) -> None:
    rf = _rf(prices)
    console = Console(record=True, width=100)
    render_terminal(rf, console=console)
    text = console.export_text()
    assert "amplification" in text
    assert "Worst offenders" in text
    assert "×" in headline(rf)


def test_req_rp_2_economic_fragment_merges_into_adversarial(prices: PriceTable) -> None:
    rf = _rf(prices)
    # simulate stampede's existing adversarial section
    adversarial = {"cohort_size": 10, "injection_probes": 10, "destructive_reached": 1,
                   "denial_of_wallet_flags": 0}
    merged = rf.economic_fragment(adversarial)
    assert "economic" in merged
    assert merged["cohort_size"] == 10  # stampede keys preserved
    assert merged["denial_of_wallet_flags"] == len(rf.findings)  # bumped by costbomb
    assert merged["economic"]["amplification_factor"] == round(rf.amplification_factor, 2)


def test_it_7_findings_and_otel_export(prices: PriceTable) -> None:
    rf = _rf(prices)
    fj = findings_json(rf)
    assert {"run_id", "worst_usd", "amplification_factor", "findings"} <= set(fj)
    assert all({"attack_class", "worst_usd", "repro"} <= set(f) for f in fj["findings"])

    otel = otel_spans(rf)
    assert otel["traces"], "no traces exported"
    span = otel["traces"][0]["trace"]["spans"][0]
    # spans carry the OTel GenAI-profile attribute keys (gen_ai.* / swarmproof.*)
    assert any(k.startswith(("gen_ai.", "swarmproof.")) for k in span["attributes"])
