from pathlib import Path
from tempfile import NamedTemporaryFile

import sqlalchemy as sa

from app import db
from app.models import MasIcd1020192
from app.services.va_mapping.va_mapping_08_icd import va_mapping_icd
from tests.base import BaseTestCase


class TestVaMappingIcdService(BaseTestCase):
    def test_va_mapping_icd_delegates_to_master_icd_import(self):
        with NamedTemporaryFile("w", suffix=".csv", delete=False) as tmp:
            tmp.write(
                "\n".join(
                    [
                        "code,title,node_type,semantic_level,parent_code,chapter_code,chapter_title,block_code,block_title,three_character_code,three_character_title,has_children,is_leaf,is_three_character_code,is_detailed_code,is_coding_selectable,sex_selectable,age_group_selectable,policy_status,restriction_note",
                        "A00,Cholera,category,three_character,,I,Infectious diseases,A00-A09,Intestinal infectious diseases,A00,Cholera,false,true,true,false,,,,unreviewed,",
                    ]
                )
            )
            csv_path = Path(tmp.name)

        try:
            db.session.execute(sa.delete(MasIcd1020192))
            db.session.commit()

            result = va_mapping_icd(csv_path)

            self.assertEqual(result.total_rows, 1)
            row = db.session.get(MasIcd1020192, "A00")
            self.assertIsNotNone(row)
            self.assertEqual(row.title, "Cholera")
        finally:
            csv_path.unlink(missing_ok=True)
