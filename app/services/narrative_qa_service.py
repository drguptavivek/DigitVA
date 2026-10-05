"""Narrative Quality Assessment fields: the one source for the web form, the
save route and the API workspace.

``key`` is the POST body key of ``/api/v1/va/<sid>/narrative-qa`` and the
``va_nqa_<key>`` column; each option ``value`` is a stored score point.
"""

NARRATIVE_QA_FIELDS = [
    {
        "key": "length",
        "label": "Q1. Length of Narrative",
        "options": [
            {"value": 1, "label": "< 3 sentences"},
            {"value": 2, "label": "3–5 sentences"},
            {"value": 3, "label": "> 5 sentences"},
        ],
    },
    {
        "key": "pos_symptoms",
        "label": "Q2. Number of Positive Symptoms",
        "options": [
            {"value": 1, "label": "< 3 symptoms"},
            {"value": 2, "label": "3–5 symptoms"},
            {"value": 3, "label": "> 5 symptoms"},
        ],
    },
    {
        "key": "neg_symptoms",
        "label": "Q3. Presence of Negative Symptoms",
        "options": [
            {"value": 0, "label": "Absent"},
            {"value": 1, "label": "Present"},
        ],
    },
    {
        "key": "chronology",
        "label": "Q4. Chronology of Events",
        "options": [
            {"value": 0, "label": "Cannot be established"},
            {"value": 1, "label": "Can be established"},
        ],
    },
    {
        "key": "doc_review",
        "label": "Q5. Document Review",
        "options": [
            {"value": 0, "label": "Not present / Inconclusive"},
            {"value": 1, "label": "Provides useful data"},
        ],
    },
    {
        "key": "comorbidity",
        "label": "Q6. Comorbidities / Risk Factors",
        "options": [
            {"value": 0, "label": "Not present"},
            {"value": 1, "label": "Present"},
        ],
    },
]

#: The highest score the six answers can add up to.
NARRATIVE_QA_MAX_SCORE = sum(max(o["value"] for o in f["options"]) for f in NARRATIVE_QA_FIELDS)


def narrative_qa_allowed_values() -> dict[str, frozenset[int]]:
    """``{key: allowed values}`` in question order."""
    return {
        field["key"]: frozenset(option["value"] for option in field["options"])
        for field in NARRATIVE_QA_FIELDS
    }
