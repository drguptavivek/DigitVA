"""PII slice 2, T3: duplicate matching over the sealed register (docs/kb/pii-slice-2.md).

The whole possible-duplicate suite is run again with ``REGISTER_PII_SPLIT_ENABLED``
on (new rows sealed). On top: plaintext/sealed parity of the result, phone and
ABHA hints, the prefilter cap, a constant statement count, what is opened, and
the Python trigram against live pg_trgm.
"""
import uuid
from datetime import timedelta
from unittest import mock

import sqlalchemy as sa

from app import db
from app.models import MapDeathIdentifier, MasDeathIdentifierType, VaDeathRegister
from app.services import register_duplicate_service as dup
from app.services import register_pii_accessor as accessor
from app.services import web_intake_service as intake_svc
from app.utils import pii_crypto as pc
from tests.services import test_possible_duplicates as base_tests

DOD = base_tests.DOD


class SealedPossibleDuplicateTests(base_tests.PossibleDuplicateTests):
    """Every inherited test runs with sealed rows; the tests below are new."""

    def setUp(self):
        super().setUp()
        self.addCleanup(self.app.config.__setitem__, "REGISTER_PII_SPLIT_ENABLED",
                        self.app.config.get("REGISTER_PII_SPLIT_ENABLED", False))
        self.app.config["REGISTER_PII_SPLIT_ENABLED"] = True
        dup._classes()  # the one-off probe is not part of any measured page

    # -- helpers ------------------------------------------------------------

    def _row(self, name="Kamla Devi", unit="PDB1", dod=DOD, **over):
        """A plaintext row built directly (not sealed), as a legacy row is."""
        values = {
            "project_id": self.PROJECT_ID, "site_id": self.SITE_ID, "death_number": uuid.uuid4().int % 10**9,
            "unique_id": f"DUP-{uuid.uuid4().hex[:10]}", "deceased_name": name, "deceased_sex": "female",
            "age_years": 62, "date_of_death": dod, "status": "registered", "source": "register",
            "registered_by": self.alice.user_id, "org_unit_id": self.unit[unit].org_unit_id,
        }
        values.update(over)
        death = VaDeathRegister(**values)
        db.session.add(death)
        db.session.flush()
        return death

    def _rows(self, subjects, per_case, scope=None):
        scope = scope if scope is not None else intake_svc._worklist_scope(self.alice)
        return dup.possible_duplicate_rows([s.death_id for s in subjects], scope, per_case=per_case)

    def _snapshot(self, subjects, per_case):
        return [
            (r.subject_id, r.death_id, round(r.score, 5), r.deceased_name, r.informant_name,
             r.address_village_ward, r.unique_id, r.unit_name, r.interviewer_name, r.registrant_name)
            for r in self._rows(subjects, per_case)
        ]

    def _identifier_type(self):
        kind = MasDeathIdentifierType(
            project_id=self.PROJECT_ID, code="crs", label="CRS", sort_order=1, min_length=4, max_length=12,
            char_type="digits", uniqueness_scope="project",
        )
        db.session.add(kind)
        db.session.flush()
        return kind

    def _number(self, kind, death, value):
        db.session.add(MapDeathIdentifier(
            death_id=death.death_id, identifier_type_id=kind.identifier_type_id, value_ciphertext="x",
            dek_wrapped="x", value_blind_index=pc.blind_index(kind.identifier_type_id.bytes, value),
            key_id="k", entered_by=self.alice.user_id,
        ))
        db.session.flush()

    def _seal(self, *deaths):
        for death in deaths:
            accessor.seal_register_pii(death)
        db.session.flush()

    # -- parity -------------------------------------------------------------

    def test_name_and_number_matches_are_identical_before_and_after_sealing(self):
        kind = self._identifier_type()
        subject = self._row("Kamla Devi", informant_name="Mohan", address_village_ward="Kandaghat")
        names = [self._row(n, dod=DOD + timedelta(days=i % 3), informant_name=f"Inf {i}")
                 for i, n in enumerate(("Smt. KAMLA devi", "Kamala Devi", "Late Kamla-Devi", "Ramesh Singh"))]
        far_unit = self._row("Someone Else", unit="PDB3", dod=DOD + timedelta(days=30))
        self._number(kind, subject, "123456")
        self._number(kind, far_unit, "123456")
        everyone = [subject, *names, far_unit]

        for per_case in (3, 50):
            before = self._snapshot(everyone, per_case)
            self.assertTrue(any(row[0] == subject.death_id and row[1] == names[0].death_id for row in before))
            self.assertTrue(any(row[1] == far_unit.death_id and row[2] == 1.0 for row in before))
            self.assertFalse(any(row[1] == names[3].death_id and row[0] == subject.death_id for row in before))
            self.assertIsNotNone(subject.deceased_name)
        plain = {n: self._snapshot(everyone, n) for n in (3, 50)}

        self._seal(*everyone)
        self.assertIsNone(subject.deceased_name)  # the plaintext is really gone
        for per_case in (3, 50):
            self.assertEqual(self._snapshot(everyone, per_case), plain[per_case], per_case)

    def test_phone_and_abha_hints_match_sealed_rows_by_index_with_score_one(self):
        subject = self._row("Asha Rao", dod=DOD, informant_phone="+91 98765-43210", informant_phone_2="9123456780",
                            abha_number="12-3456-7890-1234", abha_address="asha@abdm")
        by_phone2 = self._row("Different Name", unit="PDD2", dod=DOD + timedelta(days=40),
                              informant_phone="08888888888", informant_phone_2="9876543210")
        by_phone_same = self._row("Another", dod=DOD + timedelta(days=50), informant_phone="9123456780")
        by_abha_number = self._row("Third", dod=DOD + timedelta(days=60), abha_number="12345678901234")
        by_abha_address = self._row("Fourth", dod=DOD + timedelta(days=70), abha_address="ASHA@abdm")
        unrelated = self._row("Fifth", dod=DOD + timedelta(days=80), informant_phone="9000000001")
        others = [by_phone2, by_phone_same, by_abha_number, by_abha_address, unrelated]
        # Legacy plaintext rows carry no index: no hint. The subject is present, so the absence means it.
        self.assertEqual([r for r in self._rows([subject], 50) if r.death_id in {o.death_id for o in others}], [])

        self._seal(subject, *others)
        for per_case in (3, 50):
            rows = {r.death_id: r for r in self._rows([subject], per_case)}
            expected = {by_phone2, by_phone_same, by_abha_number, by_abha_address}
            if per_case == 50:
                self.assertEqual(set(rows), {o.death_id for o in expected})
            else:
                self.assertEqual(len(rows), 3)
                self.assertLessEqual(set(rows), {o.death_id for o in expected})
            self.assertTrue(all(r.score == 1.0 for r in rows.values()))
            self.assertNotIn(unrelated.death_id, rows)
        rows = {r.death_id: r for r in self._rows([subject], 50)}
        self.assertEqual(rows[by_phone2.death_id].deceased_name, "Different Name")  # opened for the survivor
        # The hint is symmetric: the other side finds the subject.
        self.assertIn(subject.death_id, {r.death_id for r in self._rows([by_abha_address], 50)})

    def test_phone_hint_obeys_scope_status_and_project(self):
        subject = self._row("Asha Rao", informant_phone="9876543210")
        far = self._row("Far Away", unit="PDD2", dod=DOD + timedelta(days=40), informant_phone="9876543210")
        closed = self._row("Closed", dod=DOD + timedelta(days=41), informant_phone="9876543210", status="cancelled")
        self._seal(subject, far, closed)
        self.assertEqual({r.death_id for r in self._rows([subject], 50)}, {far.death_id})
        carol_scope = intake_svc._worklist_scope(self.carol)
        self.assertEqual(dup.possible_duplicate_rows([subject.death_id], carol_scope, per_case=50), [])

    # -- cost and what is opened ---------------------------------------------

    def test_names_never_reach_postgres(self):
        subject = self._case(name="Zorbulon Quimby")
        twin = self._case(name="Zorbulon Quimbi")
        statements = []

        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(f"{statement} {parameters}")

        sa.event.listen(db.engine, "before_cursor_execute", record)
        try:
            hints = intake_svc.possible_duplicates(self.alice, subject)
        finally:
            sa.event.remove(db.engine, "before_cursor_execute", record)
        self.assertEqual([h["death_id"] for h in hints], [str(twin.death_id)])
        self.assertEqual(hints[0]["deceased_name"], "Zorbulon Quimbi")
        self.assertFalse([s for s in statements if "Zorbulon" in s or "zorbulon" in s])

    def test_statement_count_is_constant_for_any_page(self):
        counts = []
        scope = intake_svc._worklist_scope(self.alice)  # its grant lookups are not part of the page
        for size in (2, 6):
            subjects = [self._case(name=f"Page Subject{'x' * i}") for i in range(size)]
            db.session.flush()
            statements = []

            def record(conn, cursor, statement, parameters, context, executemany):
                statements.append(statement)

            sa.event.listen(db.engine, "before_cursor_execute", record)
            try:
                rows = self._rows(subjects, 3, scope)
            finally:
                sa.event.remove(db.engine, "before_cursor_execute", record)
            counts.append((len(statements), len(rows)))
        self.assertGreater(counts[0][1], 0)
        self.assertGreater(counts[1][1], counts[0][1])
        self.assertEqual(counts[0][0], counts[1][0], counts)
        self.assertEqual(counts[0][0], 2)

    def test_unwraps_per_page_are_the_distinct_rows_and_nothing_out_of_scope(self):
        group = [self._case(name="Gopal Das") for _ in range(4)]
        out_of_scope = self._case(unit="PDD2", name="Gopal Das")  # alice reaches it; carol does not
        db.session.flush()
        pc.clear_dek_cache()
        with mock.patch.object(pc, "unwrap_dek", wraps=pc.unwrap_dek) as unwrap:
            rows = self._rows(group, 3)
        # Each subject has three candidates (its three siblings; the out-of-scope
        # unit is a top-level neighbour of none of them) and every row is a
        # subject: 4 distinct sealed rows, 4 unwraps, however many pairs.
        self.assertEqual(len(rows), 12)
        self.assertEqual(unwrap.call_count, 4)

        pc.clear_dek_cache()
        carol_scope = intake_svc._worklist_scope(self.carol)
        subject = self._case(unit="PDB3", name="Gopal Das")
        self._case(unit="PDB3", name="Gopal Das")  # a twin carol reaches, so the subject is scored
        with mock.patch.object(pc, "open_record", wraps=pc.open_record) as spy:
            dup.possible_duplicate_rows([subject.death_id], carol_scope, per_case=50)
        opened_rows = {c.kwargs["row_ref"] for c in spy.call_args_list}
        self.assertIn(str(subject.death_id), opened_rows)  # present, so the absences below mean something
        self.assertNotIn(str(out_of_scope.death_id), opened_rows)

    def test_only_the_name_is_opened_for_scoring_and_the_rest_for_survivors(self):
        subject = self._case(name="Rita Kaur")
        twin = self._case(name="Rita Kaur")
        fields = []
        real = pc.open_record

        def spy(*args, **kwargs):
            fields.append((kwargs["row_ref"], tuple(kwargs["only"])))
            return real(*args, **kwargs)

        with mock.patch.object(pc, "open_record", side_effect=spy):
            self.assertEqual(len(self._rows([subject], 50)), 1)
        self.assertEqual(
            sorted(fields),
            sorted([
                (str(subject.death_id), ("deceased_name",)), (str(twin.death_id), ("deceased_name",)),
                (str(twin.death_id), ("deceased_name", "informant_name", "address_village_ward")),
            ]),
        )

    def test_the_prefilter_cap_keeps_the_nearest_and_logs_counts_only(self):
        self.app.config["DUPLICATE_PREFILTER_MAX"] = 2
        self.addCleanup(self.app.config.pop, "DUPLICATE_PREFILTER_MAX", None)
        subject = self._row("Hari Prasad Verma", unit="PDB1", informant_name="Secret Informant")
        same_unit_far_date = self._row("Hari Prasad Verma", unit="PDB1", dod=DOD + timedelta(days=3))
        sibling_same_day = self._row("Hari Prasad Verma", unit="PDB2")
        same_unit_next_day = self._row("Hari Prasad Verma", unit="PDB1", dod=DOD + timedelta(days=1))
        same_unit_same_day = self._row("Hari Prasad Verma", unit="PDB1")
        everyone = [subject, same_unit_far_date, sibling_same_day, same_unit_next_day, same_unit_same_day]
        self._seal(*everyone)

        with self.assertLogs(dup.log, level="WARNING") as logs:
            rows = self._rows([subject], 50)
        # Same unit first, then the closest date: the same day, then the next day.
        self.assertEqual({r.death_id for r in rows}, {same_unit_same_day.death_id, same_unit_next_day.death_id})
        message = logs.output[0]
        self.assertIn("subjects=1 | max_candidates=4 | cap=2", message)
        self.assertNotIn("Hari", message)
        self.assertNotIn(str(subject.death_id), message)

        self.app.config["DUPLICATE_PREFILTER_MAX"] = 50
        with self.assertNoLogs(dup.log, level="WARNING"):
            self.assertEqual(len(self._rows([subject], 50)), 4)

    def test_plaintext_name_candidates_are_never_capped_sealed_ones_are(self):
        self.app.config["DUPLICATE_PREFILTER_MAX"] = 2
        self.addCleanup(self.app.config.pop, "DUPLICATE_PREFILTER_MAX", None)
        subject = self._row("Hari Prasad Verma", unit="PDB1")
        crowd = [self._row("Rina Sen", unit="PDB1") for _ in range(4)]  # nearer, different names
        true_duplicate = self._row("Hari Prasad Verma", unit="PDB2", dod=DOD + timedelta(days=3))
        self.assertEqual(len(crowd), 4)
        # Plaintext (legacy) candidates: the far-date true duplicate is found.
        self.assertEqual({r.death_id for r in self._rows([subject], 50)}, {true_duplicate.death_id})
        # Sealed: capped at the two nearest, which are not the duplicate.
        self._seal(subject, true_duplicate, *crowd)
        with self.assertLogs(dup.log, level="WARNING"):
            self.assertEqual(self._rows([subject], 50), [])

    def test_a_shared_phone_is_capped_nearest_first_with_constant_statements(self):
        self.app.config["DUPLICATE_STRONG_MAX"] = 3
        self.addCleanup(self.app.config.pop, "DUPLICATE_STRONG_MAX", None)
        subject = self._row("Asha Rao", unit="PDB1", informant_phone="9876543210")
        near = self._row("Near One", unit="PDB1", dod=DOD + timedelta(days=1), informant_phone="9876543210")
        same_day_other_unit = self._row("Near Two", unit="PDD2", informant_phone="09876543210")
        far = [self._row(f"Far {i}", unit="PDD2", dod=DOD + timedelta(days=30 + i), informant_phone_2="9876543210")
               for i in range(6)]
        self._seal(subject, near, same_day_other_unit, *far)
        statements = []

        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        scope = intake_svc._worklist_scope(self.alice)  # its grant lookups are not part of the page
        sa.event.listen(db.engine, "before_cursor_execute", record)
        try:
            with self.assertLogs(dup.log, level="WARNING") as logs:
                rows = self._rows([subject], 50, scope)
        finally:
            sa.event.remove(db.engine, "before_cursor_execute", record)
        self.assertEqual(len(statements), 2)
        ids = {r.death_id for r in rows}
        self.assertIn(near.death_id, ids)
        self.assertIn(same_day_other_unit.death_id, ids)
        self.assertLessEqual(len(ids), 3 * 4)  # at most the cap per phone branch
        self.assertLess(len(ids), len(far) + 2)
        self.assertIn("duplicate strong cap hit", logs.output[0])
        self.assertNotIn("9876543210", logs.output[0])

    def test_a_row_with_the_name_present_but_the_subject_without_one_is_skipped(self):
        draft = intake_svc.start_draft(self.alice, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
                                       org_unit_id=str(self.unit["PDB1"].org_unit_id))
        pending = db.session.get(VaDeathRegister, draft.death_id)
        self._case(name="Sunita Devi")
        self.assertEqual(intake_svc.possible_duplicates(self.alice, pending), [])


