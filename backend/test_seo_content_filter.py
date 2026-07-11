"""
Tests for Azure content-filter handling in the SEO generators.

A prompt blocked by Azure's content filter (400, code='content_filter') is
permanent — retrying the same prompt every worker pass just burns API calls.
The generators must surface it as ContentFilterError so the worker can mark
the row as skipped, while other errors keep the old return-None behavior
(transient, worth retrying next pass).
"""

import pytest

import seo_generator
import event_seo_generator
from seo_generator import ContentFilterError


class FakeContentFilterError(Exception):
    """Mimics openai.BadRequestError for an Azure content-filter block."""
    code = "content_filter"


class FakeServerError(Exception):
    code = "server_error"


def _fake_client_class(exc):
    class FakeResponses:
        def create(self, **kwargs):
            raise exc

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.responses = FakeResponses()

    return FakeClient


# ---------------------------------------------------------------- market

def test_market_generator_raises_on_content_filter(monkeypatch):
    monkeypatch.setattr(seo_generator, "AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        seo_generator, "OpenAI", _fake_client_class(FakeContentFilterError("blocked"))
    )
    with pytest.raises(ContentFilterError):
        seo_generator.generate_seo_content(market_title="Will X strike Y?")


def test_market_generator_returns_none_on_other_errors(monkeypatch):
    monkeypatch.setattr(seo_generator, "AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        seo_generator, "OpenAI", _fake_client_class(FakeServerError("boom"))
    )
    assert seo_generator.generate_seo_content(market_title="Will X happen?") is None


# ---------------------------------------------------------------- event

def test_event_generator_raises_on_content_filter(monkeypatch):
    monkeypatch.setattr(event_seo_generator, "AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        event_seo_generator, "OpenAI", _fake_client_class(FakeContentFilterError("blocked"))
    )
    with pytest.raises(ContentFilterError):
        event_seo_generator.generate_event_seo_content(event_title="X vs Y")


def test_event_generator_returns_none_on_other_errors(monkeypatch):
    monkeypatch.setattr(event_seo_generator, "AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        event_seo_generator, "OpenAI", _fake_client_class(FakeServerError("boom"))
    )
    assert event_seo_generator.generate_event_seo_content(event_title="X vs Y") is None


# ------------------------------------------------------- prompt framing

def test_market_prompt_has_neutral_framing():
    prompt = seo_generator._build_market_prompt("Will X strike Y?")
    assert "quoted verbatim" in prompt


def test_event_prompt_has_neutral_framing():
    prompt = event_seo_generator._build_event_prompt("X vs Y")
    assert "quoted verbatim" in prompt
