Status: pending
Priority: medium
Created: 2026-04-13
Goal: Continue expanding `docs/kb/smart-va/` so each remaining WHO symptom-family question group has its own forward-trace knowledge document.

Context:
- The SmartVA KB now covers fever, cough, diarrhea, breathing difficulty, rash, convulsions, unconsciousness, jaundice, and swelling.
- Remaining symptom families still need the same current-state treatment: WHO fields -> PHMRC-style variable -> symptom-stage variable -> tariff-applied feature.
- The writeup should keep using `smart-va-pipeline` terminology and relative links.

References:
- `docs/kb/smart-va/README.md`
- `docs/kb/smart-va/fever.md`
- `docs/kb/smart-va/cough.md`
- `docs/kb/smart-va/diarrhea.md`
- `docs/kb/smart-va/breathing-difficulty.md`
- `docs/kb/smart-va/rash.md`
- `docs/kb/smart-va/convulsions.md`
- `docs/kb/smart-va/unconsciousness.md`
- `docs/kb/smart-va/jaundice.md`
- `docs/kb/smart-va/swelling.md`
- `vendor/smartva-analyze/src/smartva/data/who_data.py`
- `vendor/smartva-analyze/src/smartva/data/*_pre_symptom_data.py`
- `vendor/smartva-analyze/src/smartva/data/*_symptom_data.py`
- `vendor/smartva-analyze/src/smartva/data/*_tariff_data.py`

Expected Scope:
- Add more symptom documents one-by-one for the remaining WHO symptom groups.
- Update `docs/kb/smart-va/README.md` as each new document is added.
- Keep cautious wording where the WHO adapter path is less explicit than the downstream symptom model.

Completed in this batch:
- `docs/kb/smart-va/medical-history.md` for WHO `Id10125` through `Id10144`
- `docs/kb/smart-va/risk-factors.md` for WHO `Id10411` through `Id10414` and `Id10487`
- `docs/kb/smart-va/chest-pain.md` for the adult WHO chest-pain family
- `docs/kb/smart-va/lumps.md` for WHO `Id10254` through `Id10257`
- `docs/kb/smart-va/skin-other.md` for WHO `Id10237`, `Id10238`, `Id10239`, `Id10240`, and `Id10242` through `Id10246`
- `docs/kb/smart-va/neonatal-physical-abnormality.md` for WHO `Id10277` through `Id10279`
- `docs/kb/smart-va/neonatal-unresponsive.md` for WHO `Id10281` through `Id10283`
- `docs/kb/smart-va/neonatal-period-general.md` for WHO `Id10354` and `Id10367`
- `docs/kb/smart-va/neonatal-cry.md` for WHO `Id10104` through `Id10107`
- `docs/kb/smart-va/neonatal-birth-condition.md` for WHO `Id10109` through `Id10116`
- `docs/kb/smart-va/neonatal-birth-weight.md` for WHO `Id10363`, `Id10365`, and `Id10366`
- `docs/kb/smart-va/neonatal-fetal-movement.md` for WHO `Id10376` and `Id10377`
- `docs/kb/smart-va/neonatal-delivery.md` for WHO `Id10369`, `Id10382` through `Id10385`, `Id10387` through `Id10389`, and `Id10403` through `Id10405`
- `docs/kb/smart-va/neonatal-danger-signs.md` for WHO `Id10284`, `Id10286` through `Id10289`
- `docs/kb/smart-va/neonatal-blue-at-birth.md` for WHO `Id10406`
- `docs/kb/smart-va/maternal-periods-delivery-abortion.md` for WHO `Id10302`, `Id10303`, `Id10305`, `Id10306`, `Id10308`, `Id10310`, `Id10312`, `Id10314`, `Id10333`, and `Id10334`
- `docs/kb/smart-va/who-2022-va-social-subcategory-inventory.md` for the DB-backed category/subcategory baseline of `WHO_2022_VA_SOCIAL`
- `docs/kb/smart-va/demographic-general.md` for `vademographicdetails/general`
- `docs/kb/smart-va/neonatal-period-physical-abnormalities.md` for `vaneonatalperioddetails/physical_abnormalities` with WHO `Id10370` through `Id10373`
- `docs/kb/smart-va/duration-of-illness.md` for `vageneralsymptoms/duration_of_illness` with WHO `Id10120` through `Id10123`
- `docs/kb/smart-va/interview-details-interview.md` for `vainterviewdetails/interview`
- `docs/kb/smart-va/neonatal-baby-mother.md` for `vaneonatalperioddetails/baby_mother` with WHO `Id10391`, `Id10393`, `Id10395`, `Id10396`, `Id10397`, `Id10398`, `Id10399`, `Id10400`, `Id10401`, and `Id10402`
- `docs/kb/smart-va/injuries.md` for `vainjuriesdetails/default` with WHO `Id10077` through `Id10100`
