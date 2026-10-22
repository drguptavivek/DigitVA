"""Offline bundle conformance vectors (digitva-gb8w.6; bundle spec 7 vector 4,
section 9). One scenario table, two users:

* ``DIGITVA_WRITE_BUNDLE_VECTORS=1 pytest tests/test_bundle_vectors.py`` builds every scenario with the
  fixed station identity (``FixedKit``: the sample bundle's device, station
  config, station key seed ``0x52 * 32``, KEM key ``tv1``) into
  ``tests/fixtures/bundles/vectors/*.dvb`` plus ``expected.json``. The bytes
  differ per run (random DEK and nonces, as the spec allows); regenerate only
  after a deliberate change, then re-run the three consumers below.
* ``tests/test_bundle_vectors.py`` checks every committed file against its
  ``container`` expectation (signature, body hash, record types) with the
  server's parser, and that ``expected.json`` still equals this table.
* ``tests/routes/test_bundle_ingest_api.py`` rebuilds each scenario with the
  live test station and asserts the ``steps`` (HTTP status, code, per-record
  outcome) against the real ingest.
* ``desktop/crates/digitva-bundle/tests/bundle_vectors.rs`` checks the same
  ``container`` expectations with the station crate's verifier.

A step is ``(setup, build, expect)``. *setup* is a tuple of tokens the ingest
test applies before building (the fixed kit ignores them): ``fresh_station``,
``revoked_station``, ``superseded_config``, ``expired_config``, ``project_mode:<mode>``,
``ready``. *build* takes a kit and returns bundle bytes. *expect* is
``{"status", "code", "records": [[record_type, outcome, code], ...]}`` in
report order (spec 2.4 type order), ``code`` the whole-bundle refusal.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.services.station_config_service import canonical_json
from tests import bundle_builder as bb

VECTORS = Path(__file__).parent / "fixtures" / "bundles" / "vectors"
FIXTURES = Path(__file__).parent / "fixtures"
STATION_KEY = Ed25519PrivateKey.from_private_bytes(b"\x52" * 32)
OTHER_KEY = Ed25519PrivateKey.from_private_bytes(b"\x53" * 32)
DEVICE_ID = uuid.UUID("0b8d6c2e-1f3a-4c5b-9d7e-8f9a0b1c2d3e")
CONFIG_ID = uuid.UUID("6f1c2b3a-4d5e-4f60-8a71-92b3c4d5e6f7")
NOTICE_ID = "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d"
NOTICE_SHA = "f9e7f8bfa6527fc40a4b97b5e8ad528c39240ba732ce4126dd1ae0e63e89154c"
CREATED_AT = datetime(2026, 10, 21, 10, 0, 0, tzinfo=UTC)
ANSWERS = '{"Id10013":"yes","Id10017":"Ram","Id10073":"XXXXXXXXX123"}'
LINE_LIMIT_BYTES = 2 * 1024 * 1024 + 64 * 1024 + 1  # one byte over the record line limit (spec 2.3)


def key_id(key=STATION_KEY) -> str:
    return bb.key_id(key)


def tv1_public():
    from tests.test_bundle_fixture import _tv1

    return _tv1().public_key()


class FixedKit:
    """The sample station's identity; every id derives from the scenario name."""

    fixed = True

    def __init__(self, scenario: str):
        self.scenario, self._ids = scenario, {}
        self.key, self.device_id, self.config_id = STATION_KEY, DEVICE_ID, CONFIG_ID
        self.signing_key_id = key_id(STATION_KEY)
        self.last_interview = None

    def id(self, name: str) -> uuid.UUID:
        # Version 4 in form: the ingest takes only v4 bundle and client ids.
        return self._ids.setdefault(name, uuid.UUID(int=uuid.uuid5(DEVICE_ID, f"{self.scenario}/{name}").int, version=4))

    def _rec(self, record_type, name, actor=7, role="interviewer", **body):
        return bb.record(record_type, project_id="TST001", actor_user_id=actor, acting_role=role,
                         client_id=self.id(name), recorded_at="2026-10-21T15:05:00+05:30", **body)

    def registration(self, name="reg", consent=None, **fields):
        body = {"site_id": "TS01", "deceased_name": "Ram Lal", "deceased_sex": "male",
                "date_of_death": "2026-10-18", "age_years": 70, **fields}
        if consent is not None:
            body["consent_client_id"] = consent["client_id"]
        return self._rec("death_registration", name, **body)

    def consent(self, death_ref, name="consent", granted=True):
        return self._rec(
            "consent", name, death_ref=death_ref, client_draft_id=None, notice_version_id=NOTICE_ID,
            notice_language="en", notice_sha256=NOTICE_SHA, decision="granted" if granted else "refused",
            purposes=[{"code": "record_interview", "granted": granted}], mode="tap", witness_present=False,
            supersedes_client_id=None)

    def interview(self, death_ref, name="interview", consent_client_id=None, answers=ANSWERS):
        import hashlib

        stamp = "2026-10-21T14:40:00+00:00"
        record = self._rec(
            "interview_submission", name, site_id="TS01", death_ref=death_ref,
            draft={"instrumentVersion": "2023072701", "startedAt": stamp, "completedAt": stamp,
                   "deviceClockAt": stamp, "interviewOutcome": "completed"},
            completion={"valid": True, "issues": []}, answers_json=answers,
            answers_sha256=hashlib.sha256(answers.encode()).hexdigest(), consent_client_id=consent_client_id)
        self.last_interview = record
        return record

    def coding(self, interview, mode, name="coding"):
        final = ({"conclusive_cod": "1B10.Z Respiratory tuberculosis", "doris_certificate": {"ICDVersion": "ICD11"}}
                 if mode == "icd11_doris" else
                 {"conclusive_cod": "I64", "remark": "station", "immediate_cod": "I64", "other_conditions": "I10"})
        return self._rec("coding_result", name, actor=9, role="coder", kind="final", coding_mode=mode,
                         client_draft_id=interview["client_id"],
                         coded_answers_sha256=interview["answers_sha256"], final=final)

    def bundle(self, records, *, key=None, bundle_id=None, bundle_seq=1, **kwargs):
        return bb.build(records, signing_key=key or self.key, device_id=self.device_id,
                        station_config_id=self.config_id, project_id="TST001", public_key=tv1_public(),
                        bundle_id=bundle_id or self.id(f"bundle{bundle_seq}"), bundle_seq=bundle_seq,
                        created_at=CREATED_AT, **kwargs)


