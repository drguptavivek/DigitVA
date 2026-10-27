"""KPI registry (digitva-r5s0): schema, drift against docs/policy/kpis.md,
the help page rendered from it and the ``kpi`` search kind."""

import copy
import importlib
import os
import re
import unittest
from pathlib import Path
from unittest import mock

from app.services import ai_analytics_catalog, kpi_registry
from app.services import ai_search_service as search
from tests.base import BaseTestCase

POLICY = Path(__file__).resolve().parents[2] / "docs" / "policy" / "kpis.md"
CORE_EXAMPLE = "C-21"
CATALOG_KPIS = {"O-UNK", "EQ-01", "EQ-02", "EQ-03", "AD-FCOD", "C-05", "C-06", "MO-01", "D-LC-01"}


def _entry(**changes):
    entry = copy.deepcopy(kpi_registry.get_kpi(CORE_EXAMPLE))
    entry.update(changes)
    return entry


class KpiRegistrySchemaTests(unittest.TestCase):
    def test_shipped_registry_loads_with_the_policy_tier_counts(self):
        tiers = [k["tier"] for k in kpi_registry.load_registry()]
        self.assertEqual(
            {t: tiers.count(t) for t in kpi_registry.TIERS},
            {"core": 18, "registered": 35, "merged": 16, "retired": 1},
        )

    def test_lookup_and_filters(self):
        self.assertEqual(kpi_registry.get_kpi("O-UNK")["name"], "Unknown Cause Share")
        self.assertIsNone(kpi_registry.get_kpi("NOPE"))
        self.assertIsNone(kpi_registry.get_kpi(None))
        core_outcome = kpi_registry.list_kpis(stage="outcome", tier="core")
        self.assertEqual({k["id"] for k in core_outcome}, {"O-UNK", "D-QG-09", "EQ-01", "EQ-02"})
        self.assertIn("C-23", {k["id"] for k in kpi_registry.list_kpis(views="blocker")})
        self.assertIn("AD-VN", {k["id"] for k in kpi_registry.list_kpis(audience="IC")})
        self.assertIn("C-21", {k["id"] for k in kpi_registry.list_kpis(level="Bk", category="workforce")})
        self.assertEqual(kpi_registry.list_kpis(stage="process", tier="retired"), [])

    def test_display_groups_follow_stage_then_category(self):
        groups = kpi_registry.grouped_for_display()
        self.assertEqual([stage for stage, _ in groups], list(kpi_registry.STAGES))
        shown = [k["id"] for _, cats in groups for _, kpis in cats for k in kpis]
        self.assertEqual(len(shown), 53)  # core and registered only
        self.assertNotIn("C-02", shown)

    def test_validate_accepts_the_registry_and_rejects_each_kind_of_fault(self):
        kpi_registry.validate(kpi_registry.load_registry())
        good = _entry()
        faults = {
            "enum": _entry(stage="upstream"),
            "level": _entry(level=["Zz"]),
            "tier": _entry(tier="optional"),
            "list type": _entry(views="status"),
            "peer": _entry(peer="yes"),
            "min_whole": _entry(min_whole=0),
            "helper": _entry(helper="no_colon"),
            "core needs question": _entry(question=None),
            "merged needs target": _entry(tier="merged", merged_into=None),
            "retired needs reason": _entry(tier="retired", retired_reason=None),
            "merged_into off a merged entry": _entry(merged_into="C-04"),
            "target missing": _entry(id="X-1", tier="merged", merged_into="NOPE"),
        }
        for label, bad in faults.items():
            with self.subTest(label):
                with self.assertRaises(kpi_registry.RegistryError):
                    kpi_registry.validate([good, bad] if bad["id"] != good["id"] else [bad])
        missing = {k: v for k, v in good.items() if k != "mcp"}
        with self.assertRaises(kpi_registry.RegistryError):
            kpi_registry.validate([missing])
        with self.assertRaises(kpi_registry.RegistryError):
            kpi_registry.validate([good, good])  # duplicate id
        with self.assertRaises(kpi_registry.RegistryError):
            kpi_registry.validate({"kpis": []})

    def test_unreadable_file_is_an_error_not_an_empty_registry(self):
        with mock.patch.object(kpi_registry, "REGISTRY_PATH", Path("/nonexistent/kpi_registry.json")):
            with self.assertRaises(kpi_registry.RegistryError):
                kpi_registry.load_registry()


