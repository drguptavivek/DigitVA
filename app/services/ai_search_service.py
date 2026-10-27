"""Typo-tolerant suggestions over help pages, WHO VA definitions, the AI
question catalog and a user's own saved queries.

Policy: docs/policy/ai-analytics-questions.md ("Suggestions"). Typesense
(internal container, plain HTTP API via ``requests``) answers when reachable;
on any error or when unconfigured, an in-process difflib match over the same
documents, built from source, answers instead. Only titles, keywords and
public help/definition text are indexed, never SQL results or submission data.

Every document carries ``roles``: ``["public"]`` (any caller), ``["authenticated"]``
any signed-in user, else the role names of the help registry. A user sees a
document when it shares a role with the roles they hold (resolved with
``app.routes.help._user_has_role``, the filter ``_visible_pages`` uses). A
``saved_query`` document is additionally visible to its owner only.
"""

import difflib
import html
import json
import logging
import os
import re
import time
from pathlib import Path

import requests
import sqlalchemy as sa

from app import db
from app.services import ai_analytics_catalog

log = logging.getLogger(__name__)

COLLECTION = "digitva_search"
# Typesense strips symbols from filter values, so the spec's "*" cannot be
# filtered on; "public" is the same token in a form it can.
PUBLIC = "public"
KINDS = ("help", "va_definition", "catalog", "saved_query")
BODY_MAX = 4096
_TIMEOUT = (0.5, 1)  # connect, read seconds: suggestions must never stall a page
_REPO_ROOT = Path(__file__).resolve().parents[2]
_HELP_TEMPLATES = _REPO_ROOT / "app" / "templates" / "help" / "pages"
VA_DEFINITIONS_URL = "/help/va-definitions"
# The AI questions page (app/routes/ai_questions.py); a test checks it
# against url_for. The page runs ?saved=<id> and ?catalog=<key>.
AI_PAGE_URL = "/data-management/ai-questions"
SAVED_QUERY_URL = AI_PAGE_URL + "?saved={id}"
AI_PAGE_ROLES = ["data_manager"]  # admin passes every role check too
SAVED_QUERY_TABLE = "va_ai_saved_queries"

_FALLBACK_TTL = 60  # seconds a process keeps its source-built documents
_FALLBACK_CUTOFF = 0.8

_SCHEMA = {
    "name": COLLECTION,
    "fields": [
        {"name": "kind", "type": "string", "facet": True},
        {"name": "title", "type": "string"},
        {"name": "body", "type": "string"},
        {"name": "keywords", "type": "string"},
        {"name": "url", "type": "string", "index": False},
        {"name": "roles", "type": "string[]"},
        {"name": "owner_user_id", "type": "string", "optional": True},
    ],
}


# ---------------------------------------------------------------------------
# Typesense transport
# ---------------------------------------------------------------------------

def _config() -> tuple[str, str] | None:
    """(base_url, api_key), or None when Typesense is not configured."""
    host = os.environ.get("TYPESENSE_HOST", "").strip()
    key = os.environ.get("TYPESENSE_API_KEY", "").strip()
    if not host or not key:
        return None
    return f"http://{host}:{os.environ.get('TYPESENSE_PORT', '8108').strip()}", key


def _call(method: str, path: str, **kwargs):
    """One Typesense request; raises ``requests`` errors, never logs the key."""
    config = _config()
    if config is None:
        raise RuntimeError("Typesense is not configured")
    base, key = config
    response = requests.request(
        method, f"{base}{path}", headers={"X-TYPESENSE-API-KEY": key},
        timeout=_TIMEOUT, **kwargs,
    )
    response.raise_for_status()
    return response


def _q(value: str) -> str:
    """A Typesense filter literal; backticks delimit it, so none may appear inside."""
    return "`" + str(value).replace("`", "") + "`"


# ---------------------------------------------------------------------------
# Documents built from source
# ---------------------------------------------------------------------------

