"""Make the WHO_2022_VA field mapping cover every DigitVA layer (digitva-l2dg).

Owner decisions 2026-11-26 (docs/policy/va-form-project-configuration.md,
"One field mapping for every layer"): the layer switches decide which
questions a web or Collect form asks, so the ``mas_field_display_config`` rows
of ``WHO_2022_VA`` and ``WHO_2022_VA_SOCIAL`` must both map every layer's
fields. For each of the two form types this:

1. inserts the rows it is missing, by ``(form_type_id, field_id)`` (never a
   duplicate, never an update of an existing row): the 29 ``sa*`` social
   autopsy rows and 79 uncategorised ODK helper rows ``WHO_2022_VA_SOCIAL``
   already had (frozen below as of 2026-11-26, not copied from the database,
   which may have no SOCIAL form type or an edited one), the 11 ``equity``
   rows and the 19 ``doris_support_whova_2022`` rows;
2. sets only the decided columns of the named shared fields: ``Id10023``
   unflagged (``is_pii`` false, ``pii_type`` NULL; DORIS needs the death date
   for every coder); ``Id10010c`` ``pii_type`` ``staff_id``; ``Id10073``
   ``short_label``, ``full_label`` and ``field_type``; ``Id10186``
   ``subcategory_code`` ``diarrhoea``; ``Id10233``-``Id10236``
   ``display_order`` 10-40. An already-present ``social_group`` or
   ``vulnerable_group*`` row is flagged ``is_pii`` (its ``pii_type`` kept when
   set), never unflagged;
3. adds the ``social_autopsy`` category (order, display config, its
   ``social-autopsy`` subcategory) and the ``vademographicdetails`` /
   ``equity`` subcategory where missing, so the inserted rows render;
4. adds the answer labels (``mas_choice_mappings``) of the 36 select fields
   of those layers (17 ``sa*``, 11 equity, 8 DORIS-support; 168 labels), so
   coders see labels, not raw codes (owner 2026-11-26). The labels are the
   DigitVA engine's own (frozen below), the values the web and Collect forms
   store, never ``WHO_2022_VA_SOCIAL``'s ODK labels. A missing
   ``(field_id, choice_value)`` is inserted; an existing one is never
   changed, so a ``WHO_2022_VA_SOCIAL`` ODK label in use (``sa01`` ``6`` is
   "Others" there, "None" in the engine) and any value the engine does not
   emit stay as they are.

A form type that does not exist, or has no field rows yet (an unseeded
install: ``flask seed run`` seeds it from the workbooks, which already hold
these rows and labels), is skipped. Counts are logged. Every inserted or changed row gets
``updated_at = now()``, which moves the PII-set version other workers compare
(``field_mapping_service._pii_config_version``); the other mapping caches are
per process, so restart the app and Celery workers after upgrading.

Recovery: before any change, in the same transaction, every existing
``mas_field_display_config`` row of both form types is copied to
``_mig_bak_field_display_config_f3c9d1a7b5e2`` and every existing
``mas_choice_mappings`` row of both form types for the 36 labelled fields to
``_mig_bak_choice_mappings_f3c9d1a7b5e2`` (both kept after the upgrade), and
the category and choice rows this upgrade inserts are listed in
``_mig_f3c9d1a7b5e2_inserted``. The upgrade fails if any of the three tables
already exists. Downgrade deletes the listed rows, replaces the field rows of
every form type present in the backup with the backup's rows exactly
(``config_id`` included; nothing references ``config_id``), replaces both form
types' choice rows of the 36 fields with the choice backup's rows exactly
(``choice_id`` included; nothing references it), and drops the three tables.
A downgrade therefore also discards any mapping edit made to those form types,
and any choice edit to those fields, after the upgrade. To restore by hand
without a downgrade::

    BEGIN;
    DELETE FROM mas_field_display_config
     WHERE form_type_id IN (SELECT DISTINCT form_type_id
                              FROM _mig_bak_field_display_config_f3c9d1a7b5e2);
    INSERT INTO mas_field_display_config
    SELECT * FROM _mig_bak_field_display_config_f3c9d1a7b5e2;
    -- Only the labels this upgrade added (keeps any later choice edit):
    DELETE FROM mas_choice_mappings
     WHERE choice_id IN (SELECT row_id FROM _mig_f3c9d1a7b5e2_inserted
                          WHERE table_name = 'mas_choice_mappings');
    COMMIT;

The choice backup restores the 36 fields' rows exactly as they were (delete
those fields' rows of both form types, then ``INSERT INTO mas_choice_mappings
SELECT * FROM _mig_bak_choice_mappings_f3c9d1a7b5e2``), as the downgrade does.

Take a database backup before upgrading on staging or production.

Revision ID: f3c9d1a7b5e2
Revises: e7a4c2f9b1d3
Create Date: 2026-11-26
"""
import logging
from decimal import Decimal

import sqlalchemy as sa
from alembic import op

revision = "f3c9d1a7b5e2"
down_revision = "e7a4c2f9b1d3"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

# Hardcoded allowlist: the only form types this migration reads or writes.
# Interpolated into the backup's CREATE TABLE AS, which takes no bind params.
FORM_TYPE_CODES = ("WHO_2022_VA", "WHO_2022_VA_SOCIAL")
BACKUP = "_mig_bak_field_display_config_f3c9d1a7b5e2"
CHOICE_BACKUP = "_mig_bak_choice_mappings_f3c9d1a7b5e2"
LEDGER = "_mig_f3c9d1a7b5e2_inserted"
# Table -> primary key column of the inserted rows the ledger may name.
LEDGER_TABLES = {
    "mas_category_order": "category_order_id",
    "mas_category_display_config": "category_display_config_id",
    "mas_subcategory_order": "subcategory_order_id",
    "mas_choice_mappings": "choice_id",
}

EQUITY_PII_FIELDS = (
    "social_group",
    "vulnerable_group",
    "vulnerable_group_child_no_care",
    "vulnerable_group_female_head",
    "vulnerable_group_elderly_alone",
    "vulnerable_group_gender_minority",
    "vulnerable_group_custody",
)
EQUITY_PII_TYPE = "identifier"

ID10073_LABEL = "(Id10073) [National identification number of deceased]"
SKIN_RASH_ORDER = {"Id10233": 10, "Id10234": 20, "Id10235": 30, "Id10236": 40}