def _ref(record):
    return {"client_death_id": record["client_id"]}


# ── byte-level mutations (what a hostile or damaged file looks like) ───────

def _lines(raw):
    return raw.split(b"\n")


def flip_record_byte(raw):
    lines = _lines(raw)
    record = json.loads(lines[2])
    record["ct"] = record["ct"][:-2] + ("AA" if not record["ct"].endswith("AA") else "BB")
    return b"\n".join([*lines[:2], canonical_json(record), *lines[3:]])


def change_manifest(raw):
    lines = _lines(raw)
    manifest = json.loads(lines[0])
    manifest["app_version"] = "9.9.9"
    return b"\n".join([canonical_json(manifest), *lines[1:]])


def swap_records(raw):
    lines = _lines(raw)
    return b"\n".join([*lines[:2], lines[3], lines[2], *lines[4:]])


# ── scenarios ──────────────────────────────────────────────────────────────

def _consented(kit, **extra):
    """Registration with informant data, its granted consent and an interview."""
    registration = kit.registration(informant_name="Sita Devi", **extra)
    consent = kit.consent(_ref(registration))
    registration["consent_client_id"] = consent["client_id"]
    interview = kit.interview(_ref(registration), consent_client_id=consent["client_id"])
    return registration, consent, interview


def valid(kit):
    return kit.bundle(list(_consented(kit)))


def _one(kit, **body):
    return kit.bundle([kit.registration(**body)])


