"""Release regressions: named models and benchmark ceilings reach the run."""

from app import bench, benchcases, modeldiscovery
from app.providers import _api_agent, apiagent
from app.web.settings import Settings


def test_api_agent_includes_models_reported_by_its_provider(monkeypatch, tmp_path):
    monkeypatch.setattr(modeldiscovery, "cached", lambda: {"mistral": ["new-hosted-model"]})
    assert "new-hosted-model" in apiagent.models_for(apiagent.MISTRAL, tmp_path)


def test_explicit_unpriced_model_is_not_silently_replaced(tmp_path):
    researcher = _api_agent(apiagent.MISTRAL, timeout=1, model="new-hosted-model",
                            app_state_path=tmp_path / "app.sqlite")
    assert researcher.model == "new-hosted-model"


def test_fixed_benchmark_passes_its_ceiling_and_records_requested_model(monkeypatch):
    class Reader:
        max_documents = 0
        max_pages = 40
        budget_usd = 0.0
        requested_model = "test-model"
        model = "test-harness"
        sources = {}

        def ask(self, prompt):
            assert self.max_documents == 2
            assert self.max_pages == 2
            assert self.budget_usd == 0.15
            return '{"risks": []}'

    monkeypatch.setattr(bench, "_asker", lambda *args: Reader())
    row = bench.run_case(Settings(), benchcases.case_rows(1)[0], plane="harness",
                         model="test-model", max_documents=2, budget_usd=0.15)
    assert not row.get("error")
    assert row["model"] == "test-model"
