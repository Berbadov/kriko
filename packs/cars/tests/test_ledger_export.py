

def test_a_one_model_part_drops_claims_about_another_generation():
    from packs.cars.build import _names_another_generation

    body = {"model": {"megane"}, "generation": {"IV"}}
    shared = {"model": {"megane", "clio"}, "generation": {"IV", "V"}}
    assert _names_another_generation({"title": "Xenon fault (2011 Renault Mégane 3)"}, body)
    assert not _names_another_generation({"title": "Judder (Mégane III/IV)"}, body)
    assert not _names_another_generation({"title": "Boot seal leaks"}, body)
    # A part fitted to more than one model keeps it: a shared engine's fault
    # carries across generations.
    assert not _names_another_generation({"title": "Turbo failure (Megane II)"}, shared)