# (field_id, category_code, subcategory_code, short_label, full_label, field_type, display_order)
SOCIAL_LAYER_ROWS = [
    ('sa01', 'social_autopsy', 'social-autopsy', '1. Did the deceased have any health insurance?', '1. Did the deceased have any health insurance?', 'select_one', '10.00'),
    ('sa06', 'social_autopsy', 'social-autopsy', '2. Place of death', '2. Place of death', 'select_one', '20.00'),
    ('sa06_a', 'social_autopsy', 'social-autopsy', '2.1 Please specify the other place of death', '2.1 Please specify the other place of death', 'text', '30.00'),
    ('sa02', 'social_autopsy', 'social-autopsy', '3. Was any health care sought for the illness that led to death?', '3. Was any health care sought for the illness that led to death?', 'select_one', '40.00'),
    ('sa03', 'social_autopsy', 'social-autopsy', '4. If No health care was sought or treatment provided as per the advise, what were the reasons for the same?', '4. If No health care was sought or treatment provided as per the advise, what were the reasons for the same?', 'select_multiple', '50.00'),
    ('sa04', 'social_autopsy', 'social-autopsy', '4.1 Please specify the other reasons', '4.1 Please specify the other reasons', 'text', '60.00'),
    ('sa05', 'social_autopsy', 'social-autopsy', '5. If yes, type of first consultation', '5. If yes, type of first consultation', 'select_one', '70.00'),
    ('sa05_a', 'social_autopsy', 'social-autopsy', '5.1 Please specify the other type of first consultation', '5.1 Please specify the other type of first consultation', 'text', '80.00'),
    ('sa07', 'social_autopsy', 'social-autopsy', '6. What transport was used to reach HCF from home', '6. What transport was used to reach HCF from home', 'select_one', '90.00'),
    ('sa07_a', 'social_autopsy', 'social-autopsy', '6.1 Please specify the other transport used to reach HCF from home', '6.1 Please specify the other transport used to reach HCF from home', 'text', '100.00'),
    ('sa09', 'social_autopsy', 'social-autopsy', '7. How many HCF did you take the patient', '7. How many HCF did you take the patient', 'integer', '110.00'),
    ('sa10', 'social_autopsy', 'social-autopsy', '8. Was the patient referred to another health facility?', '8. Was the patient referred to another health facility?', 'select_one', '120.00'),
    ('sa11', 'social_autopsy', 'social-autopsy', '9. What was the reason for referral?', '9. What was the reason for referral?', 'select_multiple', '130.00'),
    ('sa12', 'social_autopsy', 'social-autopsy', '10. Did the patient go to the referred institution?', '10. Did the patient go to the referred institution?', 'select_one', '140.00'),
    ('sa08', 'social_autopsy', 'social-autopsy', '11. In case of referral to higher center, transport used', '11. In case of referral to higher center, transport used', 'select_one', '150.00'),
    ('sa13', 'social_autopsy', 'social-autopsy', '12.1. Enter the time taken to make the decision to seek healthcare (in ${sa_tu13})', '12.1. Enter the time taken to make the decision to seek healthcare', 'text', '170.00'),
    ('sa_tu13', 'social_autopsy', 'social-autopsy', '12. Time taken to make the decision to seek healthcare', '12. Time taken to make the decision to seek healthcare', 'select_one', '171.00'),
    ('sa14', 'social_autopsy', 'social-autopsy', '13.1. Enter the time taken to make transport arrangement (in ${sa_tu14})', '13.1. Enter the time taken to make transport arrangement (in ${sa_tu14})', 'text', '190.00'),
    ('sa_tu14', 'social_autopsy', 'social-autopsy', '13. Time taken to make transport arrangement', '13. Time taken to make transport arrangement', 'select_one', '191.00'),
    ('sa15', 'social_autopsy', 'social-autopsy', '14.1. Enter the time taken to reach first HCF/physician consultation', '14.1. Enter the time taken to reach first HCF/physician consultation', 'text', '210.00'),
    ('sa_tu15', 'social_autopsy', 'social-autopsy', '14. Units - Time taken to reach first HCF/physician consultant', '14. Units - Time taken to reach first HCF/physician consultant', 'select_one', '212.00'),
    ('sa16', 'social_autopsy', 'social-autopsy', '15.1. Enter the time taken for the doctor to attend the patient', '15.1. Enter the time taken for the doctor to attend the patient', 'text', '230.00'),
    ('sa_tu16', 'social_autopsy', 'social-autopsy', '15. Units - Time taken for the doctor to attend the patient', '15. Units - Time taken for the doctor to attend the patient', 'select_one', '232.00'),
    ('sa17', 'social_autopsy', 'social-autopsy', '16.1. Enter the time taken for the initiation of the treatment or referral to higher center (in ${sa_tu17})', '16.1. Enter the time taken for the initiation of the treatment or referral to higher center (in ${sa_tu17})', 'text', '250.00'),
    ('sa_tu17', 'social_autopsy', 'social-autopsy', '16. Units - Time taken for the initiation of the treatment or referral to higher center', '16. Units - Time taken for the initiation of the treatment or referral to higher center', 'select_one', '252.00'),
    ('sa18', 'social_autopsy', 'social-autopsy', '17.1. Enter the time taken to reach the HCF where he/she died (in ${sa_tu18})', '17.1. Enter the time taken to reach the HCF where he/she died (in ${sa_tu18})', 'text', '270.00'),
    ('sa_tu18', 'social_autopsy', 'social-autopsy', '17. Units- Time taken to reach the HCF where he/she died', '17. Units - Time taken to reach the HCF where he/she died', 'select_one', '272.00'),
    ('sa19', 'social_autopsy', 'social-autopsy', '18.1. Time of Death', '18.1. Time of Death', 'text', '280.00'),
    ('sa_tu19', 'social_autopsy', 'social-autopsy', '18. Units -  Time of Death', '18. Units - Time of Death', 'select_one', '290.00'),
    ('age_adult', None, None, "[Enter adult's age in years:]", "[Enter adult's age in years:]", 'integer', '0.00'),
    ('age_child_days', None, None, "[Enter child's age in days:]", "[Enter child's age in days:]", 'integer', '0.00'),
    ('age_child_months', None, None, "[Enter child's age in months:]", "[Enter child's age in months:]", 'integer', '0.00'),
    ('age_child_unit', None, None, "How old was the child? [Enter child's age in:]", "How old was the child? [Enter child's age in:]", 'select_one', '0.00'),
    ('age_child_years', None, None, "[Enter child's age in years:]", "[Enter child's age in years:]", 'integer', '0.00'),
    ('ageInDaysNeonate', None, None, 'Age in days', 'Age in days', 'calculate', '0.00'),
    ('ageInMonthsByYear', None, None, 'Age in Months', 'Age in Months', 'calculate', '0.00'),
    ('ageInMonthsRemain', None, None, None, None, 'calculate', '0.00'),
    ('ageInYearsRemain', None, None, None, None, 'calculate', '0.00'),
    ('audit', None, None, None, None, 'audit', '0.00'),
    ('confirm_inst', None, None, 'I have reviewed the essential information above and would like to proceed with the form.', 'I have reviewed the essential information above and would like to proceed with the form.', 'trigger', '0.00'),
    ('deviceid', None, None, None, None, 'deviceid', '0.00'),
    ('ds_available', None, None, 'Is there any death summary / certificate document (images) available for the deceased?', 'Is there any death summary / certificate document (images) available for the deceased?', 'select_one', '0.00'),
    ('ds_count', None, None, 'How many images for death summary / certificate document? (Max: 05)', 'How many images for death summary / certificate document? (Max: 05)', 'integer', '0.00'),
    ('finalAgeInYears', None, None, 'Final Age in Years', 'Final Age in Years', 'calculate', '0.00'),
    ('Id10020', None, None, '(Id10020) Is the date of birth known?', '(Id10020) Is the date of birth known?', 'select_one', '0.00'),
    ('Id10022', None, None, '(Id10022) Is the date of death known?', '(Id10022) Is the date of death known?', 'select_one', '0.00'),
    ('Id10023_a', None, None, '(Id10023_a) When did (s)he die?', '(Id10023_a) When did (s)he die?', 'date', '0.00'),
    ('Id10023_b', None, None, '(Id10023_b) When did (s)he die?', '(Id10023_b) When did (s)he die?', 'date', '0.00'),
    ('Id10051', None, None, '(Id10051) [Is there a need to collect additional demographic data on the deceased?]', '(Id10051) [Is there a need to collect additional demographic data on the deceased?]', 'select_one', '0.00'),
    ('Id10069_a', None, None, '(Id10069_a) Do you have a Death Certificate from the Civil Registry?', '(Id10069_a) Do you have a Death Certificate from the Civil Registry?', 'select_one', '0.00'),
    ('Id10071_check', None, None, '(Id10071_check) [Is the date of registration available?]', '(Id10071_check) [Is the date of registration available?]', 'select_one', '0.00'),
    ('Id10077_b', None, None, '(Id10077_b) [Interviewer click "OK" to confirm the answer: She/died less than or equal to 7 days after the accident]', '(Id10077_b) [Interviewer click "OK" to confirm the answer: She/died less than or equal to 7 days after the accident]', 'trigger', '0.00'),
    ('Id10120_0', None, None, '(Id10120_0) For how many days was (s)he ill before death?', '(Id10120_0) For how many days was (s)he ill before death?', 'integer', '0.00'),
    ('Id10120_1', None, None, '(Id10120_1) Days', '(Id10120_1) Days', 'integer', '0.00'),
    ('id10120_unit', None, None, '(id10120_unit) For how long was (s)he ill before death?', '(id10120_unit) For how long was (s)he ill before death?', 'select_one', '0.00'),
    ('Id10148_b', None, None, '(Id10148_b) [Enter how long the fever lasted in days]:', '(Id10148_b) [Enter how long the fever lasted in days]:', 'integer', '0.00'),
    ('Id10148_units', None, None, '(Id10148_units) How long did the fever last?', '(Id10148_units) How long did the fever last?', 'select_one', '0.00'),
    ('Id10154_a', None, None, '(Id10154_a) [Enter how long (s)he had a cough in days]:', '(Id10154_a) [Enter how long (s)he had a cough in days]:', 'integer', '0.00'),
    ('Id10154_units', None, None, '(Id10154_units) For how long did (s)he have a cough?', '(Id10154_units) For how long did (s)he have a cough?', 'select_one', '0.00'),
    ('Id10161_1', None, None, '(Id10161_1) [Enter how long the difficult breathing or breathlessness lasted in days]:', '(Id10161_1) [Enter how long the difficult breathing or breathlessness lasted in days]:', 'integer', '0.00'),
    ('id10161_unit', None, None, '(Id10161_unit) For how long did the difficulty breathing or breathlessness last?', '(Id10161_unit) For how long did the difficulty breathing or breathlessness last?', 'select_one', '0.00'),
    ('Id10167_b', None, None, '(Id10167_b) [Enter how long the fast breathing lasted in days]:', '(Id10167_b) [Enter how long the fast breathing lasted in days]:', 'integer', '0.00'),
    ('Id10167_units', None, None, '(Id10167_units) How long did the fast breathing last?', '(Id10167_units) How long did the fast breathing last?', 'select_one', '0.00'),
    ('Id10173', None, None, '(Id10173) During the illness that led to death did his/her breathing sound like any of the following:', '(Id10173) During the illness that led to death did his/her breathing sound like any of the following:', 'calculate', '0.00'),
    ('Id10178_unit', None, None, '(Id10178_unit) How long did the chest pain last?', '(Id10178_unit) How long did the chest pain last?', 'select_one', '0.00'),
    ('Id10182_a', None, None, '(Id10182_a) [Enter how long  (s)he have diarrhoea in days]:', '(Id10182_a) [Enter how long  (s)he have diarrhoea in days]:', 'integer', '0.00'),
    ('Id10182_units', None, None, '(Id10182_units) How long did (s)he have diarrhoea?', '(Id10182_units) How long did (s)he have diarrhoea?', 'select_one', '0.00'),
    ('Id10184_units', None, None, '(Id10184_units) How long before death did the diarrhoea start?', '(Id10184_units) How long before death did the diarrhoea start?', 'select_one', '0.00'),
    ('Id10190_units', None, None, '(Id10190_units) For how long did (s)he vomit?', '(Id10190_units) For how long did (s)he vomit?', 'select_one', '0.00'),
    ('id10196_unit', None, None, '(id10196_unit) For how long did (s)he have abdominal pain?', '(id10196_unit) For how long did (s)he have abdominal pain?', 'select_one', '0.00'),
    ('Id10197_a', None, None, '(Id10197_a) [Enter how long (s)he had  abdominal pain in days]:', '(Id10197_a) [Enter how long (s)he had  abdominal pain in days]:', 'integer', '0.00'),
    ('Id10201_a', None, None, '(Id10201_a) [Enter how long before death (s)he had a more than usually protruding abdomen in days]:', '(Id10201_a) [Enter how long before death (s)he had a more than usually protruding abdomen in days]:', 'integer', '0.00'),
    ('Id10201_unit', None, None, '(Id10201_unit) For how long before death did (s)he have a more than usually protruding abdomen?', '(Id10201_unit) For how long before death did (s)he have a more than usually protruding abdomen?', 'select_one', '0.00'),
    ('Id10205_a', None, None, '(Id10205_a) [Enter how long (s)he had a mass in the abdomen in days]:', '(Id10205_a) [Enter how long (s)he had a mass in the abdomen in days]:', 'integer', '0.00'),
    ('Id10205_unit', None, None, '(Id10205_unit) For how long did (s)he have a mass in the abdomen?', '(Id10205_unit) For how long did (s)he have a mass in the abdomen?', 'select_one', '0.00'),
    ('Id10209_a', None, None, '(Id10209_a) [Enter how long before death did (s)he have stiff or painful neck in days]:', '(Id10209_a) [Enter how long before death did (s)he have stiff or painful neck in days]:', 'integer', '0.00'),
    ('Id10209_units', None, None, '(Id10209_units) How long before death did s/he have a stiff or painful neck?', '(Id10209_units) How long before death did s/he have a stiff or painful neck?', 'select_one', '0.00'),
    ('Id10213_b', None, None, '(Id10213_b) [Enter how long (s)he had mental confusion in months]:', '(Id10213_b) [Enter how long (s)he had mental confusion in months]:', 'integer', '0.00'),
    ('Id10213_units', None, None, '(Id10213_units) How long did (s)he have mental confusion?', '(Id10213_units) How long did (s)he have mental confusion?', 'select_one', '0.00'),
    ('Id10216_a', None, None, '(Id10216_a) [Enter how long before death unconsciousness started in hours]?', '(Id10216_a) [Enter how long before death unconsciousness started in hours]?', 'integer', '0.00'),
    ('Id10216_units', None, None, '(Id10216_units) How long before death did unconsciousness start?', '(Id10216_units) How long before death did unconsciousness start?', 'select_one', '0.00'),
    ('Id10232_a', None, None, '(Id10232_a) [Enter how long the ulcer on the foot had pus in days]:', '(Id10232_a) [Enter how long the ulcer on the foot had pus in days]:', 'integer', '0.00'),
    ('Id10232_units', None, None, '(Id10232_units) How long  did the ulcer on the foot have pus?', '(Id10232_units) How long  did the ulcer on the foot have pus?', 'select_one', '0.00'),
    ('Id10248_a', None, None, '(Id10248_a) [Enter how long (s)he had puffiness of the face in days]:', '(Id10248_a) [Enter how long (s)he had puffiness of the face in days]:', 'integer', '0.00'),
    ('Id10248_units', None, None, '(Id10248_units) How long did (s)he have puffiness of the face?', '(Id10248_units) How long did (s)he have puffiness of the face?', 'select_one', '0.00'),
    ('Id10250_a', None, None, '(Id10250_a) [Enter how long the swelling lasted in days]:', '(Id10250_a) [Enter how long the swelling lasted in days]:', 'integer', '0.00'),
    ('Id10250_units', None, None, '(Id10250_units) How long did the swelling last?', '(Id10250_units) How long did the swelling last?', 'select_one', '0.00'),
    ('Id10253', None, None, '(Id10253) Did (s)he have lumps anywhere else on the body?', '(Id10253) Did (s)he have lumps anywhere else on the body?', 'select_one', '0.00'),
    ('Id10262_a', None, None, '(Id10262_a) [Enter how long before death (s)he had difficulty or pain in swallowing in days]:', '(Id10262_a) [Enter how long before death (s)he had difficulty or pain in swallowing in days]:', 'integer', '0.00'),
    ('Id10262_units', None, None, '(Id10262_units) For how long did (s)he have difficulty or pain in swallowing?', '(Id10262_units) For how long did (s)he have difficulty or pain in swallowing?', 'select_one', '0.00'),
    ('Id10266_a', None, None, '(Id10266_a) [Enter how long (s)he had the yellow discoloration in days]:', '(Id10266_a) [Enter how long (s)he had the yellow discoloration in days]:', 'integer', '0.00'),
    ('Id10266_units', None, None, '(Id10266_units) For how long did (s)he have the yellow discoloration?', '(Id10266_units) For how long did (s)he have the yellow discoloration?', 'select_one', '0.00'),
    ('Id10274_a', None, None, '(Id10274_a) How many days after birth did the baby stop suckling?', '(Id10274_a) How many days after birth did the baby stop suckling?', 'integer', '0.00'),
    ('Id10274_b', None, None, '(Id10274_b) [Enter how long after birth  the baby stopped suckling in days]:', '(Id10274_b) [Enter how long after birth  the baby stopped suckling in days]:', 'integer', '0.00'),
    ('Id10274_units', None, None, '(Id10274_units) How long after birth did the baby stop suckling?', '(Id10274_units) How long after birth did the baby stop suckling?', 'select_one', '0.00'),
    ('Id10313', None, None, '(Id10313) Did she die after delivering a baby?', '(Id10313) Did she die after delivering a baby?', 'select_one', '0.00'),
    ('isAdult1', None, None, 'The deceased person is an Adult', 'The deceased person is an Adult', 'calculate', '0.00'),
    ('isAdult2', None, None, 'The deceased person is an Adult', 'The deceased person is an Adult', 'calculate', '0.00'),
    ('isChild1', None, None, 'The deceased person is a Child', 'The deceased person is a Child', 'calculate', '0.00'),
    ('isChild2', None, None, 'The deceased person is a Child', 'The deceased person is a Child', 'calculate', '0.00'),
    ('isNeonatal1', None, None, 'The deceased person is a Neonate', 'The deceased person is a Neonate', 'calculate', '0.00'),
    ('isNeonatal2', None, None, 'The deceased person is a Neonate', 'The deceased person is a Neonate', 'calculate', '0.00'),
    ('md_available', None, None, 'Are there any medical documents available related to the deceased?', 'Are there any medical documents available related to the deceased?', 'select_one', '0.00'),
    ('md_count', None, None, 'How many images for medical documents? (Max: 30)', 'How many images for medical documents? (Max: 30)', 'integer', '0.00'),
    ('start', None, None, None, None, 'start', '0.00'),
    ('survey_block', None, None, 'Select Survey Block', 'Select Survey Block', 'select_one', '0.00'),
    ('telephonic_consent', None, None, 'Please attach or record the telephonic consent', 'Please attach or record the telephonic consent', 'audio', '0.00'),
    ('today', None, None, None, None, 'today', '0.00'),
]

