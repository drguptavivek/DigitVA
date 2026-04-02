import tempfile
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app import create_app
from app.utils.va_odk.va_odk_05_deltacheck import va_odk_delta_count
from app.utils.va_odk.va_odk_06_fetchsubmissions import va_odk_fetch_submissions
from app.utils.va_odk.va_odk_07_syncattachments import (
    va_odk_sync_form_attachments,
    va_odk_sync_submission_attachments,
)
from config import TestConfig


class _FakeResponse:
    def __init__(self, *, status_code=200, json_data=None, text="", headers=None, content=b""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self.headers = headers or {}
        self.content = content
        self.closed = False

    def json(self):
        return self._json_data

    def iter_content(self, chunk_size=1):
        for index in range(0, len(self.content), chunk_size):
            yield self.content[index:index + chunk_size]

    def close(self):
        self.closed = True


class _FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self._responses:
            raise AssertionError(f"No fake response configured for {url}")
        return self._responses.pop(0)


class TestOdkClientReuse(TestCase):
    def test_delta_count_uses_injected_client(self):
        fake_client = SimpleNamespace(
            session=_FakeSession(
                [_FakeResponse(json_data={"@odata.count": 3})]
            )
        )

        with patch(
            "app.utils.va_odk.va_odk_05_deltacheck.va_odk_clientsetup",
            side_effect=AssertionError("clientsetup should not be called"),
        ):
            count = va_odk_delta_count(
                odk_project_id=11,
                odk_form_id="FORM_A",
                since=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                app_project_id="PROJ01",
                client=fake_client,
            )

        self.assertEqual(count, 3)
        self.assertEqual(len(fake_client.session.calls), 1)

    def test_fetch_submissions_uses_injected_client(self):
        fake_client = SimpleNamespace(
            session=_FakeSession(
                [
                    _FakeResponse(
                        json_data={
                            "value": [
                                {
                                    "__id": "uuid:abc",
                                    "__system": {
                                        "submissionDate": "2026-03-14T00:00:00.000Z",
                                        "updatedAt": "2026-03-14T00:00:00.000Z",
                                        "submitterName": "tester",
                                        "reviewState": None,
                                    },
                                    "meta": {"instanceName": "instance-1"},
                                }
                            ]
                        }
                    )
                ]
            )
        )
        va_form = SimpleNamespace(
            project_id="PROJ01",
            odk_project_id="11",
            odk_form_id="FORM_A",
            form_id="FORM01",
        )

        with patch(
            "app.utils.va_odk.va_odk_06_fetchsubmissions.va_odk_clientsetup",
            side_effect=AssertionError("clientsetup should not be called"),
        ):
            rows = va_odk_fetch_submissions(va_form, client=fake_client)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["KEY"], "uuid:abc")
        self.assertEqual(len(fake_client.session.calls), 1)

    def test_attachment_sync_uses_injected_client(self):
        app = create_app(TestConfig)
        download_response = _FakeResponse(
            headers={"ETag": "abc123", "Content-Type": "text/plain"},
            content=b"hello",
        )
        fake_client = SimpleNamespace(
            session=_FakeSession(
                [
                    _FakeResponse(json_data=[{"name": "note.txt", "exists": True}]),
                    download_response,
                ]
            )
        )
        va_form = SimpleNamespace(
            project_id="PROJ01",
            odk_project_id="11",
            odk_form_id="FORM_A",
        )

        with tempfile.TemporaryDirectory() as media_dir, patch(
            "app.utils.va_odk.va_odk_01_clientsetup.va_odk_clientsetup",
            side_effect=AssertionError("clientsetup should not be called"),
        ), patch(
            "app.db"
        ) as mock_db:
            with app.app_context():
                mock_db.session.scalars.return_value.all.return_value = []
                mock_db.session.flush.return_value = None

                result = va_odk_sync_submission_attachments(
                    va_form,
                    instance_id="uuid:abc",
                    va_sid="uuid:abc-form01",
                    media_dir=media_dir,
                    client=fake_client,
                )

        self.assertEqual(result["downloaded"], 1)
        self.assertEqual(len(fake_client.session.calls), 2)
        _, list_kwargs = fake_client.session.calls[0]
        self.assertEqual(list_kwargs["timeout"], (1.0, 5.0))
        _, download_kwargs = fake_client.session.calls[1]
        self.assertTrue(download_kwargs["stream"])
        self.assertEqual(download_kwargs["timeout"], (1.0, 5.0))
        self.assertTrue(download_response.closed)

    def test_form_attachment_sync_uses_client_factory_and_aggregates_results(self):
        app = create_app(TestConfig)
        fake_client = SimpleNamespace(
            session=_FakeSession(
                [
                    _FakeResponse(json_data=[{"name": "one.txt", "exists": True}]),
                    _FakeResponse(
                        headers={"ETag": "etag-one", "Content-Type": "text/plain"},
                        content=b"one",
                    ),
                    _FakeResponse(json_data=[{"name": "two.txt", "exists": True}]),
                    _FakeResponse(
                        headers={"ETag": "etag-two", "Content-Type": "text/plain"},
                        content=b"two",
                    ),
                ]
            )
        )
        va_form = SimpleNamespace(
            project_id="PROJ01",
            odk_project_id="11",
            odk_form_id="FORM_A",
        )
        client_factory_calls = 0

        def client_factory():
            nonlocal client_factory_calls
            client_factory_calls += 1
            return fake_client

        with tempfile.TemporaryDirectory() as media_dir, patch("app.db") as mock_db:
            with app.app_context():
                mock_db.session.scalars.return_value.all.return_value = []
                mock_db.session.flush.return_value = None
                mock_db.session.add.return_value = None

                result = va_odk_sync_form_attachments(
                    va_form,
                    {
                        "uuid:one-form01": "uuid:one",
                        "uuid:two-form01": "uuid:two",
                    },
                    media_dir,
                    client_factory=client_factory,
                    max_workers=1,
                )

        self.assertEqual(result["downloaded"], 2)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(result["errors"], 0)
        self.assertEqual(client_factory_calls, 1)
        self.assertEqual(len(fake_client.session.calls), 4)

    def test_attachment_sync_skips_unchanged_files_with_streamed_request(self):
        app = create_app(TestConfig)
        not_modified_response = _FakeResponse(status_code=304)
        fake_client = SimpleNamespace(
            session=_FakeSession(
                [
                    _FakeResponse(json_data=[{"name": "note.txt", "exists": True}]),
                    not_modified_response,
                ]
            )
        )
        va_form = SimpleNamespace(
            project_id="PROJ01",
            odk_project_id="11",
            odk_form_id="FORM_A",
        )

        with tempfile.TemporaryDirectory() as media_dir, patch("app.db") as mock_db:
            with app.app_context():
                existing = SimpleNamespace(filename="note.txt", etag='"etag-old"')
                mock_db.session.scalars.return_value.all.return_value = [existing]
                mock_db.session.flush.return_value = None

                result = va_odk_sync_submission_attachments(
                    va_form,
                    instance_id="uuid:abc",
                    va_sid="uuid:abc-form01",
                    media_dir=media_dir,
                    client=fake_client,
                )

        self.assertEqual(result["downloaded"], 0)
        self.assertEqual(result["skipped"], 1)
        _, download_kwargs = fake_client.session.calls[1]
        self.assertEqual(download_kwargs["headers"]["If-None-Match"], '"etag-old"')
        self.assertTrue(download_kwargs["stream"])
        self.assertTrue(not_modified_response.closed)