# ---------------------------------------------------------------------------
# Python normalisation and trigram against live Postgres
# ---------------------------------------------------------------------------

CORPUS = [
    "", " ", "a", "ab", "abc", "Kamla Devi", "Kamala Devi", "KAMLA   devi", "Smt. Kamla-Devi", "Late Kamla Devi",
    "Late Smt. Kamla-Devi  ", "Dr. Mr. Ms. Mrs. Miss Baby Master Kumari Km Shri Sri Shrimati Lt", "Srinivas", "Sri",
    "Ramesh Singh", "ramesh_singh", "R. K. Singh", "O'Brien", "Mary-Ann", "mary ann", "José Álvarez", "JOSÉ ÁLVAREZ",
    "Ünal Çelik", "İstanbul", "Straße", "Ivan Иван", "Иван Петров", "Ivanov", "123 456", "x1y2z3", "a.b.c",
    "कमला देवी", "कमला  देवि", "श्रीमती कमला देवी", "स्व. कमला देवी", "राम सिंह", "रामसिंह", "राम।सिंह", "राम, सिंह",
    "सीता", "सी", "क", "ॐ", "कमला‍देवी", "कमला‌देवी", "कृष्ण कुमार", "कृष्णा कुमारी", "मोहम्मद इरफ़ान", "मोहम्मद इरफान",
    "ಕಮಲಾ ದೇವಿ", "కమల దేవి", "কমলা দেবী", "கமலா தேவி", "كمالا ديفي", "٣٤ name", "Kamla Devi", "Kamla\tDevi",
    "a_b", "a-b", "(Kamla) [Devi]", "Kamla/Devi", "Kamla & Devi", "😀 Kamla", "Kamla 😀 Devi",
]