# (field_id, category_code, subcategory_code, label, field_type, age_group, display_order)
LAYER_ROWS = [
    ('social_group', 'vademographicdetails', 'equity', 'Which of these groups did the deceased belong to?', 'select_one SOCIAL_GROUP', 'ALL', '63.01'),
    ('residence_type', 'vademographicdetails', 'equity', 'Was the place where the deceased usually lived rural, urban or an urban slum?', 'select_one RESIDENCE_TYPE', 'ALL', '63.02'),
    ('vulnerable_group', 'vademographicdetails', 'equity', 'Did any of these apply to the deceased? Tick all that apply.', 'select_multiple VULNERABLE_GROUP', 'ALL', '63.03'),
    ('vulnerable_group_child_no_care', 'vademographicdetails', 'equity', 'Was the deceased a child without parental care?', 'select_one EQUITY_YES_NO_DK_REF', 'ALL', '63.04'),
    ('vulnerable_group_female_head', 'vademographicdetails', 'equity', 'Was the deceased a widow or a woman heading the household alone?', 'select_one EQUITY_YES_NO_DK_REF', 'ALL', '63.05'),
    ('vulnerable_group_elderly_alone', 'vademographicdetails', 'equity', 'Was the deceased an older person living alone?', 'select_one EQUITY_YES_NO_DK_REF', 'ALL', '63.06'),
    ('vulnerable_group_gender_minority', 'vademographicdetails', 'equity', 'Was the deceased a transgender or gender-diverse person?', 'select_one EQUITY_YES_NO_DK_REF', 'ALL', '63.07'),
    ('vulnerable_group_custody', 'vademographicdetails', 'equity', 'Was the deceased in prison or custody at the time of death?', 'select_one EQUITY_YES_NO_DK_REF', 'ALL', '63.08'),
    ('health_coverage', 'vademographicdetails', 'equity', 'What health insurance did the deceased have? Tick all that apply.', 'select_multiple HEALTH_COVERAGE', 'ALL', '63.09'),
    ('refusal_age_group', 'vademographicdetails', 'equity', 'Age group of the deceased', 'select_one REFUSAL_AGE_GROUP', 'ALL', '63.10'),
    ('refusal_sex', 'vademographicdetails', 'equity', 'Sex of the deceased', 'select_one REFUSAL_SEX', 'ALL', '63.11'),
    ('dob_precision', 'vademographicdetails', 'general', 'Is the month and year, or only the year, of birth known?', 'select_one dob_precision', 'ALL', '21.10'),
    ('dob_month_year', 'vademographicdetails', 'general', 'In which month and year was the deceased born?', 'date', 'ALL', '21.20'),
    ('dob_year', 'vademographicdetails', 'general', 'In which year was the deceased born?', 'date', 'ALL', '21.30'),
    ('doris_mother_age', 'vaneonatalperioddetails', 'general', "How old was the baby's mother, in completed years, when the baby was born?", 'integer', 'N_C', '65.10'),
    ('doris_pregnancy_weeks', 'vaneonatalperioddetails', 'general', 'How many completed weeks long was the pregnancy? (only if known, e.g. from an antenatal card)', 'integer', 'N_C', '66.10'),
    ('doris_hours_survived', 'vaneonatalperioddetails', 'stillbirth', 'For how many hours did the baby live?', 'integer', 'N', '89.10'),
    ('Id10366_confirm', 'vaneonatalperioddetails', 'birth_weight', 'A birth weight of ${Id10366} g is unusual. Check the card and confirm the weight is in grammes.', 'acknowledge', 'N_C', '93.10'),
    ('doris_injury_date_known', 'vainjuriesdetails', 'default', 'Is the date of the injury known?', 'select_one injury_date_known', 'ALL', '118.10'),
    ('doris_injury_date', 'vainjuriesdetails', 'default', 'On what date was (s)he injured?', 'date', 'ALL', '118.20'),
    ('doris_injury_month_year', 'vainjuriesdetails', 'default', 'In which month and year was (s)he injured?', 'date', 'ALL', '118.30'),
    ('doris_injury_place', 'vainjuriesdetails', 'default', 'Where did the injury happen?', 'select_one injury_place', 'ALL', '118.40'),
    ('doris_injury_legal_war', 'vainjuriesdetails', 'default', 'Was the injury from police or legal action, or from war?', 'select_one legal_war', 'ALL', '118.50'),
    ('doris_surgery_performed', 'vahealthserviceutilisation', 'treatment', 'Did (s)he have an operation before death?', 'select_one YES_NO_DK_REF', 'ALL', '365.10'),
    ('doris_surgery_when', 'vahealthserviceutilisation', 'treatment', 'How long before death was the operation? (number)', 'integer', 'ALL', '365.20'),
    ('doris_surgery_when_unit', 'vahealthserviceutilisation', 'treatment', 'Unit', 'select_one time_unit', 'ALL', '365.30'),
    ('doris_surgery_type', 'vahealthserviceutilisation', 'treatment', 'What operation was done?', 'text', 'ALL', '365.40'),
    ('doris_surgery_reason', 'vahealthserviceutilisation', 'treatment', 'For what illness or condition was it done?', 'text', 'ALL', '365.50'),
    ('doris_autopsy_requested', 'vanarrationanddocuments', 'medical_certs', 'Was an autopsy (post-mortem examination) requested?', 'select_one YES_NO_DK_REF', 'ALL', '391.10'),
    ('doris_autopsy_findings', 'vanarrationanddocuments', 'medical_certs', 'Were the autopsy findings made available?', 'select_one YES_NO_DK_REF', 'ALL', '391.20'),
]


