"""Drift guard for the golden coding-rule vectors the phone is tested against (digitva-r8nh.25).

Regenerates scripts/export_coding_rule_vectors.py from the server code and requires the committed JSON to match.
Fails when a server rule changes without the vectors (and so the phone tests) being refreshed."""

import json

from scripts.export_coding_rule_vectors import OUTPUT, build_vectors, dump_vectors


def test_committed_vectors_equal_a_regeneration():
    assert OUTPUT.read_text(encoding="utf-8") == dump_vectors(build_vectors())


def test_vectors_cover_each_branch_the_phone_mirrors():
    vectors = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert {c["status"] for c in vectors["allowability"]} == {"ok", "blocked", "age_confirm"}
    assert {c["group"] for c in vectors["age_group"]} == {None, "neonate", "infant", "child", "adult"}
    assert {c["expected"]["outcome"] for c in vectors["underlying_cause"]} == {"ok", "blocked", "age_confirm"}
    assert any(c["expression"] is None for c in vectors["expression"])
    assert {c["length"] for c in vectors["expression"]} >= {256, 257}
    assert vectors["limits"]["expression_max_length"] == 256
