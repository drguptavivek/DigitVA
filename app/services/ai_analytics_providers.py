"""The two model providers behind AI analytics questions (digitva-qwvt).

docs/policy/ai-analytics-questions.md, "Providers". One call shape for both:
``plan(provider, prompt, schema, retry=...)`` sends the fixed
``system`` instruction and one user message, asks for JSON matching
*schema*, and returns a ``Reply``. Neither implementation sends anything
else; the planner decides what goes into *prompt* (never result rows).

A provider is enabled when ``AI_ANALYTICS_ENABLED`` is set and its
credentials are configured; ``PROVIDERS`` is also the default order.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from flask import current_app

log = logging.getLogger(__name__)

ANTHROPIC = "anthropic"
GEMINI = "gemini"
PROVIDERS = (ANTHROPIC, GEMINI)
PROVIDER_LABELS = {ANTHROPIC: "Claude (Anthropic)", GEMINI: "Gemini (Google)"}
ANTHROPIC_MAX_TOKENS = 4000
_ANTHROPIC_BETAS = ["server-side-fallback-2026-07-01"]


class ProviderError(Exception):
    """A call that gave no usable answer; ``message`` is safe to show."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Reply:
    text: str
    model: str
    # prompt_tokens, cached_tokens, output_tokens (audit-log column names)
    usage: dict = field(default_factory=dict)


def enabled_providers() -> list[str]:
    """Enabled providers in default order; empty while the feature is off."""
    config = current_app.config
    if not config.get("AI_ANALYTICS_ENABLED"):
        return []
    enabled = []
    if config.get("ANTHROPIC_API_KEY"):
        enabled.append(ANTHROPIC)
    if config.get("GOOGLE_CLOUD_PROJECT") or config.get("GEMINI_API_KEY"):
        enabled.append(GEMINI)
    return enabled


def model_name(provider: str) -> str:
    config = current_app.config
    if provider == ANTHROPIC:
        return config.get("AI_ANALYTICS_MODEL_ANTHROPIC") or "claude-sonnet-5-5"
    return config.get("AI_ANALYTICS_MODEL_GEMINI") or "gemini-3.5-flash"


def _client(provider: str):
    """The SDK client for *provider* (tests patch this one seam)."""
    config = current_app.config
    if provider == ANTHROPIC:
        import anthropic

        return anthropic.Anthropic(api_key=config["ANTHROPIC_API_KEY"], max_retries=1, timeout=60.0)
    from google import genai

    if config.get("GOOGLE_CLOUD_PROJECT"):
        return genai.Client(
            vertexai=True,
            project=config["GOOGLE_CLOUD_PROJECT"],
            location=config.get("GOOGLE_CLOUD_LOCATION") or "asia-south1",
        )
    return genai.Client(api_key=config["GEMINI_API_KEY"])


def plan(provider: str, system: str, prompt: str, schema: dict, *, retry: bool = False,
         max_tokens: int = ANTHROPIC_MAX_TOKENS) -> Reply:
    """One model call. *retry* thinks a little harder (Claude effort medium,
    Gemini thinking level low). Raises ``ProviderError``; any other exception
    is an SDK failure the caller reports as ``model_error``."""
    if provider == ANTHROPIC:
        return _plan_anthropic(system, prompt, schema, retry=retry, max_tokens=max_tokens)
    return _plan_gemini(system, prompt, schema, retry=retry)


def _plan_anthropic(system, prompt, schema, *, retry, max_tokens) -> Reply:
    import anthropic

    model = model_name(ANTHROPIC)
    try:
        response = _client(ANTHROPIC).beta.messages.create(
            model=model,
            max_tokens=max_tokens,
            # The fixed instruction is the cached prefix; the question follows it.
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": prompt}],
            output_config={
                "effort": "medium" if retry else "low",
                "format": {"type": "json_schema", "schema": schema},
            },
            betas=_ANTHROPIC_BETAS,
            fallbacks="default",
        )
    except anthropic.RateLimitError:
        log.warning("Anthropic rate limit on an AI analytics call")
        raise ProviderError("model_busy", "The AI service is busy. Try again in a minute.") from None
    except anthropic.APIStatusError as exc:
        log.warning("Anthropic API error on an AI analytics call: status=%s", exc.status_code)
        raise ProviderError("model_error", "The AI service did not answer. Try again later.") from None
    except anthropic.APIConnectionError:
        log.warning("Anthropic connection error on an AI analytics call")
        raise ProviderError("model_error", "The AI service could not be reached. Try again later.") from None
    usage = response.usage
    reply_usage = {
        "prompt_tokens": getattr(usage, "input_tokens", None),
        "cached_tokens": getattr(usage, "cache_read_input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
    }
    if response.stop_reason == "refusal":
        raise ProviderError(
            "refused", "The AI service declined this question. Rephrase it as a question about the counts."
        )
    text = "".join(block.text for block in response.content if block.type == "text")
    return Reply(text=text, model=getattr(response, "model", None) or model, usage=reply_usage)


def _plan_gemini(system, prompt, schema, *, retry) -> Reply:
    from google.genai import types

    model = model_name(GEMINI)
    response = _client(GEMINI).models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=schema,
            thinking_config=types.ThinkingConfig(thinking_level="low" if retry else "minimal"),
        ),
    )
    meta = getattr(response, "usage_metadata", None)
    usage = {}
    if meta is not None:
        output = (meta.candidates_token_count or 0) + (meta.thoughts_token_count or 0)
        usage = {
            "prompt_tokens": meta.prompt_token_count,
            "cached_tokens": meta.cached_content_token_count,
            "output_tokens": output or None,
        }
    return Reply(text=response.text or "", model=model, usage=usage)