# The answer labels of every select field of the three layers, frozen from the
# DigitVA engine's composed definition (app/data/who-va-2022.composed.json,
# English, the `india` equity set the server serves) as of 2026-11-26: the
# values the web and Collect forms store. Not WHO_2022_VA_SOCIAL's ODK labels,
# which carry site-specific values. list name -> ((value, label), ...) in form order.
ENGINE_CHOICE_LISTS = {
    'sas01': (
        ('1', 'Private Cashless'),
        ('2', 'Private Reimbursement'),
        ('3', 'Ayushman Bharat'),
        ('4', 'State/Central Government'),
        ('5', 'Employee based(ESI/CGHS/Others)'),
        ('6', 'None'),
    ),
    'sas04': (
        ('1', 'Home'),
        ('2', 'HCF'),
        ('3', 'In transit'),
        ('4', 'Others'),
    ),
    'YES_NO': (
        ('yes', 'Yes'),
        ('no', 'No'),
    ),
    'sas02': (
        ('1', 'Died very soon'),
        ('2', 'Financial barrier'),
        ('3', 'Lack of transport'),
        ('4', 'Lack of people to help'),
        ('5', 'Health facility too far'),
        ('6', 'Others'),
    ),
    'sas03': (
        ('1', 'Home visit by physician'),
        ('2', 'Individual Practitioner'),
        ('3', 'Small hospital'),
        ('4', 'Medium Hospital'),
        ('5', 'Large hospital (Government/private medical colleges)'),
        ('6', 'Others'),
    ),
    'sas05': (
        ('1', 'Govt Ambulance'),
        ('2', 'Non- Govt Ambulance'),
        ('3', 'Own Motor Vehicle'),
        ('4', 'Own non-motor vehicle'),
        ('5', 'Hired Motor Vehicle'),
        ('6', 'Hired non-motor vehicle'),
        ('7', 'Physically carried'),
        ('8', 'Others'),
    ),
    'YES_NO_DK': (
        ('yes', 'Yes'),
        ('no', 'No'),
        ('DK', "Doesn't Know"),
    ),
    'sas07': (
        ('1', 'Lack of facility'),
        ('2', 'Specialist not available'),
        ('3', 'Financial constraints'),
        ('4', 'Patient/family decision'),
    ),
    'sas06': (
        ('1', 'Govt Ambulance'),
        ('2', 'Non- Govt Ambulance'),
        ('3', 'Own Motor Vehicle'),
        ('4', 'Own non-motor vehicle'),
        ('5', 'Physically carried'),
        ('6', 'Not Applicable'),
    ),
    'sa_tu': (
        ('minutes', 'Minutes'),
        ('hours', 'Hours'),
        ('days', 'Days'),
        ('na', 'Not Applicable'),
    ),
    'SOCIAL_GROUP': (
        ('sc', 'Scheduled Caste (SC)'),
        ('st', 'Scheduled Tribe (ST), including PVTG'),
        ('obc', 'Other Backward Class (OBC)'),
        ('general', 'None of these (general)'),
        ('dk', "Don't know"),
        ('ref', 'Prefer not to say'),
    ),
    'RESIDENCE_TYPE': (
        ('rural', 'Rural (village)'),
        ('urban', 'Urban (town or city)'),
        ('urban_slum', 'Urban slum or informal settlement'),
        ('dk', "Don't know"),
    ),
    'VULNERABLE_GROUP': (
        ('disability', 'A person with a disability (physical, sensory, intellectual or psychosocial)'),
        ('homeless', 'Homeless or destitute'),
        ('migrant', 'Migrant worker, seasonal or from another region'),
        ('displaced', 'Internally displaced person, refugee, asylum seeker or stateless'),
        ('poverty_programme', 'Enrolled in the national poverty or food-security programme (AAY or priority household ration card)'),
        ('none', 'None of these'),
        ('dk', "Don't know"),
        ('ref', 'Prefer not to say'),
    ),
    'EQUITY_YES_NO_DK_REF': (
        ('yes', 'Yes'),
        ('no', 'No'),
        ('dk', "Don't know"),
        ('ref', 'Prefer not to say'),
    ),
    'HEALTH_COVERAGE': (
        ('social_security', 'Social security health insurance'),
        ('government_scheme', 'A government health scheme (Ayushman Bharat PM-JAY or a state scheme)'),
        ('community_mutual', 'Mutual health organisation or community-based insurance'),
        ('employer', 'Other employer-based insurance'),
        ('private', 'Privately purchased commercial insurance'),
        ('other', 'Other'),
        ('none', 'No health insurance'),
        ('dk', "Don't know"),
        ('ref', 'Prefer not to say'),
    ),
    'REFUSAL_AGE_GROUP': (
        ('neonate', 'Neonate (under 28 days)'),
        ('child', 'Child (28 days to 14 years)'),
        ('15_49y', '15 to 49 years'),
        ('50_64y', '50 to 64 years'),
        ('65_plus', '65 years or older'),
        ('unknown', 'Unknown'),
    ),
    'REFUSAL_SEX': (
        ('male', 'Male'),
        ('female', 'Female'),
        ('unknown', 'Unknown'),
    ),
    'dob_precision': (
        ('month_year', 'Month and year known'),
        ('year', 'Only the year known'),
        ('neither', 'Neither known'),
    ),
    'injury_date_known': (
        ('full', 'Full date'),
        ('month_year', 'Month and year'),
        ('unknown', 'Not known'),
    ),
    'injury_place': (
        ('0', 'At home'),
        ('1', 'Residential institution'),
        ('2', 'School, other institution, public administration area'),
        ('3', 'Sports and athletics area'),
        ('4', 'Street and highway'),
        ('5', 'Trade and service area'),
        ('6', 'Industrial and construction area'),
        ('7', 'Farm'),
        ('8', 'Other place'),
        ('9', 'Unknown'),
    ),
    'legal_war': (
        ('legal', 'Police or legal action'),
        ('war', 'War'),
        ('neither', 'Neither'),
        ('dk', "Doesn't know"),
    ),
    'YES_NO_DK_REF': (
        ('yes', 'Yes'),
        ('no', 'No'),
        ('dk', "Doesn't know"),
        ('ref', 'Refused to answer'),
    ),
    'time_unit': (
        ('days', 'Days'),
        ('weeks', 'Weeks'),
        ('months', 'Months'),
        ('years', 'Years'),
    ),
}
# field_id -> its list in ENGINE_CHOICE_LISTS: the select fields of the sa*,
# equity and doris_support_whova_2022 rows above.
ENGINE_CHOICE_FIELDS = {
    'sa01': 'sas01',
    'sa06': 'sas04',
    'sa02': 'YES_NO',
    'sa03': 'sas02',
    'sa05': 'sas03',
    'sa07': 'sas05',
    'sa10': 'YES_NO_DK',
    'sa11': 'sas07',
    'sa12': 'YES_NO_DK',
    'sa08': 'sas06',
    'sa_tu13': 'sa_tu',
    'sa_tu14': 'sa_tu',
    'sa_tu15': 'sa_tu',
    'sa_tu16': 'sa_tu',
    'sa_tu17': 'sa_tu',
    'sa_tu18': 'sa_tu',
    'sa_tu19': 'sa_tu',
    'social_group': 'SOCIAL_GROUP',
    'residence_type': 'RESIDENCE_TYPE',
    'vulnerable_group': 'VULNERABLE_GROUP',
    'vulnerable_group_child_no_care': 'EQUITY_YES_NO_DK_REF',
    'vulnerable_group_female_head': 'EQUITY_YES_NO_DK_REF',
    'vulnerable_group_elderly_alone': 'EQUITY_YES_NO_DK_REF',
    'vulnerable_group_gender_minority': 'EQUITY_YES_NO_DK_REF',
    'vulnerable_group_custody': 'EQUITY_YES_NO_DK_REF',
    'health_coverage': 'HEALTH_COVERAGE',
    'refusal_age_group': 'REFUSAL_AGE_GROUP',
    'refusal_sex': 'REFUSAL_SEX',
    'dob_precision': 'dob_precision',
    'doris_injury_date_known': 'injury_date_known',
    'doris_injury_place': 'injury_place',
    'doris_injury_legal_war': 'legal_war',
    'doris_surgery_performed': 'YES_NO_DK_REF',
    'doris_surgery_when_unit': 'time_unit',
    'doris_autopsy_requested': 'YES_NO_DK_REF',
    'doris_autopsy_findings': 'YES_NO_DK_REF',
}


