"""PENDING_STATES is the awaiting + in-coding buckets (docs/policy/kpis.md)."""

import pytest

from app.services.workflow.definition import (
    ALL_WORKFLOW_STATES,
    CODER_READY_POOL_STATES,
    CODER_READY_POOL_STATES_SQL,
    CODING_BUCKET_AWAITING,
    CODING_BUCKET_IN_CODING,
    PENDING_STATES,
    PENDING_STATES_SQL,
    WORKFLOW_CODING_BUCKETS,
)


def test_pending_states_are_the_awaiting_and_in_coding_buckets():
    expected = {
        s
        for s, b in WORKFLOW_CODING_BUCKETS.items()
        if b in (CODING_BUCKET_AWAITING, CODING_BUCKET_IN_CODING)
    }
    assert len(PENDING_STATES) == 6
    assert set(PENDING_STATES) == expected


@pytest.mark.parametrize("state", PENDING_STATES)
def test_every_pending_state_is_a_real_workflow_state(state):
    assert state in ALL_WORKFLOW_STATES
    assert f"'{state}'" in PENDING_STATES_SQL


def test_ready_pool_is_inside_pending_and_has_sql_form():
    assert CODER_READY_POOL_STATES <= set(PENDING_STATES)
    assert CODER_READY_POOL_STATES_SQL == "('ready_for_coding')"
