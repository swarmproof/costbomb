"""Attack library — seeds/mutate/applicable/signal (TEST-PLAN §3.2)."""

from __future__ import annotations

from random import Random

from costbomb.attacks import registry
from costbomb.attacks.base import Input, TargetCapabilities


def _caps(**kw) -> TargetCapabilities:
    base = {"has_tools": True, "can_spawn": True, "accepts_documents": True}
    base.update(kw)
    return TargetCapabilities(**base)


def test_ut_al_1_all_classes_produce_seeds_and_mutations() -> None:
    caps = _caps()
    for atk in registry.all():
        seeds = atk.seeds(caps)
        assert seeds and all(isinstance(s, Input) for s in seeds)
        child = atk.mutate(seeds[0], Random(0))
        assert child.text != seeds[0].text  # mutation changes the input
        assert child.generation == seeds[0].generation + 1
        assert child.parent_id == seeds[0].id


def test_ut_al_2_template_mutation_is_deterministic() -> None:
    atk = registry.get("retry-loop")
    seed = atk.seeds(_caps())[0]
    a = atk.mutate(seed, Random(123))
    b = atk.mutate(seed, Random(123))
    assert a.text == b.text  # same rng seed → same mutation


def test_ut_al_3_applicable_gates_by_capability() -> None:
    assert registry.get("recursion").applicable(_caps(can_spawn=True))
    assert not registry.get("recursion").applicable(_caps(can_spawn=False))
    assert not registry.get("tool-storm").applicable(_caps(has_tools=False))

    skipped = registry.skipped(_caps(can_spawn=False, has_tools=False))
    assert "recursion" in skipped and "tool-storm" in skipped


V01 = {"clarification-trap", "context-bomb", "recursion", "retry-loop", "tool-storm"}
V02 = {"reasoning-inflation", "model-escalation", "cache-bust", "tool-cost-asymmetry",
       "retrieval-amplification"}


def test_registry_has_v01_and_v02_classes() -> None:
    assert set(registry.names()) == V01 | V02


def test_v02_applicability_gated_by_new_capabilities() -> None:
    bare = TargetCapabilities(has_tools=True, priced_tool_names=(), supports_reasoning=False,
                              uses_cache=False, is_routed=False, has_retrieval=False)
    # none of the v0.2 preconditions met → all five skipped (honest coverage)
    assert set(registry.skipped(bare)) >= V02

    rich = TargetCapabilities(has_tools=True, priced_tool_names=("premium_api",),
                              supports_reasoning=True, uses_cache=True, is_routed=True,
                              has_retrieval=True)
    applicable = {a.name for a in registry.applicable(rich)}
    assert applicable >= V02


def test_v02_classes_climb_on_fake_target(prices) -> None:
    from costbomb.engine import FuzzEngine, SearchConfig
    from costbomb.targets.fake import FakeTarget

    for name in sorted(V02):
        cfg = SearchConfig(seed=7, classes=(name,), max_spend_usd=1.0, k=2)
        rf = FuzzEngine(FakeTarget(), prices=prices, config=cfg).run()
        assert rf.findings, f"{name}: no findings"
        assert rf.findings[0].attack_class == name
        assert rf.worst_usd > rf.baseline_usd, f"{name} did not climb above baseline"


def test_input_id_is_stable_content_hash() -> None:
    a = Input(text="hello", attack_class="retry-loop")
    b = Input(text="hello", attack_class="retry-loop")
    assert a.id == b.id
    assert Input(text="hello", attack_class="tool-storm").id != a.id