def _target_rows():
    """Every row this migration ensures, as insert parameters."""
    rows = []
    for field_id, category, subcategory, short_label, full_label, field_type, order in SOCIAL_LAYER_ROWS:
        rows.append({
            "field_id": field_id,
            "category_code": category,
            "subcategory_code": subcategory,
            "short_label": short_label,
            "full_label": full_label,
            "field_type": field_type,
            "age_group": None,
            # The sa* questions are flagged info on WHO_2022_VA_SOCIAL; the
            # uncategorised helpers are not.
            "is_info": category == "social_autopsy",
            "is_pii": False,
            "pii_type": None,
            "display_order": Decimal(order),
        })
    for field_id, category, subcategory, label, field_type, age_group, order in LAYER_ROWS:
        pii = field_id in EQUITY_PII_FIELDS
        rows.append({
            "field_id": field_id,
            "category_code": category,
            "subcategory_code": subcategory,
            "short_label": f"({field_id}) {label}",
            "full_label": label,
            "field_type": field_type,
            "age_group": age_group,
            "is_info": False,
            "is_pii": pii,
            "pii_type": EQUITY_PII_TYPE if pii else None,
            "display_order": Decimal(order),
        })
    return rows


def _choice_rows():
    """Every engine answer label this migration ensures, as insert parameters.

    ``display_order`` is 1-based in form order, as the workbook seed numbers it.
    """
    return [
        {"field_id": field_id, "choice_value": value, "choice_label": label, "display_order": order}
        for field_id, list_name in ENGINE_CHOICE_FIELDS.items()
        for order, (value, label) in enumerate(ENGINE_CHOICE_LISTS[list_name], start=1)
    ]


