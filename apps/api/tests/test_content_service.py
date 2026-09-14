import sys
from types import SimpleNamespace

from app.modules.content import service


SIGNALS = [{
    "source": "manual",
    "type": "hint",
    "title": "Shipped consent controls",
    "content": "Added scoped consent controls and manual approval.",
}]


def test_draft_uses_template_without_openai_key(monkeypatch) -> None:
    monkeypatch.setattr(service, "OPENAI_API_KEY", "")

    result = service.draft_post(SIGNALS)

    assert "Shipped consent controls" in result


def test_draft_uses_agents_sdk_with_tracing_disabled(monkeypatch) -> None:
    monkeypatch.setattr(service, "OPENAI_API_KEY", "test-key")
    captured = {}

    class Result:
        final_output = "A grounded LinkedIn draft."

    def fake_run(agent, prompt, *, run_config):
        captured.update(agent=agent, prompt=prompt, run_config=run_config)
        return Result()

    class Agent:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class RunConfig:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    monkeypatch.setitem(sys.modules, "agents", SimpleNamespace(
        Agent=Agent,
        RunConfig=RunConfig,
        Runner=SimpleNamespace(run_sync=fake_run),
    ))

    assert service.draft_post(SIGNALS) == "A grounded LinkedIn draft."
    assert captured["agent"].name == "LinkedInDraftingAgent"
    assert captured["agent"].model == service.OPENAI_MODEL
    assert "authorized_source_context" in captured["prompt"]
    assert captured["run_config"].tracing_disabled is True


def test_draft_falls_back_when_agent_fails(monkeypatch) -> None:
    monkeypatch.setattr(service, "OPENAI_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "agents", SimpleNamespace(
        Agent=lambda **kwargs: kwargs,
        RunConfig=lambda **kwargs: kwargs,
        Runner=SimpleNamespace(run_sync=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError())),
    ))

    result = service.draft_post(SIGNALS)

    assert "Shipped consent controls" in result
