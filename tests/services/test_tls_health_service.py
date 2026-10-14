"""TLS certificate expiry checks. Certificates are generated in the test; the
network is either absent (not_configured) or mocked. Nothing here dials a host."""

import os
import ssl
import struct
import tempfile
from datetime import UTC, datetime, timedelta
from unittest import TestCase, mock

from botocore.exceptions import ClientError, ConnectTimeoutError, EndpointConnectionError
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from moto import mock_aws

from app.services import attachment_store as store_mod
from app.services import tls_health_service as svc
from tests.base import BaseTestCase
from tests.services.test_attachment_store import make_s3_app


def make_cert(cn, not_after, sans=()):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    builder = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(days=1))
        .not_valid_after(not_after)
    )
    if sans:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName(s) for s in sans]), critical=False
        )
    return builder.sign(key, hashes.SHA256())


def pem(*certs):
    return b"".join(c.public_bytes(serialization.Encoding.PEM) for c in certs)


def days_from_now(days):
    # Half a day of slack keeps the floor-division day count stable.
    return datetime.now(UTC) + timedelta(days=days, hours=12)


class StatusThresholdTests(BaseTestCase):
    def test_boundaries_at_the_default_thresholds(self):
        cases = {31: "ok", 30: "due", 8: "due", 7: "urgent", 0: "urgent", -1: "expired"}
        for days_left, status in cases.items():
            with self.subTest(days_left=days_left):
                self.assertEqual(svc.status_for_days(days_left, 30, 7), status)

    def test_cert_row_counts_whole_days_left(self):
        ctx = svc._Context(now=datetime.now(UTC), warn_days=30, urgent_days=7)
        cert = make_cert("app.test.invalid", ctx.now + timedelta(days=30, hours=1))

        row = svc._cert_row("app_https", "App", "/x.crt", cert, ctx)

        self.assertEqual(row["days_left"], 30)
        self.assertEqual(row["status"], "due")
        self.assertEqual(row["subject_cn"], "app.test.invalid")

    def test_needs_attention_only_for_due_urgent_expired_and_error(self):
        for status in ("due", "urgent", "expired", "error"):
            self.assertTrue(svc.needs_attention([{"status": status}]), status)
        for status in ("ok", "not_configured", "unreachable"):
            self.assertFalse(svc.needs_attention([{"status": status}]), status)


class ReportWithoutCertificatesTests(BaseTestCase):
    def test_missing_app_certificate_is_not_configured(self):
        with mock.patch.dict(
            self.app.config,
            {"APP_TLS_CERT_FILE": "/nonexistent/server.crt", "PUBLIC_BASE_URL": ""},
        ):
            rows = {r["key"]: r for r in svc.certificate_report()}

        self.assertEqual(rows["app_https"]["status"], "not_configured")
        self.assertIsNone(rows["app_https"]["not_after"])

    def test_database_without_verifying_sslmode_is_not_configured_and_never_dialled(self):
        url = "postgresql://user:secret@10.0.0.5:5432/minerva?sslmode=require"
        with (
            # No public probe either: only the database probe may dial here.
            mock.patch.dict(self.app.config, {"SQLALCHEMY_DATABASE_URI": url, "PUBLIC_BASE_URL": ""}),
            mock.patch.object(svc.socket, "create_connection") as dial,
        ):
            rows = {r["key"]: r for r in svc.certificate_report()}

        self.assertEqual(rows["db_presented"]["status"], "not_configured")
        self.assertEqual(rows["db_trust_1"]["status"], "not_configured")
        dial.assert_not_called()
        self.assertNotIn("secret", repr(rows))

    def test_no_public_base_url_is_not_configured(self):
        with mock.patch.dict(self.app.config, {"PUBLIC_BASE_URL": ""}):
            rows = {r["key"]: r for r in svc.certificate_report()}

        self.assertEqual(rows["public_https"]["status"], "not_configured")


class DatabaseCertificateTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = svc._Context(now=datetime.now(UTC), warn_days=30, urgent_days=7)
        self.presented = make_cert("db.test.invalid", days_from_now(100), sans=["db.test.invalid"])

    def _bundle(self, *certs):
        path = os.path.join(self.tmp.name, "ca.crt")
        with open(path, "wb") as fh:
            fh.write(pem(*certs))
        return path

    def _url(self, path):
        return (
            "postgresql://user:pw@db.test.invalid:5432/minerva"
            f"?sslmode=verify-full&sslrootcert={path}"
        )

    def _report(self, bundle_path, presented):
        url = self._url(bundle_path)
        with (
            mock.patch.dict(self.app.config, {"SQLALCHEMY_DATABASE_URI": url}),
            mock.patch.object(svc, "_presented_certificate", return_value=(presented, None)),
        ):
            return {r["key"]: r for r in svc._database_rows(self.ctx)}

    def test_multi_cert_bundle_gets_one_row_per_cert_and_notes_rotation(self):
        other = make_cert("old-ca.test.invalid", days_from_now(3))
        bundle = self._bundle(other, self.presented)

        rows = self._report(bundle, self.presented)

        self.assertIn("db_trust_1", rows)
        self.assertIn("db_trust_2", rows)
        self.assertEqual(rows["db_trust_1"]["subject_cn"], "old-ca.test.invalid")
        self.assertEqual(rows["db_trust_1"]["status"], "urgent")
        self.assertIn("rotation in progress", rows["db_trust_1"]["label"])
        self.assertEqual(rows["db_presented"]["status"], "ok")

    def test_single_cert_bundle_has_no_rotation_note(self):
        rows = self._report(self._bundle(self.presented), self.presented)

        self.assertEqual(rows["db_presented"]["status"], "ok")
        self.assertNotIn("rotation", rows["db_trust_1"]["label"])

    def test_presented_cert_missing_from_bundle_is_an_error(self):
        stranger = make_cert("stranger.test.invalid", days_from_now(100))
        bundle = self._bundle(self.presented)

        rows = self._report(bundle, stranger)

        self.assertEqual(rows["db_presented"]["status"], "error")
        self.assertEqual(
            rows["db_presented"]["detail"],
            "presented certificate is not in the trust bundle",
        )

    def test_unreachable_database_is_reported_without_raising(self):
        url = self._url(self._bundle(self.presented))
        with (
            mock.patch.dict(self.app.config, {"SQLALCHEMY_DATABASE_URI": url}),
            mock.patch.object(svc.socket, "create_connection", side_effect=OSError("refused")),
        ):
            rows = {r["key"]: r for r in svc._database_rows(self.ctx)}

        self.assertEqual(rows["db_presented"]["status"], "unreachable")
        self.assertEqual(rows["db_presented"]["detail"], "connection failed")
        self.assertNotIn("refused", repr(rows))

    def test_sends_only_the_ssl_request_before_the_tls_handshake(self):
        sock = mock.MagicMock()
        sock.recv.return_value = b"S"
        sock.__enter__.return_value = sock
        tls = mock.MagicMock()
        tls.getpeercert.return_value = self.presented.public_bytes(serialization.Encoding.DER)
        wrapped = mock.MagicMock()
        wrapped.__enter__.return_value = tls
        context = mock.MagicMock()
        context.wrap_socket.return_value = wrapped

        with (
            mock.patch.object(svc.socket, "create_connection", return_value=sock),
            mock.patch.object(svc.ssl, "create_default_context", return_value=context),
        ):
            cert, failure = svc._presented_certificate("db.test.invalid", 5432)

        self.assertIsNone(failure)
        self.assertEqual(cert.subject, self.presented.subject)
        sock.sendall.assert_called_once_with(svc.SSL_REQUEST)
        self.assertEqual(svc.SSL_REQUEST, struct.pack("!ii", 8, 80877103))
        # The SSL request must be the only thing written before the handshake.
        self.assertEqual(sock.sendall.call_count, 1)
        context.wrap_socket.assert_called_once()
        self.assertEqual(context.verify_mode, ssl.CERT_NONE)
        self.assertFalse(context.check_hostname)

    def test_server_refusing_ssl_is_an_error(self):
        sock = mock.MagicMock()
        sock.recv.return_value = b"N"
        sock.__enter__.return_value = sock

        with mock.patch.object(svc.socket, "create_connection", return_value=sock):
            cert, failure = svc._presented_certificate("db.test.invalid", 5432)

        self.assertIsNone(cert)
        self.assertEqual(failure, ("error", "server does not offer TLS"))