def _plain(text: str) -> str:
    """HTML (and Jinja tags) to plain text, capped at ``BODY_MAX``."""
    text = re.sub(r"\{#.*?#\}|\{%.*?%\}|\{\{.*?\}\}", " ", text, flags=re.DOTALL)
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()[:BODY_MAX]


def _help_docs() -> list[dict]:
    from app.routes.help import HELP_PAGES

    docs = []
    for slug, title, _icon, category, roles in HELP_PAGES:
        path = _HELP_TEMPLATES / f"{slug}.html"
        body = _plain(path.read_text(encoding="utf-8")) if path.is_file() else ""
        docs.append({
            "id": f"help:{slug}", "kind": "help", "title": title, "body": body,
            "keywords": category, "url": f"/help/{slug}",
            "roles": [PUBLIC] if roles is None else list(roles),
        })
    return docs


def _definition_docs() -> list[dict]:
    from app.models.mas_va_cause_definitions import MasVaCauseDefinition

    rows = db.session.execute(
        sa.select(
            MasVaCauseDefinition.va_code,
            MasVaCauseDefinition.title,
            MasVaCauseDefinition.definition_html,
        ).where(MasVaCauseDefinition.is_active.is_(True))
    ).all()
    # The page that lists definitions is role-gated; the documents follow it.
    return [
        {
            "id": f"va_definition:{code}", "kind": "va_definition",
            "title": f"{code} {title}", "body": _plain(definition_html or ""),
            "keywords": code, "url": VA_DEFINITIONS_URL,
            "roles": ["coder", "coding_tester", "reviewer", "admin"],
        }
        for code, title, definition_html in rows
    ]


def _catalog_docs() -> list[dict]:
    """Catalog questions (``ai_analytics_catalog.load_catalog``: key,
    question, description, keywords); none until the file exists."""
    docs = []
    for entry in ai_analytics_catalog.load_catalog():
        keywords = entry.get("keywords") or ""
        docs.append({
            "id": f"catalog:{entry['key']}", "kind": "catalog", "title": entry["question"],
            "body": _plain(entry.get("description") or ""),
            "keywords": " ".join(keywords) if isinstance(keywords, list) else str(keywords),
            "url": f"{AI_PAGE_URL}?catalog={entry['key']}",
            "roles": AI_PAGE_ROLES,
        })
    return docs


def _saved_query_doc(id, owner_user_id, title, keywords="") -> dict:
    return {
        "id": f"saved_query:{id}", "kind": "saved_query", "title": title,
        "body": "", "keywords": keywords if isinstance(keywords, str) else " ".join(keywords),
        "url": SAVED_QUERY_URL.format(id=id), "roles": AI_PAGE_ROLES,
        "owner_user_id": str(owner_user_id),
    }


def _saved_query_docs():
    """Every saved query as a document, read in batches (titles and
    descriptions only)."""
    from app.models.va_ai_analytics import VaAiSavedQuery

    rows = db.session.execute(
        sa.select(
            VaAiSavedQuery.id, VaAiSavedQuery.owner_user_id,
            VaAiSavedQuery.title, VaAiSavedQuery.description,
        ).order_by(VaAiSavedQuery.id).execution_options(yield_per=500)
    )
    for row_id, owner, title, description in rows:
        yield _saved_query_doc(row_id, owner, title, description or "")


def _source_docs() -> list[dict]:
    return _help_docs() + _definition_docs() + _catalog_docs()


# ---------------------------------------------------------------------------
# Index maintenance
# ---------------------------------------------------------------------------

def _ensure_collection() -> None:
    try:
        _call("GET", f"/collections/{COLLECTION}")
    except requests.HTTPError as exc:
        if exc.response is None or exc.response.status_code != 404:
            raise
        _call("POST", "/collections", json=_SCHEMA)
        # ponytail: a schema change needs the collection dropped by hand;
        # add a version check here if the schema starts to move.