def partial(kit):
    good = _consented(kit)
    bad = kit.registration("bad", informant_name="Someone")  # informant data, no consent
    on_bad = kit.interview(_ref(bad), "on_bad")
    return kit.bundle([*good, bad, on_bad])


def coder_steps(mode, setup, expect):
    """The case in one bundle, then the coder's result for it in the next."""
    def case(kit):
        registration = kit.registration()
        return kit.bundle([registration, kit.interview(_ref(registration))])

    def coding(kit):
        return kit.bundle([kit.coding(kit.last_interview, mode)], bundle_seq=2)

    return [((), case, _ok([("death_registration", "accepted", None), ("interview_submission", "accepted", None)])),
            (setup, coding, expect)]


def _ok(records, status=201):
    return {"status": status, "code": None, "records": [list(r) for r in records]}


def _refused(code, status=422):
    return {"status": status, "code": code, "records": []}


ALL_ACCEPTED = [("death_registration", "accepted", None), ("consent", "accepted", None),
                ("interview_submission", "accepted", None)]


def _container(signature=True, body_hash=True, types=("death_registration", "consent", "interview_submission")):
    return {"signature_ok": signature, "body_hash_ok": body_hash, "record_types": list(types)}


def _scenarios():
    one = ("death_registration",)
    cod = ("coding_result",)
    case = _container(types=("death_registration", "interview_submission"))
    return [
        ("valid", "A sandbox-free bundle: registration with informant data, its consent, the interview.",
         _container(), [((), valid, _ok(ALL_ACCEPTED))]),
        ("tampered_ciphertext", "One ciphertext byte changed: the body hash no longer matches.",
         _container(body_hash=False), [((), lambda k: flip_record_byte(valid(k)), _refused("body_hash_invalid"))]),
        ("reordered_records", "Two record lines swapped: the body hash no longer matches.",
         _container(body_hash=False, types=("consent", "death_registration", "interview_submission")),
         [((), lambda k: swap_records(valid(k)), _refused("body_hash_invalid"))]),
        ("tampered_manifest", "A manifest field changed after signing.",
         _container(signature=False), [((), lambda k: change_manifest(valid(k)), _refused("signature_invalid"))]),
        ("wrong_signature", "Signed by another key under the station's signing_key_id.",
         _container(signature=False),
         [((), lambda k: k.bundle(list(_consented(k)), key=OTHER_KEY,
                                  manifest_overrides={"signing_key_id": k.signing_key_id}),
           _refused("signature_invalid"))]),
        ("unknown_signing_key", "Signed with a key the server never registered for the station.",
         _container(), [((), lambda k: k.bundle(list(_consented(k)), key=OTHER_KEY), _refused("signing_key_unknown"))]),
        ("unknown_device", "A device id the server does not know.",
         _container(), [(("unknown_device",), valid, _refused("device_unknown"))]),
        ("revoked_device", "A station revoked before the bundle was made.",
         _container(), [(("revoked_station",), valid, _refused("device_revoked", 403))]),
        ("replayed", "The same bytes sent twice: the stored report again (200), nothing written twice.",
         _container(), [((), valid, _ok(ALL_ACCEPTED)), ((), "again", _ok(ALL_ACCEPTED, 200))]),
        ("replayed_other_bytes", "A bundle_id the server already holds, with other records.",
         _container(types=one),
         [((), lambda k: k.bundle([k.registration("a")], bundle_id=k.id("replay")), _ok([("death_registration", "accepted", None)])),
          ((), lambda k: k.bundle([k.registration("b")], bundle_id=k.id("replay")), _refused("bundle_id_reused", 409))]),
        ("same_records_later_bundle", "The same records in a later bundle (new id, seq 2) are duplicates.",
         _container(types=one),
         [((), lambda k: k.bundle([k.registration("r")]), _ok([("death_registration", "accepted", None)])),
          ((), lambda k: k.bundle([k.registration("r")], bundle_seq=2), _ok([("death_registration", "duplicate", None)]))]),
        ("superseded_station_config", "A bundle naming an earlier config of the station, a newer one since issued: still issued to it, accepted.",
         _container(), [(("superseded_config",), valid, _ok(ALL_ACCEPTED))]),
        ("unissued_station_config", "A bundle naming a config this server never issued to the station (sandbox build or forged id).",
         _container(), [(("unissued_config",), valid, _refused("station_not_onboarded"))]),
        ("expired_station_config", "A bundle made after the expires_at of the config it names (issued to the station, not superseded); the Rust writer refuses the same before writing.",
         _container(), [(("expired_config",), valid, _refused("station_config_expired"))]),
        ("consent_missing_informant", "Informant data with no consent: the record is rejected, the bundle is processed.",
         _container(types=one), [((), lambda k: _one(k, informant_name="Sita Devi"),
                                  _ok([("death_registration", "rejected", "consent_required")]))]),
        ("partial_acceptance", "A valid case beside a registration without consent and an interview on it.",
         _container(types=("death_registration", "death_registration", "consent", "interview_submission", "interview_submission")),
         [((), partial, _ok([("death_registration", "accepted", None), ("death_registration", "rejected", "consent_required"),
                             ("consent", "accepted", None), ("interview_submission", "accepted", None),
                             ("interview_submission", "rejected", "depends_on_rejected")]))]),
        ("coder_icd11_doris", "A DORIS result in an ICD-11 project: held for the server's reprocessing.",
         [case, _container(types=cod)], coder_steps("icd11_doris", ("project_mode:unmasked_doris", "ready"),
                                            _ok([("coding_result", "pending", "doris_pending")]))),
        ("coder_icd10", "An ICD-10 result in an unmasked simple project: applied at once.",
         [case, _container(types=cod)], coder_steps("icd10", ("project_mode:unmasked_simple", "ready"),
                                            _ok([("coding_result", "accepted", None)]))),
        ("coder_mode_mismatch", "A DORIS result sent to an ICD-10 project: refused.",
         [case, _container(types=cod)], coder_steps("icd11_doris", ("project_mode:unmasked_simple", "ready"),
                                            _ok([("coding_result", "rejected", "coding_mode_mismatch")]))),
        ("oversize_record_line", "A record line over the line limit (generated at test time, never stored).",
         None, [((), "oversize", _refused("payload_too_large", 413))]),
    ]


