"""
SEO generator call parameters (2026-09-26 cost review).

Both generators run with reasoning.effort=low — the page copy is ~300
visible output tokens and default effort spent another ~150 reasoning — and
print a one-line usage record so seo_worker.log carries token counts
(the backend has no access to the scanner's SQLite usage table).
"""

import json
from types import SimpleNamespace

import event_seo_generator
import seo_generator

REPLY = json.dumps({
    "seo_title": "t", "seo_description": "d", "seo_summary": "s",
    "seo_faqs": [{"question": "q", "answer": "a"}],
})


def _usage():
    return SimpleNamespace(
        input_tokens=528,
        input_tokens_details=SimpleNamespace(cached_tokens=0),
        output_tokens=445,
        output_tokens_details=SimpleNamespace(reasoning_tokens=152),
    )


def _fake_client_class(calls):
    class FakeResponses:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(output_text=REPLY, usage=_usage())

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.responses = FakeResponses()

    return FakeClient


def _wire(monkeypatch, module):
    calls = []
    monkeypatch.setattr(module, "AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(module, "OpenAI", _fake_client_class(calls))
    return calls


def test_market_generator_uses_low_reasoning(monkeypatch):
    calls = _wire(monkeypatch, seo_generator)

    result = seo_generator.generate_seo_content(market_title="Will X happen?")

    assert result["seo_title"] == "t"
    assert calls[0]["reasoning"] == {"effort": "low"}


def test_event_generator_uses_low_reasoning(monkeypatch):
    calls = _wire(monkeypatch, event_seo_generator)

    result = event_seo_generator.generate_event_seo_content(event_title="Event X")

    assert result["seo_title"] == "t"
    assert calls[0]["reasoning"] == {"effort": "low"}


def test_market_generator_prints_usage_line(monkeypatch, capsys):
    _wire(monkeypatch, seo_generator)

    seo_generator.generate_seo_content(market_title="Will X happen?")

    assert "[seo_generator] usage kind=market_seo prompt=528 cached=0 output=445 reasoning=152" \
        in capsys.readouterr().out


def test_event_generator_prints_usage_line(monkeypatch, capsys):
    _wire(monkeypatch, event_seo_generator)

    event_seo_generator.generate_event_seo_content(event_title="Event X")

    assert "[seo_generator] usage kind=event_seo prompt=528 cached=0 output=445 reasoning=152" \
        in capsys.readouterr().out