def _import(docs: list[dict]) -> None:
    if not docs:
        return
    payload = "\n".join(json.dumps(d) for d in docs)
    response = _call(
        "POST", f"/collections/{COLLECTION}/documents/import",
        params={"action": "upsert"}, data=payload.encode("utf-8"),
    )
    failed = [json.loads(line) for line in response.text.splitlines() if line]
    failed = [r for r in failed if not r.get("success")]
    if failed:
        raise RuntimeError(f"Typesense rejected {len(failed)} documents")


def reindex_all() -> int:
    """Upsert help, definition, catalog and every saved-query document, then
    drop documents that no longer exist (deleted saved queries included).

    Saved queries are also written one by one on save and delete
    (``upsert_saved_query``, ``delete_saved_query``). Returns the number of
    documents indexed; raises when Typesense is unconfigured or unreachable
    (the CLI reports it).
    """
    docs = _source_docs()
    _ensure_collection()
    _import(docs)
    ids = [d["id"] for d in docs]
    batch = []
    for doc in _saved_query_docs():
        batch.append(doc)
        if len(batch) == 500:
            _import(batch)
            ids += [d["id"] for d in batch]
            batch = []
    _import(batch)
    ids += [d["id"] for d in batch]
    # ponytail: one filter listing every id; split it if the URL grows past
    # Typesense's limit (thousands of saved queries).
    _call(
        "DELETE", f"/collections/{COLLECTION}/documents",
        params={"filter_by": f"id:!=[{','.join(_q(i) for i in ids)}]"},
    )
    clear_fallback_cache()
    return len(docs)


def upsert_saved_query(id, owner_user_id, title, keywords="") -> None:
    """Index one saved query for its owner. Best effort: a down index must not
    fail the save, and the fallback reads the table directly. Nothing to do
    while Typesense is not configured."""
    if _config() is None:
        return
    doc = _saved_query_doc(id, owner_user_id, title, keywords)
    try:
        _ensure_collection()
        _import([doc])
    except Exception:  # noqa: BLE001 - suggestions are optional
        log.warning("Could not index saved query %s", id, exc_info=True)


def delete_saved_query(id) -> None:
    """Remove one saved query from the index (best effort, as above)."""
    if _config() is None:
        return
    try:
        doc_id = requests.utils.quote(f"saved_query:{id}", safe="")
        _call("DELETE", f"/collections/{COLLECTION}/documents/{doc_id}")
    except requests.HTTPError as exc:
        if exc.response is None or exc.response.status_code != 404:
            log.warning("Could not remove saved query %s from the index", id, exc_info=True)
    except Exception:  # noqa: BLE001
        log.warning("Could not remove saved query %s from the index", id, exc_info=True)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def _user_roles(user) -> list[str]:
    """Every role token the user holds, plus ``public`` and (signed in) ``authenticated``.

    Asks ``_user_has_role`` about each token the registry uses, so admin
    and the ``is_<role>`` methods resolve exactly as for the Help sidebar.
    """
    from app.routes.help import HELP_PAGES, _user_has_role

    tokens = {r for page in HELP_PAGES for r in (page[4] or []) if r != "authenticated"}
    tokens |= {"coder", "coding_tester", "reviewer", "admin"}
    held = {r for r in tokens if _user_has_role(user, [r])}
    held.add(PUBLIC)
    if getattr(user, "is_authenticated", False):
        held.add("authenticated")
    return sorted(held)


def _owner_id(user) -> str:
    return str(getattr(user, "user_id", "") or "")


def _snippet(body: str) -> str:
    return body[:160] + ("..." if len(body) > 160 else "")


def _result(doc: dict) -> dict:
    return {
        "kind": doc["kind"], "title": doc["title"], "url": doc["url"],
        "snippet": _snippet(doc.get("body") or ""),
    }


def _typesense_search(user, q: str, limit: int) -> list[dict]:
    roles = ",".join(_q(r) for r in _user_roles(user))
    filter_by = f"roles:=[{roles}]"
    owner = _owner_id(user)
    filter_by += (
        f" && (kind:!=saved_query || owner_user_id:={_q(owner)})" if owner
        else " && kind:!=saved_query"
    )
    response = _call(
        "GET", f"/collections/{COLLECTION}/documents/search",
        params={
            "q": q, "query_by": "title,keywords,body", "num_typos": 2, "prefix": "true",
            "filter_by": filter_by, "per_page": limit,
            "include_fields": "kind,title,url,body",
        },
    )
    return [_result(hit["document"]) for hit in response.json().get("hits", [])]