SCENARIOS = _scenarios()


def oversize(kit):
    """A signed bundle whose one record line is one byte over the limit."""
    registration = kit.registration()
    return kit.bundle([registration], record_bytes={registration["client_id"]: b"x" * LINE_LIMIT_BYTES})


def run_builders(kit, name, steps):
    """The bundle bytes of each step of one scenario, in order."""
    raws = []
    for _setup, build, _expect in steps:
        raws.append(raws[-1] if build == "again" else oversize(kit) if build == "oversize" else build(kit))
    return raws


def expected_document() -> dict:
    out = {}
    for name, doc, container, steps in SCENARIOS:
        out[name] = {"description": doc,
                     "container": None if container is None else
                     container if isinstance(container, list) else [container] * len(steps),
                     "files": None if container is None else
                     [f"{name}.dvb" if i == 0 else f"{name}.{i + 1}.dvb" for i in range(len(steps))],
                     "steps": [{"setup": list(s), "expect": e} for s, _b, e in steps]}
    return out


def write() -> None:
    VECTORS.mkdir(parents=True, exist_ok=True)
    for name, _doc, container, steps in SCENARIOS:
        if container is None:
            continue  # synthetic
        for index, raw in enumerate(run_builders(FixedKit(name), name, steps)):
            (VECTORS / (f"{name}.dvb" if index == 0 else f"{name}.{index + 1}.dvb")).write_bytes(raw)
    (VECTORS / "expected.json").write_text(
        json.dumps(expected_document(), indent=1, sort_keys=True) + "\n", encoding="utf-8")
