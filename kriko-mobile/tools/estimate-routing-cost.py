"""Reproducible planning scenarios; these are assumptions, not production telemetry."""
import json

# USD per million tokens, official Mistral model cards, checked 2026-10-31.
RATES = {"3b": (0.10, 0.10), "8b": (0.15, 0.15), "glm_flash": (0.15, 0.50)}


def model_cost(model, input_tokens=600, output_tokens=200):
    incoming, outgoing = RATES[model]
    return (input_tokens * incoming + output_tokens * outgoing) / 1_000_000


def service(api):
    return api * 1.20 + 0.001


def scenario(simple_share, simple_hit_rate):
    # Among non-simple shopping turns, keep the earlier 75% screenshot / 25% deep mix.
    # Simple calls are assumed 25% 3B, 75% 8B; one 600-in/200-out call, no tools.
    simple_api = .25 * model_cost("3b") + .75 * model_cost("8b")
    shopping_api = .75 * .01148 + .25 * .02781
    # Old quick-research estimate includes two retrievals. Also compare equal
    # compact prompts with Mercury doing NO retrieval, to avoid claiming those
    # retrievals were always needed for a simple question.
    baseline = service(simple_share * .00366 + (1 - simple_share) * shopping_api)
    same_prompt_baseline = service(simple_share * .00026 + (1 - simple_share) * shopping_api)
    optimized = service(simple_share * (1 - simple_hit_rate) * simple_api + (1 - simple_share) * shopping_api)
    return {"simple_share": simple_share, "cache_hit_rate_among_simple": simple_hit_rate,
            "old_quick_research_baseline_usd": baseline,
            "same_prompt_mercury_baseline_usd": same_prompt_baseline,
            "optimized_usd_per_query": optimized,
            "savings_percent": 100 * (1 - optimized / baseline)}


if __name__ == "__main__":
    print(json.dumps({
        "assumptions_not_measurements": True,
        "simple_api_usd": {model: model_cost(model) for model in RATES},
        "scenarios": [scenario(share, hits) for share in (.2, .4, .6) for hits in (0, .10)],
        "plans_at_002_per_credit": [
            {"price": price, "credits": credits,
             "full_use_contribution": price * .85 - credits * .02 - other}
            for price, credits, other in ((6.99, 100, .25), (12.99, 250, .40))
        ],
    }, indent=2))
