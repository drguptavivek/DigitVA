"""Gemini provider call (docs/policy/ai-analytics-questions.md)."""
import weakref
from types import SimpleNamespace
from unittest.mock import patch

from app.services import ai_analytics_providers as providers
from tests.base import BaseTestCase


class _FakeClient:
    """genai.Client closes its HTTP client when garbage collected; the request
    must therefore run while the Client object is still referenced."""

    def __init__(self):
        alive = weakref.ref(self)

        def generate_content(**_kwargs):
            if alive() is None:
                raise RuntimeError("Cannot send a request, as the client has been closed.")
            return SimpleNamespace(text='{"sql": "select 1"}', usage_metadata=None)

        self.models = SimpleNamespace(generate_content=generate_content)


class GeminiPlanTest(BaseTestCase):
    def test_client_stays_alive_for_the_request(self):
        with patch.object(providers, "_client", side_effect=lambda _p: _FakeClient()):
            reply = providers.plan(providers.GEMINI, "system", "prompt", {"type": "object"})
        self.assertEqual(reply.text, '{"sql": "select 1"}')
