import pytest

from app.llm import llm


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Tests exercise the rule-based fallbacks, whatever is in the environment."""
    monkeypatch.setattr(llm, "client", None)