#: The SQL this port replaces (``web_intake_service._normalised_name`` and the
#: ``similarity()`` call), kept here as the oracle.
_TITLES = r"\m(late|lt|mr|mrs|ms|miss|smt|shrimati|shri|sri|dr|master|baby|kumari|km)\M"


def _sql_normalised(value):
    text = sa.func.regexp_replace(sa.func.lower(value), r"[[:punct:]]+", " ", "g")
    text = sa.func.regexp_replace(text, _TITLES, " ", "g")
    return sa.func.btrim(sa.func.regexp_replace(text, r"\s+", " ", "g"))


class TrigramParityTests(base_tests.BaseTestCase):
    def test_normalised_name_equals_the_sql_normalisation(self):
        names = sa.func.unnest(sa.literal(CORPUS, sa.ARRAY(sa.Text))).column_valued("n")
        rows = db.session.execute(sa.select(names, _sql_normalised(names))).all()
        self.assertEqual(len(rows), len(CORPUS))
        wrong = [(n, sql, dup.normalised_name(n)) for n, sql in rows if dup.normalised_name(n) != sql]
        self.assertEqual(wrong, [])

    def test_similarity_equals_pg_trgm_for_every_pair_of_the_corpus(self):
        source = sa.select(sa.func.unnest(sa.literal(CORPUS, sa.ARRAY(sa.Text))).label("n")).subquery()
        left, right = source.alias("l"), source.alias("r")
        rows = db.session.execute(
            sa.select(left.c.n, right.c.n, sa.func.similarity(_sql_normalised(left.c.n), _sql_normalised(right.c.n)))
            .select_from(left.join(right, sa.true()))
        ).all()
        self.assertEqual(len(rows), len(CORPUS) ** 2)
        wrong = []
        for left, right, score in rows:
            mine = dup.similarity(
                dup.trigrams(dup.normalised_name(left)), dup.trigrams(dup.normalised_name(right))
            )
            if mine != dup._float4(float(score)):
                wrong.append((left, right, mine, float(score)))
        self.assertEqual(wrong, [])
        # Present before absent: the corpus really exercises matches and misses.
        scores = {float(r[2]) for r in rows}
        self.assertIn(1.0, scores)
        self.assertIn(0.0, scores)
        self.assertTrue([s for s in scores if 0.4 <= s <= 0.6])

    def test_trigram_sets_have_the_size_of_show_trgm_for_the_corpus(self):
        # Postgres hashes non-ASCII trigrams to 24 bits, so equal sizes also say
        # that none of the corpus collides.
        for name in CORPUS:
            normalised = dup.normalised_name(name)
            shown = db.session.scalar(sa.select(sa.func.show_trgm(normalised)))
            mine = dup.trigrams(normalised)
            self.assertEqual(len(mine), len(shown), name)