class PublicCertificateTests(BaseTestCase):
    def test_verification_failure_is_an_error_with_a_fixed_phrase(self):
        ctx = svc._Context(now=datetime.now(UTC), warn_days=30, urgent_days=7)
        sock = mock.MagicMock()
        sock.__enter__.return_value = sock
        verifying = mock.MagicMock()
        verifying.__enter__.side_effect = ssl.SSLCertVerificationError("unable to get issuer")

        with (
            mock.patch.dict(self.app.config, {"PUBLIC_BASE_URL": "https://digitva.test.invalid"}),
            mock.patch.object(svc.socket, "create_connection", return_value=sock),
            mock.patch.object(svc.ssl, "create_default_context") as make_ctx,
        ):
            make_ctx.return_value.wrap_socket.return_value = verifying
            row = svc._public_https_row(ctx)

        self.assertEqual(row["status"], "error")
        self.assertEqual(row["detail"], "certificate did not verify")
        self.assertEqual(row["source"], "digitva.test.invalid:443")
        self.assertNotIn("issuer", repr(row))


class ReportCacheTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.store = {}

        class FakeCache:
            def get(inner, key):
                return self.store.get(key)

            def set(inner, key, value, timeout=None):
                self.store[key] = value

        patcher = mock.patch("app.cache", FakeCache())
        patcher.start()
        self.addCleanup(patcher.stop)

    def _row(self, status, **extra):
        row = {
            "key": "app_https",
            "label": "App HTTPS certificate",
            "source": "/x.crt",
            "subject_cn": "app.test.invalid",
            "sans": [],
            "not_after": None,
            "days_left": 3,
            "status": status,
            "detail": "",
        }
        row.update(extra)
        return row

    def test_banner_is_absent_without_a_stored_report(self):
        self.assertIsNone(svc.banner_rows())

    def test_banner_lists_only_the_rows_that_need_attention(self):
        expires = datetime.now(UTC) + timedelta(days=3)
        svc.store_report(
            [self._row("urgent", not_after=expires), self._row("ok", key="public_https")]
        )

        attention = svc.banner_rows()

        self.assertEqual([r["key"] for r in attention], ["app_https"])
        self.assertEqual(attention[0]["days_left"], 3)
        self.assertIsInstance(self.store[svc.CACHE_KEY][0]["not_after"], str)

    def test_banner_is_absent_when_everything_is_ok(self):
        svc.store_report([self._row("ok")])

        self.assertIsNone(svc.banner_rows())

    def test_cache_failure_does_not_break_the_banner(self):
        class BrokenCache:
            def get(self, key):
                raise RuntimeError("redis down")

        with mock.patch("app.cache", BrokenCache()):
            self.assertIsNone(svc.banner_rows())


def _client_error(code, status, message="raw detail with AKIAFAKEKEY123"):
    return ClientError(
        {
            "Error": {"Code": code, "Message": message},
            "ResponseMetadata": {"HTTPStatusCode": status},
        },
        "Op",
    )


class S3StoreRowTests(BaseTestCase):
    def test_local_store_is_one_not_configured_row(self):
        ctx = svc._Context(now=datetime.now(UTC), warn_days=30, urgent_days=7)
        with mock.patch.dict(self.app.config, {"ATTACHMENT_STORE": "local"}):
            rows = svc._s3_rows(ctx)

        self.assertEqual([(r["key"], r["status"]) for r in rows], [("s3_store", "not_configured")])


