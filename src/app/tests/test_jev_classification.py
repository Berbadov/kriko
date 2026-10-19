"""TypeSafe Choice classification stays opt-in and is locally validated."""

from app import categorizer


def _profile(pack_id="gaming.mice", name="Gaming mice", kind="mouse"):
    return {
        "pack_id": pack_id, "name": name, "version": "2.0.0",
        "content_digest": "abc123", "enabled": True,
        "definition": {
            "kinds": [{"id": kind, "label": kind}],
            "identity_keys": ["brand", "model"],
            "attributes": [], "examples": [],
        },
        "terms": [name, kind],
    }


def _reply(roster, *, selected="catalog_000", candidate_probability=0.97,
           confidence=0.95, model="jev-1.14.0"):
    probabilities = {key: 0.0 for key in (*roster, "uncertain")}
    probabilities[selected] = candidate_probability
    probabilities["uncertain"] = 1.0 - candidate_probability
    return {
        "model": model,
        "answers": {"catalog": {"type": "choice", "choice": selected,
                                "probabilities": probabilities,
                                "confidence": confidence}},
        "usage": {"input_tokens": 1000, "output_tokens": 10},
    }


def test_jev_request_has_full_roster_opaque_ids_and_untrusted_data_notice():
    profiles = [_profile(), _profile("tools", "Power tools", "drill")]

    request, roster = categorizer.jev_request(
        "Acme Gaming Mouse", {"category": "gaming mouse"}, profiles,
    )

    question = request["questions"]["catalog"]
    assert request["model"] == "jev-1.14.0"
    assert set(question["criteria"]) == {"catalog_000", "catalog_001", "uncertain"}
    assert roster["catalog_001"]["pack_id"] == "tools"
    assert "untrusted data" in question["instructions"]
    assert question["criteria"]["catalog_000"]["pack_id"] == "gaming.mice"


def test_jev_assignment_requires_thresholds_and_local_scope_evidence():
    profile = _profile()
    request, roster = categorizer.jev_request("Acme Gaming Mouse", {}, [profile])

    result = categorizer.parse_jev(
        _reply(roster), "Acme Gaming Mouse", {}, [profile], roster,
    )

    assert result["status"] == "assigned"
    assert result["method"] == "jev"
    assert result["pack_id"] == "gaming.mice"
    assert result["basis"] == [{"saved_text": "Acme Gaming Mouse", "catalog_text": "mouse"}]
    assert result["audit"]["response_model"] == request["model"]
    assert result["audit"]["catalog"]["content_digest"] == "abc123"
    assert result["audit"]["estimated_spend_usd"] == 0.000042


def test_jev_low_confidence_and_bad_probability_shapes_abstain():
    profile = _profile()
    _, roster = categorizer.jev_request("Acme Gaming Mouse", {}, [profile])

    low = categorizer.parse_jev(
        _reply(roster, candidate_probability=0.8, confidence=0.95),
        "Acme Gaming Mouse", {}, [profile], roster,
    )
    malformed = _reply(roster)
    malformed["answers"]["catalog"]["probabilities"]["uncertain"] = float("nan")
    invalid = categorizer.parse_jev(
        malformed, "Acme Gaming Mouse", {}, [profile], roster,
    )
    off_roster = _reply(roster)
    off_roster["answers"]["catalog"]["probabilities"]["extra"] = 0.0
    absent = categorizer.parse_jev(
        off_roster, "Acme Gaming Mouse", {}, [profile], roster,
    )

    assert low["status"] == invalid["status"] == absent["status"] == "uncertain"
    assert low["audit"]["reason"] == "below_assignment_threshold"
    assert invalid["audit"]["reason"] == "invalid_probability"
    assert absent["audit"]["reason"] == "probability_roster_mismatch"


def test_jev_non_object_response_and_empty_roster_fail_closed():
    profile = _profile()
    _, roster = categorizer.jev_request("Acme Gaming Mouse", {}, [profile])

    malformed = categorizer.parse_jev(
        ["not", "an", "object"], "Acme Gaming Mouse", {}, [profile], roster,
    )
    no_catalogs = categorizer.parse_jev(
        {}, "Acme Gaming Mouse", {}, [], {},
    )

    assert malformed["status"] == "uncertain"
    assert malformed["audit"]["reason"] == "malformed_response"
    assert no_catalogs["status"] == "uncertain"
    assert no_catalogs["audit"]["reason"] == "no_installed_catalogs"


def test_jev_selected_catalog_must_pass_product_title_scope():
    mouse = _profile()
    bike = _profile("bikes", "Electric bikes", "bicycle")
    profiles = [mouse, bike]
    _, roster = categorizer.jev_request("Acme Electric Bicycle", {}, profiles)
    reply = _reply(roster, candidate_probability=0.97)

    result = categorizer.parse_jev(
        reply, "Acme Electric Bicycle", {}, profiles, roster,
    )

    assert result["status"] == "uncertain"
    assert result["audit"]["reason"] == "unsupported_product_title_scope"


def test_jev_option_limit_abstains_without_calling_provider(monkeypatch):
    import app.providers.jev as provider

    calls = []
    monkeypatch.setattr(provider, "evaluate", lambda *args, **kwargs: calls.append(args))
    profiles = [_profile(f"catalog.{index}", f"Category {index}", f"kind{index}")
                for index in range(categorizer.JEV_MAX_OPTIONS)]

    result = categorizer.classify_with_jev("Some product", {}, profiles,
                                           api_key="not-a-real-key")

    assert result["status"] == "uncertain"
    assert result["audit"]["reason"] == "choice_limit_exceeded"
    assert calls == []


def test_configured_jev_is_never_called_after_clear_deterministic_match(monkeypatch):
    import app.providers.jev as provider

    monkeypatch.setattr(provider, "evaluate", lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("Jev must not be called for a deterministic match")))
    profile = _profile()
    profile["name"] = "Gaming Mouse"

    result = categorizer.classify_configured(
        "Acme Gaming Mouse", {"category": "Gaming Mouse"}, [profile], "typesafe",
    )

    assert result["status"] == "assigned"
    assert result["method"] == "deterministic"


def test_configured_agent_default_never_calls_jev_on_abstention(monkeypatch):
    import app.providers.jev as provider

    monkeypatch.setattr(provider, "evaluate", lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("Jev is opt-in")))

    result = categorizer.classify_configured("Unknown thing", {}, [], "agent")

    assert result["status"] == "uncertain"
    assert result["method"] == "deterministic"


def test_jev_adapter_uses_documented_endpoint_and_bearer_key(monkeypatch):
    import app.providers.jev as provider

    seen = []

    def post(url, payload, headers, *, timeout):
        seen.append((url, payload, headers, timeout))
        return {"model": "jev-1.14.0"}, ""

    monkeypatch.setattr(provider, "post_json_or_why", post)
    body, why = provider.evaluate({"model": "jev-1.14.0"}, api_key="fixture-secret")

    assert not why
    assert body["model"] == "jev-1.14.0"
    assert seen == [(
        "https://api.typesafe.ai/v1/systemone", {"model": "jev-1.14.0"},
        {"authorization": "Bearer fixture-secret"}, provider.TIMEOUT,
    )]
