"""Server-side allowlist for admin-edited rich text.

Pairs with the shared editor app/static/js/rich_text_editor.js, whose toolbar
(bold, italic, bullet list, numbered list, indent, outdent) produces only what
this allowlist keeps; indent is saved as nested lists, so no class or style
attribute is needed. Policy: docs/policy/va-cause-definitions.md ("Rich text").
"""

import nh3

RICH_TEXT_TAGS = frozenset({"p", "br", "ul", "ol", "li", "strong", "b", "em", "i"})


def sanitize_rich_text(html: str | None) -> str:
    """Return ``html`` reduced to the rich-text allowlist.

    Every attribute, link, style and unknown tag is dropped; <script> and
    <style> lose their content too (nh3 default). Non-breaking spaces become
    plain spaces, because the editor emits them between words and they would
    otherwise defeat text search. Idempotent: sanitizing stored output again
    returns it unchanged. ``None`` or blank input returns "".
    """
    if not html or not html.strip():
        return ""
    cleaned = nh3.clean(
        html,
        tags=set(RICH_TEXT_TAGS),
        attributes={},
        url_schemes=set(),
        link_rel=None,
        strip_comments=True,
    )
    return cleaned.replace("&nbsp;", " ").replace("\xa0", " ").strip()