# One statement per form type: inserts the missing labels and lists each new
# row in the ledger. Never an update: an existing row (a WHO_2022_VA_SOCIAL
# ODK label in use, an admin edit) keeps its label, order and active flag.
INSERT_CHOICES = sa.text(
    "WITH inserted AS ("
    "INSERT INTO mas_choice_mappings (choice_id, form_type_id, field_id, choice_value, "
    "choice_label, display_order, is_active, synced_at, created_at, updated_at) "
    "SELECT gen_random_uuid(), :form_type_id, t.field_id, t.choice_value, t.choice_label, "
    "t.display_order, true, now(), now(), now() "
    "FROM unnest(CAST(:field_ids AS varchar[]), CAST(:choice_values AS varchar[]), "
    "CAST(:choice_labels AS varchar[]), CAST(:display_orders AS integer[])) "
    "AS t(field_id, choice_value, choice_label, display_order) "
    "ON CONFLICT ON CONSTRAINT uq_choice_form_type_field DO NOTHING RETURNING choice_id) "
    f"INSERT INTO {LEDGER} (table_name, row_id) "
    "SELECT 'mas_choice_mappings', choice_id FROM inserted"
)


def _insert_choices(bind, form_type_id):
    rows = _choice_rows()
    return bind.execute(INSERT_CHOICES, {
        "form_type_id": form_type_id,
        "field_ids": [row["field_id"] for row in rows],
        "choice_values": [row["choice_value"] for row in rows],
        "choice_labels": [row["choice_label"] for row in rows],
        "display_orders": [row["display_order"] for row in rows],
    }).rowcount