class KpiRegistryDriftTests(unittest.TestCase):
    """The registry against docs/policy/kpis.md, which is the specification."""

    @classmethod
    def setUpClass(cls):
        text = POLICY.read_text(encoding="utf-8")
        cls.headings = re.findall(r"^### ([A-Z0-9-]+): (.+)$", text, re.M)

    def test_every_policy_heading_has_one_entry_with_the_same_name(self):
        ids = [i for i, _ in self.headings]
        self.assertEqual(len(ids), len(set(ids)), "an id has two headings")
        by_id = {k["id"]: k for k in kpi_registry.load_registry()}
        self.assertEqual(set(ids), set(by_id))
        for kid, name in self.headings:
            self.assertEqual(by_id[kid]["name"], name.strip(), kid)

    def test_policy_anchor_points_at_the_policy_page(self):
        for kpi in kpi_registry.load_registry():
            self.assertTrue(kpi["policy_anchor"].startswith("docs/policy/kpis.md#"), kpi["id"])

    def test_merged_targets_exist_and_are_not_themselves_merged(self):
        by_id = {k["id"]: k for k in kpi_registry.load_registry()}
        for kpi in kpi_registry.list_kpis(tier="merged"):
            self.assertIn(by_id[kpi["merged_into"]]["tier"], ("core", "registered"), kpi["id"])
            self.assertIn(kpi["id"], by_id[kpi["merged_into"]]["replaces"], kpi["id"])

    def test_catalog_keys_exist_and_cover_the_cube_answerable_kpis(self):
        keys = {e["key"] for e in ai_analytics_catalog.load_catalog()}
        with_key = {k["id"] for k in kpi_registry.load_registry() if k["catalog_key"]}
        self.assertEqual(with_key, CATALOG_KPIS)
        for kpi in kpi_registry.load_registry():
            if kpi["catalog_key"]:
                self.assertIn(kpi["catalog_key"], keys, kpi["id"])

    def test_every_helper_that_exists_imports(self):
        broken, pending, checked = [], [], 0
        for kpi in kpi_registry.load_registry():
            if kpi["tier"] in ("core", "registered") and not kpi["helper"]:
                self.assertEqual(kpi.get("helper_status"), "pending", f"{kpi['id']}: null helper not marked pending")
            if not kpi["helper"]:
                if kpi.get("helper_status") == "pending":
                    pending.append(kpi["id"])
                continue
            module_name, func = kpi["helper"].split(":")
            try:
                ok = callable(getattr(importlib.import_module(module_name), func, None))
            except ImportError:
                ok = False
            checked += 1
            if not ok:
                broken.append(kpi["id"])
        self.assertFalse(broken, f"helpers that do not import ({checked} checked, {len(pending)} pending): {broken}")

    def test_pending_helper_needs_a_null_helper(self):
        with self.assertRaises(kpi_registry.RegistryError):
            kpi_registry.validate([_entry(helper_status="pending")])
        with self.assertRaises(kpi_registry.RegistryError):
            kpi_registry.validate([_entry(helper_status="later", helper=None)])


class KpiHelpAndSearchTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        search.clear_fallback_cache()
        patcher = mock.patch.dict(os.environ, {"TYPESENSE_HOST": "", "TYPESENSE_API_KEY": ""})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(search.clear_fallback_cache)

    def test_help_page_renders_the_registry_with_an_anchor_per_kpi(self):
        self._login(str(self.base_admin_id))
        response = self.client.get("/help/kpis")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        for kpi in kpi_registry.load_registry():
            self.assertIn(f'id="{kpi["id"]}"', html, kpi["id"])
        self.assertIn("Coder Utilization Rate", html)
        self.assertIn('href="#C-21"', html)  # a merged id links to its survivor

    def test_help_page_stays_closed_to_a_coder(self):
        self._login(str(self.base_coder_id))
        self.assertEqual(self.client.get("/help/kpis").status_code, 403)

    def test_kpi_documents_cover_the_registry(self):
        docs = search._kpi_docs()
        self.assertEqual(len(docs), len(kpi_registry.load_registry()))
        doc = next(d for d in docs if d["id"] == "kpi:O-UNK")
        self.assertEqual((doc["kind"], doc["url"]), ("kpi", "/help/kpis#O-UNK"))
        self.assertEqual(doc["roles"], ["data_manager", "admin"])
        self.assertEqual(doc["keywords"].split()[:3], ["O-UNK", "outcome", "coding"])
        self.assertIn("Cause of death unknown", doc["body"])
        self.assertIn("kpi", search.KINDS)

    def test_typo_in_a_kpi_name_finds_it_for_admins_not_coders(self):
        admin_hits = search.search(self.base_admin_user, "coder utilisation rate")
        hit = next(r for r in admin_hits if r["kind"] == "kpi")
        self.assertEqual((hit["title"], hit["url"]), ("Coder Utilization Rate", "/help/kpis#C-21"))
        coder_hits = search.search(self.base_coder_user, "coder utilisation rate")
        self.assertNotIn("kpi", [r["kind"] for r in coder_hits])
