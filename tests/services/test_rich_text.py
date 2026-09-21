"""app/utils/rich_text.py::sanitize_rich_text — the shared rich-text allowlist."""
import unittest

from app.utils.rich_text import sanitize_rich_text


class SanitizeRichTextTests(unittest.TestCase):
    def test_keeps_the_allowed_formatting(self):
        html = (
            "<p><strong>A</strong> <b>B</b> <em>C</em> <i>D</i><br>E</p>"
            "<ul><li>one<ol><li>nested</li></ol></li></ul>"
        )
        self.assertEqual(sanitize_rich_text(html), html)

    def test_drops_script_with_its_content(self):
        cleaned = sanitize_rich_text("<p>ok</p><script>alert(1)</script>")
        self.assertIn("ok", cleaned)
        self.assertNotIn("script", cleaned)
        self.assertNotIn("alert", cleaned)

    def test_drops_event_handlers_styles_classes_and_links(self):
        cleaned = sanitize_rich_text(
            '<p class="note" style="color:red" onclick="x()">t</p>'
            '<a href="javascript:alert(1)">link</a><img src=x onerror="y()">'
            '<li class="ql-indent-1">i</li>'
        )
        self.assertIn("t", cleaned)
        self.assertIn("link", cleaned)  # the text survives, the anchor does not
        for banned in ("class", "style", "onclick", "href", "javascript", "<a", "<img", "onerror"):
            self.assertNotIn(banned, cleaned)

    def test_drops_style_blocks_and_unknown_tags(self):
        cleaned = sanitize_rich_text("<style>p{}</style><h1>Head</h1><table><tr><td>c</td></tr></table>")
        self.assertEqual(cleaned, "Headc")

    def test_blank_and_none_become_empty(self):
        self.assertEqual(sanitize_rich_text(None), "")
        self.assertEqual(sanitize_rich_text("   "), "")

    def test_non_breaking_spaces_become_spaces(self):
        self.assertEqual(sanitize_rich_text("<p>a&nbsp;b\xa0c</p>"), "<p>a b c</p>")

    def test_is_idempotent(self):
        once = sanitize_rich_text('<p onclick="x">a <b>b</p><ul><li>c')
        self.assertEqual(sanitize_rich_text(once), once)