INSERT_FIELD = sa.text(
    "INSERT INTO mas_field_display_config (config_id, form_type_id, field_id, "
    "category_code, subcategory_code, short_label, full_label, summary_label, field_type, "
    "age_group, flip_color, is_info, summary_include, is_pii, pii_type, display_order, "
    "is_active, is_custom, created_at, updated_at) "
    "VALUES (gen_random_uuid(), :form_type_id, :field_id, :category_code, :subcategory_code, "
    ":short_label, :full_label, NULL, :field_type, :age_group, false, :is_info, false, "
    ":is_pii, :pii_type, :display_order, true, false, now(), now()) "
    "ON CONFLICT ON CONSTRAINT uq_field_config_form_type DO NOTHING"
)


def _count_rows(bind, form_type_id):
    return bind.execute(
        sa.text("SELECT count(*) FROM mas_field_display_config WHERE form_type_id = :ft"),
        {"ft": form_type_id},
    ).scalar()


def _update(bind, form_type_id, field_id, set_sql, changed_sql, params=None):
    """Set ``set_sql`` on one named field when ``changed_sql`` says it differs."""
    return bind.execute(
        sa.text(
            f"UPDATE mas_field_display_config SET {set_sql}, updated_at = now() "
            f"WHERE form_type_id = :ft AND field_id = :field_id AND ({changed_sql})"
        ),
        {"ft": form_type_id, "field_id": field_id, **(params or {})},
    ).rowcount


def _apply_named_decisions(bind, form_type_id):
    changed = 0
    changed += _update(
        bind, form_type_id, "Id10023",
        "is_pii = false, pii_type = NULL", "is_pii OR pii_type IS NOT NULL",
    )
    changed += _update(
        bind, form_type_id, "Id10010c",
        "pii_type = :pii_type", "pii_type IS DISTINCT FROM :pii_type", {"pii_type": "staff_id"},
    )
    changed += _update(
        bind, form_type_id, "Id10073",
        "short_label = :label, full_label = :label, field_type = :field_type",
        "short_label IS DISTINCT FROM :label OR full_label IS DISTINCT FROM :label "
        "OR field_type IS DISTINCT FROM :field_type",
        {"label": ID10073_LABEL, "field_type": "text"},
    )
    changed += _update(
        bind, form_type_id, "Id10186",
        "subcategory_code = :sub", "subcategory_code IS DISTINCT FROM :sub", {"sub": "diarrhoea"},
    )
    for field_id, order in SKIN_RASH_ORDER.items():
        changed += _update(
            bind, form_type_id, field_id,
            "display_order = :ord", "display_order IS DISTINCT FROM :ord", {"ord": Decimal(order)},
        )
    for field_id in EQUITY_PII_FIELDS:
        changed += _update(
            bind, form_type_id, field_id,
            "is_pii = true, pii_type = COALESCE(pii_type, :pii_type)", "NOT is_pii",
            {"pii_type": EQUITY_PII_TYPE},
        )
    return changed


def _record(bind, table, row_id):
    if row_id is not None:
        bind.execute(
            sa.text(f"INSERT INTO {LEDGER} (table_name, row_id) VALUES (:t, :id)"),
            {"t": table, "id": row_id},
        )
        return 1
    return 0


