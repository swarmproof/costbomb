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


def test_registry_has_the_five_v01_classes() -> None:
    assert set(registry.names()) == {
        "clarification-trap", "context-bomb", "recursion", "retry-loop", "tool-storm",
    }


def test_input_id_is_stable_content_hash() -> None:
    a = Input(text="hello", attack_class="retry-loop")
    b = Input(text="hello", attack_class="retry-loop")
    assert a.id == b.id
    assert Input(text="hello", attack_class="tool-storm").id != a.id
