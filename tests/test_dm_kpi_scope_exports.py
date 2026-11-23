"""dm_kpi_scope keeps every name the route modules and tests reach it by,
whichever module defines it (digitva-r8nh.16, slice 2a)."""

import pytest

from app.routes.api.dm_kpi import dm_kpi_scope

EXPORTED = [
    "DmScope",
    "GRANT_PROJECT_JOINS",
    "GRANT_PROJECT_SQL",
    "CLOCK_JOIN_SQL",
    "NOT_DEMO_OUTPUT_SQL",
    "local_day_start",
    "clock_day_sql",
    "clock_tz_sql",
    "in_last_days_sql",
    "clock_params",
    "bucket_flow_by_day",
    "dm_scope",
    "cached_kpi",
    "_cache_key",
    "bust_dm_kpi_cache",
    "bp",
    "cache",
    "grant_cache",
    "dm_grant_scope",
    "_IN_ODK_SQL",
    "_NOT_DUPLICATE_SQL",
    "_CODED_STATES",
]


@pytest.mark.parametrize("name", EXPORTED)
def test_dm_kpi_scope_exports(name):
    assert hasattr(dm_kpi_scope, name)