def _ensure_categories(bind, form_type_id):
    """Add the social_autopsy category and the equity subcategory if missing."""
    added = 0
    added += _record(bind, "mas_category_order", bind.execute(sa.text(
        "INSERT INTO mas_category_order (category_order_id, form_type_id, category_code, "
        "category_name, display_order, is_active) "
        "SELECT gen_random_uuid(), :ft, 'social_autopsy', 'Social Autopsy', "
        "COALESCE(max(display_order), 0) + 1, true FROM mas_category_order WHERE form_type_id = :ft "
        "HAVING NOT EXISTS (SELECT 1 FROM mas_category_order WHERE form_type_id = :ft "
        "AND category_code = 'social_autopsy') RETURNING category_order_id"
    ), {"ft": form_type_id}).scalar())
    added += _record(bind, "mas_category_display_config", bind.execute(sa.text(
        "INSERT INTO mas_category_display_config (category_display_config_id, form_type_id, "
        "category_code, display_label, nav_label, icon_name, display_order, render_mode, "
        "show_to_coder, show_to_reviewer, show_to_site_pi_datamanager, always_include, "
        "is_default_start, is_active, created_at, updated_at) "
        "SELECT gen_random_uuid(), :ft, 'social_autopsy', 'Social Autopsy', 'Social Autopsy', "
        "'fa-users', COALESCE(max(display_order), 0) + 1, 'table_sections', true, true, true, "
        "false, false, true, now(), now() FROM mas_category_display_config WHERE form_type_id = :ft "
        "HAVING NOT EXISTS (SELECT 1 FROM mas_category_display_config WHERE form_type_id = :ft "
        "AND category_code = 'social_autopsy') RETURNING category_display_config_id"
    ), {"ft": form_type_id}).scalar())
    # Named by code, as the workbook seed names every subcategory, so a
    # migrated database labels them as a fresh install and the offline
    # display pack do.
    for category, subcategory, name in (
        ("social_autopsy", "social-autopsy", "social-autopsy"),
        ("vademographicdetails", "equity", "equity"),
    ):
        added += _record(bind, "mas_subcategory_order", bind.execute(sa.text(
            "INSERT INTO mas_subcategory_order (subcategory_order_id, form_type_id, category_code, "
            "subcategory_code, subcategory_name, display_order, is_active, render_mode) "
            "SELECT gen_random_uuid(), :ft, :cat, :sub, :name, COALESCE(max(display_order), 0) + 1, "
            "true, 'default' FROM mas_subcategory_order WHERE form_type_id = :ft AND category_code = :cat "
            "HAVING NOT EXISTS (SELECT 1 FROM mas_subcategory_order WHERE form_type_id = :ft "
            "AND category_code = :cat AND subcategory_code = :sub) RETURNING subcategory_order_id"
        ), {"ft": form_type_id, "cat": category, "sub": subcategory, "name": name}).scalar())
    return added


def upgrade():
    bind = op.get_bind()
    codes = ", ".join(f"'{code}'" for code in FORM_TYPE_CODES)
    # Plain CREATE TABLE: an existing backup from an earlier attempt is never
    # overwritten; the upgrade stops instead.
    bind.execute(sa.text(
        f"CREATE TABLE {BACKUP} AS SELECT c.* FROM mas_field_display_config c "
        f"JOIN mas_form_types f ON f.form_type_id = c.form_type_id "
        f"WHERE f.form_type_code IN ({codes})"
    ))
    # The choice rows of the fields this upgrade labels; bound parameters need
    # an INSERT, so the table is created empty first.
    bind.execute(sa.text(
        f"CREATE TABLE {CHOICE_BACKUP} AS SELECT * FROM mas_choice_mappings WITH NO DATA"
    ))
    bind.execute(sa.text(
        f"INSERT INTO {CHOICE_BACKUP} SELECT c.* FROM mas_choice_mappings c "
        f"JOIN mas_form_types f ON f.form_type_id = c.form_type_id "
        f"WHERE f.form_type_code = ANY(:codes) AND c.field_id = ANY(:field_ids)"
    ), {"codes": list(FORM_TYPE_CODES), "field_ids": list(ENGINE_CHOICE_FIELDS)})
    bind.execute(sa.text(
        f"CREATE TABLE {LEDGER} (table_name varchar(64) NOT NULL, row_id uuid NOT NULL)"
    ))

    rows = _target_rows()
    for code in FORM_TYPE_CODES:
        form_type_id = bind.execute(
            sa.text("SELECT form_type_id FROM mas_form_types WHERE form_type_code = :code"),
            {"code": code},
        ).scalar()
        if form_type_id is None:
            log.info("l2dg | %s | form type absent, skipped", code)
            continue
        before = _count_rows(bind, form_type_id)
        if not before:
            log.info("l2dg | %s | no field rows yet (unseeded), skipped", code)
            continue
        # Target rows already present are left as they are; name them so a
        # database whose mapping differs from dev shows where.
        kept = sorted(bind.execute(
            sa.text(
                "SELECT field_id FROM mas_field_display_config "
                "WHERE form_type_id = :ft AND field_id = ANY(:ids)"
            ),
            {"ft": form_type_id, "ids": [row["field_id"] for row in rows]},
        ).scalars())
        if kept:
            log.info("l2dg | %s | already mapped, left as is: %s", code, ", ".join(kept))
        bind.execute(INSERT_FIELD, [{"form_type_id": form_type_id, **row} for row in rows])
        inserted = _count_rows(bind, form_type_id) - before
        changed = _apply_named_decisions(bind, form_type_id)
        categories = _ensure_categories(bind, form_type_id)
        choices = _insert_choices(bind, form_type_id)
        log.info(
            "l2dg | %s | field rows before=%d inserted=%d named-field updates=%d "
            "category rows added=%d choice labels added=%d",
            code, before, inserted, changed, categories, choices,
        )


def downgrade():
    bind = op.get_bind()
    for table, key in LEDGER_TABLES.items():
        bind.execute(sa.text(
            f"DELETE FROM {table} WHERE {key} IN "
            f"(SELECT row_id FROM {LEDGER} WHERE table_name = :t)"
        ), {"t": table})
    bind.execute(sa.text(
        f"DELETE FROM mas_field_display_config WHERE form_type_id IN "
        f"(SELECT DISTINCT form_type_id FROM {BACKUP})"
    ))
    bind.execute(sa.text(f"INSERT INTO mas_field_display_config SELECT * FROM {BACKUP}"))
    # The ledger removed the inserted labels; this also undoes any later edit
    # to the labelled fields' choices, as the field rows above.
    bind.execute(sa.text(
        "DELETE FROM mas_choice_mappings c USING mas_form_types f "
        "WHERE f.form_type_id = c.form_type_id AND f.form_type_code = ANY(:codes) "
        "AND c.field_id = ANY(:field_ids)"
    ), {"codes": list(FORM_TYPE_CODES), "field_ids": list(ENGINE_CHOICE_FIELDS)})
    bind.execute(sa.text(f"INSERT INTO mas_choice_mappings SELECT * FROM {CHOICE_BACKUP}"))
    op.drop_table(LEDGER)
    op.drop_table(CHOICE_BACKUP)
    op.drop_table(BACKUP)
