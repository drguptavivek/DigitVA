"""Azure Translator v3 client for machine-drafted UI strings (digitva-cqw9).

Policy: docs/policy/ui-strings.md ("Machine candidates"). Only English UI text
is sent: never a user's data. The key is read from config, never logged and
never put in a message that reaches a caller.

``{name}`` and ``${name}`` placeholders are wrapped in a ``notranslate`` span
and the request is sent as HTML, so Azure leaves them alone. The span is
unwrapped afterwards; a placeholder Azure still mangled shows up as a changed
placeholder set, which the caller rejects.
"""

import html
import logging
import re
import time

import requests
from flask import current_app

log = logging.getLogger(__name__)

#: Azure's limits per request.
MAX_ITEMS = 1000
MAX_CHARS = 50_000
MAX_ATTEMPTS = 4
_BACKOFF_SECONDS = (1, 2, 4)
_MAX_RETRY_AFTER = 30
_TIMEOUT = (5, 30)  # connect, read

# Markup tags are shielded too (a questionnaire guidance note carries <span ...>).
_PLACEHOLDER_RE = re.compile(r"\$\{[^}]*\}|\{\w+\}|</?[A-Za-z][^<>]*>")
_SPAN_RE = re.compile(r'<span class="notranslate">(.*?)</span>', re.DOTALL)

_sleep = time.sleep  # a seam: tests do not wait


class MachineTranslationError(RuntimeError):
    """The provider could not translate. The message never holds the key."""


class NotConfigured(MachineTranslationError):
    """The Azure Translator settings are absent."""


def is_configured() -> bool:
    cfg = current_app.config
    return bool(cfg.get("AZURE_TRANSLATOR_KEY") and cfg.get("AZURE_TRANSLATOR_REGION"))


def mask(text: str) -> str:
    """Escape the text for HTML and shield each placeholder from translation."""
    parts, last = [], 0
    for m in _PLACEHOLDER_RE.finditer(text):
        parts.append(html.escape(text[last:m.start()], quote=False))
        parts.append(f'<span class="notranslate">{m.group(0)}</span>')
        last = m.end()
    parts.append(html.escape(text[last:], quote=False))
    return "".join(parts)


def unmask(text: str) -> str:
    return html.unescape(_SPAN_RE.sub(lambda m: m.group(1), text))


def _chunks(items: list[str]):
    chunk, size = [], 0
    for item in items:
        if chunk and (len(chunk) >= MAX_ITEMS or size + len(item) > MAX_CHARS):
            yield chunk
            chunk, size = [], 0
        chunk.append(item)
        size += len(item)
    if chunk:
        yield chunk


def _post(url: str, headers: dict, body: list[dict]) -> list[dict]:
    """One request, retried with backoff on 429, 5xx and network failures."""
    for attempt in range(MAX_ATTEMPTS):
        retry_after = None
        try:
            response = requests.post(url, headers=headers, json=body, timeout=_TIMEOUT)
        except requests.RequestException as exc:
            # The class only: a message can carry the URL.
            log.warning("azure translator request failed: %s", type(exc).__name__)
            status = None
        else:
            status = response.status_code
            if status == 200:
                return response.json()
            if status != 429 and status < 500:
                raise MachineTranslationError(f"Azure Translator refused the request ({status}).")
            log.warning("azure translator answered %s", status)
            try:
                retry_after = min(float(response.headers.get("Retry-After", "")), _MAX_RETRY_AFTER)
            except ValueError:
                pass
        if attempt < MAX_ATTEMPTS - 1:
            _sleep(retry_after if retry_after is not None else _BACKOFF_SECONDS[attempt])
    raise MachineTranslationError(
        "Azure Translator did not answer"
        + (f" (last status {status})." if status else " (network error).")
    )


def translate_batch(texts: list[str], target: str) -> list[str]:
    """English ``texts`` into ``target``, same order. Raises on any failure."""
    if not is_configured():
        raise NotConfigured("Azure Translator is not configured.")
    cfg = current_app.config
    url = f"{cfg['AZURE_TRANSLATOR_ENDPOINT']}/translate"
    url += f"?api-version=3.0&from=en&to={target}&textType=html"
    headers = {
        "Ocp-Apim-Subscription-Key": cfg["AZURE_TRANSLATOR_KEY"],
        "Ocp-Apim-Subscription-Region": cfg["AZURE_TRANSLATOR_REGION"],
        "Content-Type": "application/json",
    }
    out: list[str] = []
    for chunk in _chunks([mask(t) for t in texts]):
        data = _post(url, headers, [{"Text": t} for t in chunk])
        if not isinstance(data, list) or len(data) != len(chunk):
            raise MachineTranslationError("Azure Translator returned an unexpected answer.")
        try:
            out.extend(unmask(d["translations"][0]["text"]) for d in data)
        except (KeyError, IndexError, TypeError):
            raise MachineTranslationError("Azure Translator returned an unexpected answer.") from None
    return out