class S3StoreProbeTests(TestCase):
    """The S3 checks run against moto. Failures are injected on the store's own client."""

    def setUp(self):
        self.mock = mock_aws()
        self.mock.start()
        self.addCleanup(self.mock.stop)
        self.addCleanup(store_mod.reset_s3_clients)
        self.app = make_s3_app()
        app_ctx = self.app.app_context()
        app_ctx.push()
        self.addCleanup(app_ctx.pop)
        self.store = store_mod.get_attachment_store()
        self.ctx = svc._Context(now=datetime.now(UTC), warn_days=30, urgent_days=7)
        # moto serves botocore, not plain HTTP: the public-access GETs are
        # answered here like a locked bucket (signed 200, unsigned 403).
        self.http_urls = []
        patcher = mock.patch.object(svc, "_http_status", side_effect=self._locked_bucket)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _locked_bucket(self, url):
        self.http_urls.append(url)
        return 200 if "X-Amz-Signature=" in url else 403

    def _rows(self):
        return {r["key"]: r for r in svc._s3_rows(self.ctx)}

    def _objects_under_health(self):
        listing = self.store.client.list_objects_v2(
            Bucket=self.store.bucket, Prefix=self.store.absolute_key("health/")
        )
        return [item["Key"] for item in listing.get("Contents", [])]

    def test_healthy_bucket_is_ok_and_the_probe_is_deleted(self):
        with mock.patch.object(
            self.store.client, "put_object", wraps=self.store.client.put_object
        ) as put:
            rows = self._rows()

        self.assertEqual(put.call_count, 2)
        self.assertEqual(put.call_args.kwargs["ServerSideEncryption"], "AES256")
        self.assertEqual(
            [(r["key"], r["status"], r["detail"]) for r in rows.values()],
            [("s3_access", "ok", ""), ("s3_write", "ok", ""), ("s3_public", "ok", "")],
        )
        signed, unsigned, listing = self.http_urls
        self.assertIn("X-Amz-Signature=", signed)
        self.assertNotIn("?", unsigned)
        self.assertTrue(signed.startswith(unsigned + "?"))
        self.assertIn("list-type=2", listing)
        self.assertNotIn("health/", listing)
        self.assertEqual(
            rows["s3_access"]["source"], f"s3://{self.store.bucket}/{self.store.key_prefix}"
        )
        self.assertIsNone(rows["s3_access"]["not_after"])
        self.assertEqual(self._objects_under_health(), [])

    def _public_rows(self, statuses):
        with mock.patch.object(svc, "_http_status", side_effect=statuses):
            rows = self._rows()
        self.assertEqual(self._objects_under_health(), [])
        return rows

    def test_publicly_readable_objects_are_an_error(self):
        rows = self._public_rows([200, 200])
        self.assertEqual(rows["s3_public"]["status"], "error")
        self.assertEqual(rows["s3_public"]["detail"], "objects are publicly readable")
        self.assertTrue(svc.needs_attention(list(rows.values())))

    def test_a_publicly_listable_bucket_is_an_error(self):
        rows = self._public_rows([200, 403, 200])
        self.assertEqual(rows["s3_public"]["detail"], "bucket is publicly listable")

    def test_a_refused_presigned_link_is_an_error(self):
        rows = self._public_rows([403])
        self.assertEqual(rows["s3_public"]["status"], "error")
        self.assertEqual(rows["s3_public"]["detail"], "presigned link did not return the object")

    def test_no_route_for_the_public_check_is_unreachable(self):
        import urllib.error

        rows = self._public_rows(urllib.error.URLError("no route"))
        self.assertEqual(rows["s3_public"]["status"], "unreachable")
        self.assertNotIn("no route", repr(rows))

    def test_missing_bucket_is_reported_and_later_steps_are_skipped(self):
        self.store.client.delete_bucket(Bucket=self.store.bucket)

        with mock.patch.object(self.store.client, "put_object") as put:
            rows = self._rows()

        put.assert_not_called()

        self.assertEqual(rows["s3_access"]["status"], "error")
        self.assertEqual(rows["s3_access"]["detail"], "bucket not found")
        self.assertEqual(rows["s3_write"]["status"], "not_configured")
        self.assertEqual(rows["s3_write"]["detail"], "skipped after an earlier failure")

    def test_rejected_credentials_are_an_error_with_a_fixed_phrase(self):
        with mock.patch.object(
            self.store.client, "list_objects_v2", side_effect=_client_error("InvalidAccessKeyId", 403)
        ):
            rows = self._rows()

        self.assertEqual(rows["s3_access"]["status"], "error")
        self.assertEqual(rows["s3_access"]["detail"], "credentials rejected")
        self.assertNotIn("AKIAFAKEKEY123", repr(rows))
        self.assertTrue(svc.needs_attention(list(rows.values())))

    def test_access_denied_on_list_is_an_error_naming_the_iam_policy(self):
        with mock.patch.object(
            self.store.client, "list_objects_v2", side_effect=_client_error("AccessDenied", 403)
        ):
            rows = self._rows()

        self.assertEqual(rows["s3_access"]["status"], "error")
        self.assertIn("check the IAM policy", rows["s3_access"]["detail"])
        self.assertNotIn("AKIAFAKEKEY123", repr(rows))

    def test_denied_write_is_an_error_and_leaves_nothing_to_delete(self):
        with mock.patch.object(
            self.store.client, "put_object", side_effect=_client_error("AccessDenied", 403)
        ):
            rows = self._rows()

        self.assertEqual(rows["s3_write"]["status"], "error")
        self.assertIn("check the IAM policy", rows["s3_write"]["detail"])
        self.assertEqual(self._objects_under_health(), [])

    def test_probe_is_deleted_when_its_head_fails(self):
        real_delete = self.store.client.delete_object
        with mock.patch.object(
            self.store.client, "head_object", side_effect=RuntimeError("head broke")
        ), mock.patch.object(
            self.store.client, "delete_object", side_effect=real_delete
        ) as delete:
            rows = self._rows()

        delete.assert_called_once()
        self.assertEqual(rows["s3_write"]["status"], "error")
        self.assertEqual(self._objects_under_health(), [])
        self.assertNotIn("head broke", repr(rows))

    def test_a_dropped_connection_is_unreachable_not_emailed(self):
        from botocore.exceptions import ConnectionClosedError

        with mock.patch.object(
            self.store.client,
            "list_objects_v2",
            side_effect=ConnectionClosedError(endpoint_url="https://s3.test.invalid"),
        ):
            rows = self._rows()

        self.assertEqual(rows["s3_access"]["status"], "unreachable")
        self.assertFalse(svc.needs_attention(list(rows.values())))

    def test_probe_that_cannot_be_deleted_is_an_error(self):
        with mock.patch.object(
            self.store.client, "delete_object", side_effect=_client_error("AccessDenied", 403)
        ) as delete:
            rows = self._rows()

        delete.assert_called_once()

        self.assertEqual(rows["s3_write"]["status"], "error")
        self.assertEqual(rows["s3_write"]["detail"], "probe object could not be deleted")
        self.assertNotIn("AKIAFAKEKEY123", repr(rows))

    def test_unreachable_endpoint_is_unreachable_not_an_error(self):
        for exc in (
            EndpointConnectionError(endpoint_url="https://s3.test.invalid"),
            ConnectTimeoutError(endpoint_url="https://s3.test.invalid"),
        ):
            with self.subTest(exc=type(exc).__name__):
                with mock.patch.object(self.store.client, "list_objects_v2", side_effect=exc):
                    rows = self._rows()

                self.assertEqual(rows["s3_access"]["status"], "unreachable")
                self.assertEqual(rows["s3_access"]["detail"], "S3 endpoint unreachable")
                self.assertFalse(svc.needs_attention(list(rows.values())))

    def test_unexpected_failure_is_a_generic_error(self):
        with mock.patch.object(self.store.client, "list_objects_v2", side_effect=RuntimeError("boom")):
            rows = self._rows()

        self.assertEqual(rows["s3_access"]["status"], "error")
        self.assertEqual(rows["s3_access"]["detail"], "S3 check failed")
        self.assertNotIn("boom", repr(rows))

    def test_certificate_report_includes_the_s3_rows(self):
        with mock.patch.dict(self.app.config, {"PUBLIC_BASE_URL": ""}):
            rows = {r["key"]: r for r in svc.certificate_report()}

        self.assertEqual(rows["s3_access"]["status"], "ok")
        self.assertEqual(rows["s3_write"]["status"], "ok")
