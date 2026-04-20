from pathlib import Path

from app.services.icd10_2019_2_service import (
    DEFAULT_ICD10_2019_2_CSV_PATH,
    import_icd10_2019_2_from_csv,
)


def va_mapping_icd(csv_path: str | Path = DEFAULT_ICD10_2019_2_CSV_PATH):
    """Backward-compatible wrapper for ICD reference loading.

    Older setup code called this helper to refresh the ICD catalog. The
    authoritative runtime catalog is now `mas_icd10_2019_2`, so this function
    delegates to the ICD-10 2019 master import instead of rebuilding
    `va_icd_codes`.
    """

    return import_icd10_2019_2_from_csv(csv_path)
