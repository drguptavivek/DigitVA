"""Possible-duplicate check (phase 6, digitva-vzk.11).

Part of the web intake service split (bead digitva-r8nh.12); the public
module is ``app.services.web_intake_service``, which re-exports every name.
Code that tests patch on that module is read back through ``facade()``.
"""
from __future__ import annotations

from app.models import (
    VaDeathRegister,
    VaUsers,
)
from app.services import (
    register_duplicate_service,
)
from app.services.register_duplicate_service import DUPLICATE_CANDIDATES_MAX
from app.services.web_intake.scope import (
    _worklist_scope,
)


def possible_duplicates(user: VaUsers, case: VaDeathRegister, scope=None) -> list[dict]:
    """Cases in *user*'s worklist reach that may be the same death as *case*.

    A warning for the interviewer, never a block and never a merge: flagging
    stays a person's decision (decisions 6 and 14). The caller has already
    checked *user* may see *case* (``get_death``). Rules in
    ``register_duplicate_service``. Each candidate carries what tells a person
    whether it is the same death (name, date of death, village, age, sex,
    informant, previous interviewer, who reported the death); the candidates are only cases inside
    *scope* (default: *user*'s worklist reach), so nothing of any other case is
    returned (docs/policy/web-intake.md, "Duplicate and cancel flags"). ``village`` is
    the village or ward of the candidate's recorded address, None when empty
    (never the org unit, which comes as ``unit_name``).
    """
    if scope is None:
        scope = _worklist_scope(user)
    rows = register_duplicate_service.possible_duplicate_rows([case.death_id], scope, per_case=DUPLICATE_CANDIDATES_MAX)
    return [
        {
            "death_id": str(row.death_id),
            "unique_id": row.unique_id,
            "unit_name": row.unit_name,
            "state": row.status,
            "score": round(float(row.score), 2),
            "deceased_name": row.deceased_name,
            "date_of_death": row.date_of_death.isoformat() if row.date_of_death else None,
            "village": row.address_village_ward or None,
            "age_years": row.age_years,
            "sex": row.deceased_sex,
            "informant_name": row.informant_name,
            "previous_interviewer_name": row.interviewer_name,
            "reported_by_name": row.registrant_name,
        }
        for row in rows
    ]