_cache: dict = {"at": 0.0, "docs": None}


def clear_fallback_cache() -> None:
    _cache.update(at=0.0, docs=None)


def _fallback_docs() -> list[dict]:
    """Source documents with their match words, rebuilt after ``_FALLBACK_TTL``."""
    now = time.monotonic()
    if _cache["docs"] is None or now - _cache["at"] > _FALLBACK_TTL:
        docs = _source_docs()
        for doc in docs:
            doc["_fields"] = tuple(
                (weight, sorted(set(re.findall(r"[a-z0-9]{3,}", doc[name].lower()))))
                for name, weight in (("title", 3), ("keywords", 2), ("body", 1))
            )
        _cache.update(at=now, docs=docs)
    return _cache["docs"]


def _fallback_score(tokens: list[str], doc: dict) -> float:
    total = 0.0
    for token in tokens:
        best = 0.0
        for weight, words in doc["_fields"]:
            if any(w.startswith(token) for w in words):
                best = max(best, weight)
            elif len(token) >= 4 and difflib.get_close_matches(token, words, 1, _FALLBACK_CUTOFF):
                best = max(best, weight * 0.9)
        if not best:
            return 0.0  # every word of the query must match somewhere
        total += best
    return total


def _saved_query_fallback(user, q: str, limit: int) -> list[dict]:
    """The user's own saved queries by ``pg_trgm`` word similarity, only when
    phase 1's table exists. Never raises."""
    owner = _owner_id(user)
    if not owner:
        return []
    try:
        with db.session.begin_nested():
            if db.session.execute(
                sa.text("SELECT to_regclass(:name)"), {"name": SAVED_QUERY_TABLE}
            ).scalar() is None:
                return []
            rows = db.session.execute(
                sa.text(
                    f"SELECT id, title FROM {SAVED_QUERY_TABLE} "  # fixed constant, not input
                    "WHERE owner_user_id = :owner AND word_similarity(:q, title) > 0.3 "
                    "ORDER BY word_similarity(:q, title) DESC LIMIT :limit"
                ),
                {"owner": owner, "q": q, "limit": limit},
            ).all()
    except Exception:  # noqa: BLE001 - pg_trgm may be absent; suggestions are optional
        log.warning("Saved-query suggestion fallback failed", exc_info=True)
        return []
    return [
        {"kind": "saved_query", "title": title, "url": SAVED_QUERY_URL.format(id=row_id), "snippet": ""}
        for row_id, title in rows
    ]


def _fallback_search(user, q: str, limit: int) -> list[dict]:
    allowed = set(_user_roles(user))
    tokens = re.findall(r"[a-z0-9]+", q.lower())
    if not tokens:
        return []
    scored = []
    for doc in _fallback_docs():
        if not allowed.intersection(doc["roles"]):
            continue
        score = _fallback_score(tokens, doc)
        if score:
            scored.append((score, doc))
    scored.sort(key=lambda pair: -pair[0])
    results = [_result(doc) for _, doc in scored[:limit]]
    return (_saved_query_fallback(user, q, limit) + results)[:limit]


def search(user, q: str, limit: int = 8) -> list[dict]:
    """Suggestions for *user* matching *q*: dicts of kind, title, url, snippet.

    Typesense first; any failure (or no configuration) falls back to the
    in-process match, which applies the same role filter.
    """
    q = (q or "").strip()[:100]
    limit = max(1, min(int(limit), 20))
    if len(q) < 2:
        return []
    if _config() is not None:
        try:
            return _typesense_search(user, q, limit)
        except Exception as exc:  # noqa: BLE001 - never fail a page over suggestions
            log.warning("Typesense search failed, using fallback: %s", type(exc).__name__)
    return _fallback_search(user, q, limit)
