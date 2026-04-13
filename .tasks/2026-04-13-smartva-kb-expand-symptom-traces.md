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
