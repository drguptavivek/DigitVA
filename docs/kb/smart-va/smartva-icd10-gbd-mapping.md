---
title: SmartVA ICD10 And GBD Mapping
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-17
---

# SmartVA ICD10 And GBD Mapping

This note documents the current source-backed crosswalk in the vendored
`smartva-analyze` package.

The mapping lineage is:

- internal SmartVA cause selection -> reported `cause34`
- reported `cause34` -> ICD10-like code
- reported `cause34` -> GBD level 1 group

Important scope limits:

- `vendor/smartva-analyze` implements `GBD level 1` only.
- There is no `GBD level 2` mapping in the package.
- There is no `GBD level 3` mapping in the package.
- The package does not implement a separate direct `ICD10 -> GBD` crosswalk.
- `UU1` and `UU2` appear in the ICD table, but they are not standard ICD-10 codes.

Source of truth:

- `vendor/smartva-analyze/src/smartva/data/icds.py`
- `vendor/smartva-analyze/src/smartva/data/gbd_causes.py`

Current counts:

- Adult rows: `35`
- Child rows: `22`
- Neonate rows: `7`
- Total rows: `64`
- Distinct ICD-like codes across all rows: `48`

## Mapping Table

| Module | SmartVA cause34 | ICD10 | GBD level 1 code | GBD level 1 name |
|---|---|---|---|---|
| adult | AIDS | B24 | A | Communicable, maternal, neonatal and nutritional diseases |
| adult | Bite of Venomous Animal | X27 | C | Injuries |
| adult | Breast Cancer | C50 | B | Non-communicable diseases |
| adult | Cervical Cancer | C53 | B | Non-communicable diseases |
| adult | Cirrhosis | K74 | B | Non-communicable diseases |
| adult | Colorectal Cancer | C18 | B | Non-communicable diseases |
| adult | Diabetes | E14 | B | Non-communicable diseases |
| adult | Diarrhea/Dysentery | A09 | A | Communicable, maternal, neonatal and nutritional diseases |
| adult | Drowning | W74 | C | Injuries |
| adult | Epilepsy | G40 | B | Non-communicable diseases |
| adult | Esophageal Cancer | C15 | B | Non-communicable diseases |
| adult | Falls | W19 | C | Injuries |
| adult | Fires | X09 | C | Injuries |
| adult | Homicide | Y09 | C | Injuries |
| adult | Leukemia/Lymphomas | C96 | B | Non-communicable diseases |
| adult | Lung Cancer | C34 | B | Non-communicable diseases |
| adult | Malaria | B54 | A | Communicable, maternal, neonatal and nutritional diseases |
| adult | Maternal | O95 | A | Communicable, maternal, neonatal and nutritional diseases |
| adult | Other Cardiovascular Diseases | I99 | B | Non-communicable diseases |
| adult | Other Infectious Diseases | B99 | A | Communicable, maternal, neonatal and nutritional diseases |
| adult | Other Injuries | X58 | C | Injuries |
| adult | Other Non-communicable Diseases | UU1 | B | Non-communicable diseases |
| adult | Pneumonia | J22 | A | Communicable, maternal, neonatal and nutritional diseases |
| adult | Poisonings | X49 | C | Injuries |
| adult | Prostate Cancer | C61 | B | Non-communicable diseases |
| adult | Chronic Kidney Disease | N18 | B | Non-communicable diseases |
| adult | Road Traffic | V89 | C | Injuries |
| adult | Stomach Cancer | C16 | B | Non-communicable diseases |
| adult | Stroke | I64 | B | Non-communicable diseases |
| adult | Suicide | X84 | C | Injuries |
| adult | TB | A16 | A | Communicable, maternal, neonatal and nutritional diseases |
| adult | Chronic Respiratory | J44 | B | Non-communicable diseases |
| adult | Ischemic Heart Disease | I24 | B | Non-communicable diseases |
| adult | Other Cancers | C76 | B | Non-communicable diseases |
| adult | Undetermined | R99 | X | Undetermined |
| child | AIDS | B24 | A | Communicable, maternal, neonatal and nutritional diseases |
| child | Bite of Venomous Animal | X27 | C | Injuries |
| child | Diarrhea/Dysentery | A09 | A | Communicable, maternal, neonatal and nutritional diseases |
| child | Drowning | W74 | C | Injuries |
| child | Encephalitis | G04 | A | Communicable, maternal, neonatal and nutritional diseases |
| child | Falls | W19 | C | Injuries |
| child | Fires | X09 | C | Injuries |
| child | Hemorrhagic fever | A99 | A | Communicable, maternal, neonatal and nutritional diseases |
| child | Malaria | B54 | A | Communicable, maternal, neonatal and nutritional diseases |
| child | Measles | B05 | A | Communicable, maternal, neonatal and nutritional diseases |
| child | Meningitis | G03 | A | Communicable, maternal, neonatal and nutritional diseases |
| child | Childhood Cancer | C76 | B | Non-communicable diseases |
| child | Childhood Cardiovascular Diseases | I99 | B | Non-communicable diseases |
| child | Other Defined Causes of Child Deaths | UU2 | B | Non-communicable diseases |
| child | Digestive Diseases | K92 | B | Non-communicable diseases |
| child | Other Infectious Diseases | B99 | A | Communicable, maternal, neonatal and nutritional diseases |
| child | Pneumonia | J22 | A | Communicable, maternal, neonatal and nutritional diseases |
| child | Poisonings | X49 | C | Injuries |
| child | Road Traffic | V89 | C | Injuries |
| child | Sepsis | A41 | A | Communicable, maternal, neonatal and nutritional diseases |
| child | Homicide | Y09 | C | Injuries |
| child | Undetermined | R99 | X | Undetermined |
| neonate | Birth asphyxia | P21 | A | Communicable, maternal, neonatal and nutritional diseases |
| neonate | Congenital malformation | Q89 | B | Non-communicable diseases |
| neonate | Neonatal Meningitis/Sepsis | P36 | A | Communicable, maternal, neonatal and nutritional diseases |
| neonate | Neonatal Pneumonia | P23 | A | Communicable, maternal, neonatal and nutritional diseases |
| neonate | Preterm Delivery | P07 | A | Communicable, maternal, neonatal and nutritional diseases |
| neonate | Stillbirth | P95 | A | Communicable, maternal, neonatal and nutritional diseases |
| neonate | Undetermined | R99 | X | Undetermined |
