---
title: SmartVA Symptom KB
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# SmartVA Symptom KB

This folder is a symptom-by-symptom knowledge base for the current `smart-va-pipeline` behavior.

Each document starts from one WHO symptom family, then traces it forward through:

1. WHO questionnaire fields
2. PHMRC-style intermediate variables
3. symptom-stage variables
4. tariff-applied SmartVA features

Use this folder when the question is:

- which WHO fields actually survive into SmartVA
- which fields are retained as separate SmartVA signals
- which fields collapse together before tariff application
- which fields are transformed into bucketed or thresholded features
- which symptom families differ across adult, child, and neonate

Related current-state background:

- [SmartVA Analysis](../../current-state/smartva-analysis.md)
- [SmartVA Keyword And Free-Text Processing](../../current-state/smartva-keyword-processing.md)

## Symptom Documents

- [Agentic Tracing Instructions](agentic-tracing-instructions.md)
- [WHO_2022_VA_SOCIAL Category / Subcategory Inventory](who-2022-va-social-subcategory-inventory.md)
- [Uncategorized And System Fields](uncategorized-system-fields.md)
- [SmartVA Trace QA Review](trace-qa-review.md)
- [SmartVA Trace Summary Matrix](trace-summary-matrix.md)
- [Adult WHO To SmartVA Gap Audit](adult-who-to-smartva-gap-audit.md)
- [Child WHO To SmartVA Gap Audit](child-who-to-smartva-gap-audit.md)
- [Neonate WHO To SmartVA Gap Audit](neonate-who-to-smartva-gap-audit.md)
- [Cross Age WHO To SmartVA Gap Matrix](cross-age-who-to-smartva-gap-matrix.md)
- [Interview Details](interview-details-interview.md)
- [Demographic General](demographic-general.md)
- [Duration Of Illness](duration-of-illness.md)
- [Nutrition](nutrition.md)
- [Fever](fever.md)
- [Cough](cough.md)
- [Diarrhea](diarrhea.md)
- [Breathing Difficulty](breathing-difficulty.md)
- [Chest Pain](chest-pain.md)
- [Vomiting](vomiting.md)
- [Abdominal Pain](abdominal-pain.md)
- [Protruding Abdomen](protruding-abdomen.md)
- [Mass Abdomen](mass-abdomen.md)
- [Urine Problems](urine-problems.md)
- [Swallowing](swallowing.md)
- [Headache](headache.md)
- [Smell Or Taste](smell-taste.md)
- [Mental Confusion](mental-confusion.md)
- [Stiff Neck](stiff-neck.md)
- [Lumps](lumps.md)
- [Skin Other](skin-other.md)
- [Neonatal Feeding](neonatal-feeding.md)
- [Neonatal Physical Abnormality](neonatal-physical-abnormality.md)
- [Neonatal Unresponsive](neonatal-unresponsive.md)
- [Neonatal Period General](neonatal-period-general.md)
- [Neonatal Cry](neonatal-cry.md)
- [Neonatal Birth Condition](neonatal-birth-condition.md)
- [Neonatal Birth Weight](neonatal-birth-weight.md)
- [Neonatal Fetal Movement](neonatal-fetal-movement.md)
- [Neonatal Delivery](neonatal-delivery.md)
- [Neonatal Danger Signs](neonatal-danger-signs.md)
- [Neonatal Period Physical Abnormalities](neonatal-period-physical-abnormalities.md)
- [Neonatal Baby Mother](neonatal-baby-mother.md)
- [Neonatal Blue At Birth](neonatal-blue-at-birth.md)
- [Rash](rash.md)
- [Ulcers](ulcers.md)
- [Convulsions](convulsions.md)
- [Unconsciousness](unconsciousness.md)
- [Paralysis](paralysis.md)
- [Jaundice](jaundice.md)
- [Swelling](swelling.md)
- [Medical History](medical-history.md)
- [Health History Neonate](health-history-neonate.md)
- [Risk Factors](risk-factors.md)
- [Maternal General](maternal-general.md)
- [Maternal Antenatal](maternal-antenatal.md)
- [Maternal Delivery](maternal-delivery.md)
- [Health Service Treatment](health-service-treatment.md)
- [Health Service HCW Cause Of Death](health-service-hcw-cod.md)
- [Health Service Mother Related](health-service-mother-related.md)
- [Death Registration](death-registration.md)
- [Medical Certificates](medical-certs.md)
- [Medical Documents](medical-documents.md)
- [Death Documents](death-documents.md)
- [Interviewer Final Comment](iv-final.md)
- [Social Autopsy](social-autopsy.md)
- [Maternal Periods Delivery Abortion](maternal-periods-delivery-abortion.md)
- [Injuries](injuries.md)

## Reading Notes

- `retained` means the WHO concept survives as its own SmartVA feature.
- `transformed` means the WHO answer is bucketed or thresholded before tariff application.
- `collapsed` means multiple WHO inputs converge to the same downstream SmartVA feature.
- `ignored` means the WHO concept does not appear as a first-class SmartVA feature in the current pipeline.

## Scope

These notes describe the current implementation only. They do not describe ideal behavior or propose fixes.
