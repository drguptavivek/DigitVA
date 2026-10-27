"""Public contact form with email confirmation (docs/policy/
public-privacy-and-data-requests.md section 7, digitva-gyfj.1)."""
import re
from unittest.mock import patch

from app import cache, limiter
from app.services import contact_form_service
from app.services.pow_captcha_service import issue_challenge
from tests.base import BaseTestCase

CONTACT = "/contact"
CONTACT_EMAIL = "privacy@example.org"
MESSAGE = "Please delete the record for case 1234, written by a unique sender."


class PublicContactFormTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        limiter.reset()  # in-memory buckets outlive a test; POST allows 5 a minute
        config = patch.dict(self.app.config, PUBLIC_CONTACT_EMAIL=CONTACT_EMAIL, PUBLIC_BASE_URL="https://va.example.org")
        config.start()
        self.addCleanup(config.stop)
        dispatch = patch("app.services.email_service._dispatch_email")
        self.dispatch = dispatch.start()
        self.addCleanup(dispatch.stop)
        deliverable = patch("app.services.email_service._should_attempt_email_delivery", return_value=True)
        deliverable.start()
        self.addCleanup(deliverable.stop)

    def _slide_id(self, body):
        return re.search(r'name="slide_id" type="hidden" value="([^"]+)"', body).group(1)

    def _form(self, sender="sender@example.org", **overrides):
        body = self.client.get(CONTACT).get_data(as_text=True)
        slide_id = self._slide_id(body)
        challenge = issue_challenge()
        data = {
            "name": "A Sender",
            "email": sender,
            "topic": "deletion",
            "message": MESSAGE,
            "website": "",
            "captcha_salt": challenge["salt"],
            "captcha_difficulty": challenge["difficulty"],
            "captcha_expires": challenge["expires"],
            "captcha_signature": challenge["signature"],
            "captcha_solution": self._solve_pow_captcha(challenge["salt"], challenge["difficulty"]),
            "slide_id": slide_id,
            "slide_x": cache.get(f"slide_captcha:{slide_id}"),
            "slide_ms": 900,
            "slide_moves": 14,
        }
        data.update(overrides)
        return data

    def _post(self, data, csrf=True, ip="127.0.0.1"):
        return self.client.post(
            CONTACT, data=data, headers=self._csrf_headers() if csrf else {},
            environ_overrides={"REMOTE_ADDR": ip},
        )

    def _submit(self, sender="sender@example.org"):
        """A valid submission; returns the token from the queued confirmation link."""
        response = self._post(self._form(sender))
        self.assertIn("a confirmation link is on its way", response.get_data(as_text=True))
        kwargs = self.dispatch.delay.call_args.kwargs
        url = kwargs["context"]["confirm_url"]
        self.assertTrue(url.startswith("https://va.example.org/contact/confirm/"))
        return url.rsplit("/", 1)[1]

    def test_form_renders_with_puzzle_and_no_store(self):
        response = self.client.get(CONTACT + "?topic=deletion")
        body = response.get_data(as_text=True)
        self.assertIn('id="slide-captcha-range"', body)
        self.assertIn('<option selected value="deletion">', body)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        slide_id = self._slide_id(body)
        target = cache.get(f"slide_captcha:{slide_id}")
        self.assertIsNotNone(target)
        for field in ("slide_x", "slide_ms", "slide_moves"):
            self.assertIn(f'name="{field}" type="hidden" value=""', body)

    def test_unknown_topic_param_falls_back_to_general(self):
        body = self.client.get(CONTACT + "?topic=<script>").get_data(as_text=True)
        self.assertIn('<option selected value="general">', body)
        self.assertNotIn("<script>", body.split("<body", 1)[1].split('<script src', 1)[0])

    def test_contact_email_unset_hides_form_and_refuses_post(self):
        with patch.dict(self.app.config, PUBLIC_CONTACT_EMAIL=""):
            body = self.client.get(CONTACT).get_data(as_text=True)
            self.assertIn("Contact us", body)
            self.assertNotIn('id="slide-captcha-range"', body)
            response = self._post({"name": "A", "email": "a@example.org", "message": "hi"})
        self.assertIn("contact form is not available", response.get_data(as_text=True))
        self.dispatch.delay.assert_not_called()

    def test_valid_submission_sends_link_with_token_only(self):
        token = self._submit()
        self.assertEqual(len(token), 43)
        kwargs = self.dispatch.delay.call_args.kwargs
        self.assertEqual(kwargs["to"], "sender@example.org")
        self.assertEqual(kwargs["template_name"], "emails/contact_confirm")
        self.assertEqual(set(kwargs["context"]), {"confirm_url"})
        self.assertNotIn(MESSAGE, repr(self.dispatch.delay.call_args))
        self.assertNotIn("sender", kwargs["context"]["confirm_url"])
        self.assertTrue(contact_form_service.is_pending(token))

    def test_logs_carry_no_message_or_address(self):
        with self.assertLogs("app.services.contact_form_service", level="INFO") as logs:
            self._submit("logged@example.org")
        joined = "\n".join(logs.output)
        self.assertIn("event=submitted topic=deletion", joined)
        self.assertNotIn("logged@example.org", joined)
        self.assertNotIn(MESSAGE, joined)

    def test_honeypot_gets_neutral_reply_and_nothing_stored_or_sent(self):
        with patch.object(contact_form_service, "start") as start:
            response = self._post(self._form(website="http://spam.example"))
        self.assertIn("a confirmation link is on its way", response.get_data(as_text=True))
        start.assert_not_called()
        self.dispatch.delay.assert_not_called()

    def test_missing_or_wrong_captcha_is_refused(self):
        for overrides in ({"slide_id": ""}, {"captcha_solution": ""}, {"slide_x": 0}, {"captcha_signature": "0" * 64}):
            with self.subTest(overrides=overrides):
                body = self._post(self._form(**overrides)).get_data(as_text=True)
                self.assertNotIn("a confirmation link is on its way", body)
                self.assertIn('id="slide-captcha-range"', body)
                self.assertIn(MESSAGE, body)  # the message survives the retry
        self.dispatch.delay.assert_not_called()

    def test_csrf_required(self):
        response = self._post(self._form(), csrf=False)
        self.assertEqual(response.status_code, 400)
        self.dispatch.delay.assert_not_called()

    def test_message_length_capped(self):
        body = self._post(self._form(message="x" * 4001)).get_data(as_text=True)
        self.assertIn("under 4000 characters", body)
        self.dispatch.delay.assert_not_called()

    def test_get_confirm_does_not_deliver_post_delivers_once(self):
        token = self._submit()
        self.dispatch.reset_mock()
        url = f"/contact/confirm/{token}"

        page = self.client.get(url)
        self.assertIn("Send my message", page.get_data(as_text=True))
        self.assertEqual(page.headers["Cache-Control"], "no-store")
        self.assertEqual(page.headers["Referrer-Policy"], "strict-origin-when-cross-origin")
        self.dispatch.delay.assert_not_called()

        sent = self.client.post(url, headers=self._csrf_headers()).get_data(as_text=True)
        self.assertIn("Your message has been sent", sent)
        self.dispatch.delay.assert_called_once()
        kwargs = self.dispatch.delay.call_args.kwargs
        self.assertEqual(kwargs["to"], CONTACT_EMAIL)
        self.assertEqual(kwargs["reply_to"], "sender@example.org")
        self.assertEqual(kwargs["context"]["message"], MESSAGE)
        self.assertEqual(kwargs["subject"], "DigitVA contact form: Data deletion request")

        again = self.client.post(url, headers=self._csrf_headers()).get_data(as_text=True)
        self.assertIn("no longer valid", again)
        self.dispatch.delay.assert_called_once()
        self.assertIn("no longer valid", self.client.get(url).get_data(as_text=True))

    def test_confirm_post_requires_csrf(self):
        token = self._submit()
        self.dispatch.reset_mock()
        self.assertEqual(self.client.post(f"/contact/confirm/{token}").status_code, 400)
        self.dispatch.delay.assert_not_called()
        self.assertTrue(contact_form_service.is_pending(token))

    def test_expired_or_unknown_token_is_neutral(self):
        token = self._submit()
        self.dispatch.reset_mock()
        with patch.object(cache, "get", return_value=None):
            body = self.client.post(f"/contact/confirm/{token}", headers=self._csrf_headers()).get_data(as_text=True)
        self.assertIn("no longer valid", body)
        for bad in ("x" * 43, "short", "a" * 200):
            body = self.client.post(f"/contact/confirm/{bad}", headers=self._csrf_headers()).get_data(as_text=True)
            self.assertIn("no longer valid", body)
        self.dispatch.delay.assert_not_called()

    def test_pending_entry_kept_24_hours_under_hashed_key(self):
        with patch.object(cache, "set", wraps=cache.set) as cache_set:
            token = self._submit()
        pending_calls = [c for c in cache_set.call_args_list if c.args[0].startswith("contact_pending:")]
        self.assertEqual(len(pending_calls), 1)
        self.assertEqual(pending_calls[0].kwargs["timeout"], 24 * 60 * 60)
        self.assertNotIn(token, pending_calls[0].args[0])

    def test_per_sender_cap_counts_sent_confirmations_only(self):
        sender = "capped@example.org"
        # Each POST from its own address, so only the per-sender cap applies.
        for n in range(2):  # refused submissions do not count
            body = self._post(self._form(sender, captcha_signature="0" * 64), ip=f"10.0.0.{n}").get_data(as_text=True)
            self.assertIn('id="slide-captcha-range"', body)
        for n in range(3):
            self.assertIn("a confirmation link is on its way",
                          self._post(self._form(sender), ip=f"10.0.1.{n}").get_data(as_text=True))
        # A fourth confirmation within the hour is refused; the app answers
        # the limiter's 429 with a flash and a redirect.
        response = self._post(self._form(sender), ip="10.0.2.1")
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertIn("Too many requests", str(sess.get("_flashes")))
        self.assertEqual(self.dispatch.delay.call_count, 3)

    def test_per_address_limit(self):
        for n in range(5):
            self.assertEqual(self._post(self._form(f"s{n}@example.org", captcha_signature="0" * 64)).status_code, 200)
        self.assertEqual(self._post(self._form("s9@example.org")).status_code, 302)
        self.dispatch.delay.assert_not_called()

    def test_delivered_email_sets_reply_to_and_escapes_message(self):
        from app.services.email_service import _actually_send_email

        with patch("app.services.email_service.is_mail_configured", return_value=True), \
                patch("app.services.email_service.mail.send") as send:
            _actually_send_email(
                CONTACT_EMAIL, "DigitVA contact form: General question", "emails/contact_message",
                {"name": "A <b>Sender</b>", "email": "sender@example.org", "topic_label": "General question",
                 "message": "<script>x</script>"},
                reply_to="sender@example.org",
            )
        msg = send.call_args.args[0]
        self.assertEqual(msg.reply_to, "sender@example.org")
        self.assertEqual(msg.recipients, [CONTACT_EMAIL])
        self.assertIn("&lt;script&gt;x&lt;/script&gt;", msg.html)
        self.assertNotIn("<script>x", msg.html)
        self.assertIn("<script>x</script>", msg.body)  # plain text part, not HTML
