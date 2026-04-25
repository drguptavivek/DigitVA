"""Admin route sections.

The admin blueprint is owned by :mod:`app.routes.admin`; this package imports
the focused route modules that attach endpoints and request guards to it.
"""


def register_admin_sections() -> None:
    from app.routes.admin_sections import authorization  # noqa: F401
    from app.routes.admin_sections import access_grants  # noqa: F401
    from app.routes.admin_sections import activity  # noqa: F401
    from app.routes.admin_sections import cod_buckets  # noqa: F401
    from app.routes.admin_sections import data_sync  # noqa: F401
    from app.routes.admin_sections import field_mapping  # noqa: F401
    from app.routes.admin_sections import icd10_browser  # noqa: F401
    from app.routes.admin_sections import languages  # noqa: F401
    from app.routes.admin_sections import odk_connections  # noqa: F401
    from app.routes.admin_sections import project_forms  # noqa: F401
    from app.routes.admin_sections import project_pis  # noqa: F401
    from app.routes.admin_sections import project_sites  # noqa: F401
    from app.routes.admin_sections import projects  # noqa: F401
    from app.routes.admin_sections import shell  # noqa: F401
    from app.routes.admin_sections import sites  # noqa: F401
    from app.routes.admin_sections import users  # noqa: F401
