# Golden corpora: approved by the owner

All three sets are `"status": "approved"` (owner, 2026-10-30) and frozen. A change goes back to the owner: edit the JSON in `corpus/`, set it to `draft`, then re-record (README.md) and regenerate this file with `python3 scripts/icd11-golden/review.py`.

Counts: DORIS 173 certificates, postcoordination 44 stems with 47 built expressions, search 238 terms.

## DORIS certificates

Input is `group, sex, age or dates: Part I lines (top = immediate cause), Part II, blocks`.

| id | group | input | why | source |
|---|---|---|---|---|
| va-01-01 | adult | F P46Y: 1G40 Sepsis | Sepsis: single coded condition | VA cause VAs-01.01 Sepsis |
| va-01-02 | child | M P2Y: CA40.Z Pneumonia | Acute respiratory infection, including pneumonia: single coded condition | VA cause VAs-01.02 Acute respiratory infection, including pneumonia |
| va-01-03 | adult | M P38Y: 1C62.3Z AIDS stage 4 | HIV/AIDS related death: single coded condition | VA cause VAs-01.03 HIV/AIDS related death |
| va-01-04 | child | F P8M: 1A40.Z Acute watery diarrhoea | Diarrhoeal diseases: single coded condition | VA cause VAs-01.04 Diarrhoeal diseases |
| va-01-05 | adult | M P29Y: 1F40.Z Falciparum malaria | Malaria: single coded condition | VA cause VAs-01.05 Malaria |
| va-01-06 | child | F P2Y: 1F03.0 Measles | Measles: single coded condition | VA cause VAs-01.06 Measles |
| va-01-07 | adult | M P33Y: 1D01.0Z Bacterial meningitis | Meningitis and encephalitis: single coded condition | VA cause VAs-01.07 Meningitis and encephalitis |
| va-01-08 | adult | M P51Y: 1C13 Tetanus | Tetanus: single coded condition | VA cause VAs-01.08 Tetanus |
| va-01-09 | adult | M P55Y: 1B10.Z Pulmonary tuberculosis | Pulmonary tuberculosis: single coded condition | VA cause VAs-01.09 Pulmonary tuberculosis |
| va-01-10 | child | F P5M: 1C12.Z Whooping cough | Pertussis: single coded condition | VA cause VAs-01.10 Pertussis |
| va-01-11 | adult | F P27Y: 1D60.01 Ebola virus disease | Haemorrhagic fever: single coded condition | VA cause VAs-01.11 Haemorrhagic fever |
| va-01-12 | adult | M P19Y: 1D22 Severe dengue | Dengue fever: single coded condition | VA cause VAs-01.12 Dengue fever |
| va-01-13 | adult | M P71Y: RA01.0 COVID-19 | COVID-19: single coded condition | VA cause VAs-01.13 COVID-19 |
| va-01-99 | adult | F P24Y: 1A07 Typhoid fever | Unspecified infectious disease: single coded condition | VA cause VAs-01.99 Unspecified infectious disease |
| va-02-01 | adult | M P60Y: 2B61.Z Tongue cancer | Oral neoplasms: single coded condition | VA cause VAs-02.01 Oral neoplasms |
| va-02-02 | adult | M P63Y: 2B72.Z Stomach cancer | Digestive neoplasms: single coded condition | VA cause VAs-02.02 Digestive neoplasms |
| va-02-03 | adult | M P66Y: 2C25.Z Lung cancer | Respiratory neoplasms: single coded condition | VA cause VAs-02.03 Respiratory neoplasms |
| va-02-04 | adult | F P49Y: 2C60 Carcinoma of breast | Breast neoplasms: single coded condition | VA cause VAs-02.04 Breast neoplasms |
| va-02-05 | adult | F P52Y: 2C77.Z Cancer of cervix | Female reproductive neoplasms: single coded condition | VA cause VAs-02.05 Female reproductive neoplasms |
| va-02-06 | adult | M P74Y: 2C82.0 Prostate cancer | Male reproductive neoplasms: single coded condition | VA cause VAs-02.06 Male reproductive neoplasms |
| va-02-99 | adult | M P41Y: 2B33.4 Leukaemia | Other and unspecified neoplasms: single coded condition | VA cause VAs-02.99 Other and unspecified neoplasms |
| va-03-01 | adult | F P35Y: 3A00.Z Severe iron deficiency anaemia | Severe anaemia: single coded condition | VA cause VAs-03.01 Severe anaemia |
| va-03-02 | child | M P20M: 5B51 Severe wasting | Severe malnutrition: single coded condition | VA cause VAs-03.02 Severe malnutrition |
| va-03-03 | adult | F P58Y: 5A11 Diabetes | Diabetes mellitus: single coded condition | VA cause VAs-03.03 Diabetes mellitus |
| va-04-01 | adult | M P62Y: BA41.Z Heart attack | Acute cardiac disease: single coded condition | VA cause VAs-04.01 Acute cardiac disease |
| va-04-02 | adult | F P69Y: 8B11.5Z Stroke | Stroke: single coded condition | VA cause VAs-04.02 Stroke |
| va-04-03 | child | F P9Y: 3A51.2 Sickle cell crisis | Sickle cell with crisis: single coded condition | VA cause VAs-04.03 Sickle cell with crisis |
| va-04-99 | adult | M P57Y: BA00.Z High blood pressure | Other and unspecified cardiac disease: single coded condition | VA cause VAs-04.99 Other and unspecified cardiac disease |
| va-05-01 | adult | M P67Y: CA22.Z COPD | Chronic obstructive pulmonary disease (COPD): single coded condition | VA cause VAs-05.01 Chronic obstructive pulmonary disease (COPD) |
| va-05-02 | adult | F P44Y: CA23.0 Asthma | Asthma: single coded condition | VA cause VAs-05.02 Asthma |
| va-06-01 | adult | M P37Y: MD81.3 Acute abdomen | Acute abdomen: single coded condition | VA cause VAs-06.01 Acute abdomen |
| va-06-02 | adult | M P50Y: DB94.3 Alcoholic cirrhosis | Liver cirrhosis: single coded condition | VA cause VAs-06.02 Liver cirrhosis |
| va-07-01 | adult | M P64Y: GB61.5 End stage kidney disease | Renal failure: single coded condition | VA cause VAs-07.01 Renal failure |
| va-08-01 | adult | F P22Y: 8A66.Z Status epilepticus | Epilepsy: single coded condition | VA cause VAs-08.01 Epilepsy |
| va-09-01 | adult | F P26Y: JA01.Z Ruptured ectopic pregnancy ; blocks: MaternalDeath | Ectopic pregnancy: single coded condition | VA cause VAs-09.01 Ectopic pregnancy |
| va-09-02 | adult | F P20Y: JA00.06 Bleeding after abortion ; blocks: MaternalDeath | Abortion-related death: single coded condition | VA cause VAs-09.02 Abortion-related death |
| va-09-03 | adult | F P23Y: JA25 Eclampsia ; blocks: MaternalDeath | Pregnancy-induced hypertension: single coded condition | VA cause VAs-09.03 Pregnancy-induced hypertension |
| va-09-04 | adult | F P30Y: JA43.1 Bleeding after delivery ; blocks: MaternalDeath | Obstetric haemorrhage: single coded condition | VA cause VAs-09.04 Obstetric haemorrhage |
| va-09-05 | adult | F P19Y: JB04.Z Obstructed labour ; blocks: MaternalDeath | Obstructed labour: single coded condition | VA cause VAs-09.05 Obstructed labour |
| va-09-06 | adult | F P28Y: JB40.0 Puerperal sepsis ; blocks: MaternalDeath | Pregnancy-related sepsis: single coded condition | VA cause VAs-09.06 Pregnancy-related sepsis |
| va-09-07 | adult | F P25Y: JB64.0 Severe anaemia in pregnancy ; blocks: MaternalDeath | Anaemia of pregnancy: single coded condition | VA cause VAs-09.07 Anaemia of pregnancy |
| va-09-08 | adult | F P32Y: JB0A.0 Ruptured uterus ; blocks: MaternalDeath | Ruptured uterus: single coded condition | VA cause VAs-09.08 Ruptured uterus |
| va-10-01 | neonatal | M P2D: KA21.4Z Premature baby ; blocks: FetalOrInfantDeath | Prematurity or low birth weight: single coded condition | VA cause VAs-10.01 Prematurity or low birth weight |
| va-10-02 | neonatal | F PT10H: KB21.Z Birth asphyxia ; blocks: FetalOrInfantDeath | Birth asphyxia: single coded condition | VA cause VAs-10.02 Birth asphyxia |
| va-10-03 | neonatal | M P5D: KB24 Pneumonia in newborn | Neonatal pneumonia: single coded condition | VA cause VAs-10.03 Neonatal pneumonia |
| va-10-04 | neonatal | F P6D: KA60 Sepsis of newborn | Neonatal sepsis: single coded condition | VA cause VAs-10.04 Neonatal sepsis |
| va-10-05 | neonatal | M P9D: 1C15 Neonatal tetanus | Neonatal tetanus: single coded condition | VA cause VAs-10.05 Neonatal tetanus |
| va-10-06 | neonatal | F P1D: LA02.Z Spina bifida | Congenital malformation: single coded condition | VA cause VAs-10.06 Congenital malformation |
| va-10-99 | neonatal | M P3D: KA82.Z Brain bleed in newborn | Other and unspecified perinatal cause of death: single coded condition | VA cause VAs-10.99 Other and unspecified perinatal cause of death |
| va-11-01 | stillbirth | F : KD3B.1 Fresh stillbirth ; blocks: FetalOrInfantDeath | Fresh stillbirth: single coded condition | VA cause VAs-11.01 Fresh stillbirth |
| va-11-02 | stillbirth | M : KD3B.0 Macerated stillbirth ; blocks: FetalOrInfantDeath | Macerated stillbirth: single coded condition | VA cause VAs-11.02 Macerated stillbirth |
| va-12-01 | adult | M P28Y: NA02.Z Head injury **due to** PA01 Motorcycle rider hit by a truck ; blocks: MannerOfDeath | Road traffic accident: injury above its external cause, manner 1 | VA cause VAs-12.01 Road traffic accident |
| va-12-02 | adult | M P35Y: ND37 Multiple injuries **due to** PA10 Pedestrian hit on a village track ; blocks: MannerOfDeath | Other transport accident: injury above its external cause, manner 1 | VA cause VAs-12.02 Other transport accident |
| va-12-03 | adult | M P72Y: NC72.Z Broken thigh bone **due to** PA61 Fell from a roof ; blocks: MannerOfDeath | Accidental fall: injury above its external cause, manner 1 | VA cause VAs-12.03 Accidental fall |
| va-12-04 | child | M P4Y: NF08.1 Drowned in a pond **due to** PA90 Drowning in a pond ; blocks: MannerOfDeath | Accidental drowning and submersion: injury above its external cause, manner 1 | VA cause VAs-12.04 Accidental drowning and submersion |
| va-12-05 | adult | F P31Y: NE2Z Burns **due to** PB10 Kitchen fire ; blocks: MannerOfDeath | Accidental exposure to smoke, fire and flames: injury above its external cause, manner 1 | VA cause VAs-12.05 Accidental exposure to smoke, fire and flames |
| va-12-06 | adult | M P40Y: NE61 Snake bite poisoning **due to** PA78 Snake bite ; blocks: MannerOfDeath | Contact with venomous animals and plants: injury above its external cause, manner 1 | VA cause VAs-12.06 Contact with venomous animals and plants |
| va-12-07 | adult | M P36Y: NE61 Poisoning **due to** PB28 Accidental pesticide poisoning ; blocks: MannerOfDeath | Accidental poisoning and exposure to noxious substances: injury above its external cause, manner 1 | VA cause VAs-12.07 Accidental poisoning and exposure to noxious substances |
| va-12-08 | adult | F P21Y: NF05 Asphyxia by hanging **due to** PC71 Hanged herself ; blocks: MannerOfDeath | Intentional self-harm: injury above its external cause, manner 2 | VA cause VAs-12.08 Intentional self-harm |
| va-12-09 | adult | M P33Y: ND56.1 Gunshot wound **due to** PD50 Assault ; blocks: MannerOfDeath | Assault: injury above its external cause, manner 3 | VA cause VAs-12.09 Assault |
| va-12-10 | adult | M P48Y: NF08.4 Electric shock **due to** PJ00 Struck by lightning ; blocks: MannerOfDeath | Exposure to force of nature: injury above its external cause, manner 1 | VA cause VAs-12.10 Exposure to force of nature |
| va-12-99 | adult | M P45Y: NC72.Z Fracture of femur ; blocks: MannerOfDeath | Other and unspecified external cause of death: single coded condition | VA cause VAs-12.99 Other and unspecified external cause of death |
| va-99 | adult | F P91Y: MG2A Old age | Cause of death unknown: single coded condition | VA cause VAs-99 Cause of death unknown |
| chain-pneumonia-hiv | adult | M P36Y: CA40.Z Pneumonia [P10D] **due to** 1C62.Z HIV disease [P3Y] | Two lines: pneumonia due to HIV | VA cause VAs-01.02 Acute respiratory infection, including pneumonia; VA cause VAs-01.03 HIV/AIDS related death |
| chain-tb-hiv | adult | F P34Y: 1B10.Z Pulmonary tuberculosis [P6M] **due to** 1C62.Z HIV [P4Y] | Two lines: tuberculosis due to HIV (HIV/TB code interplay) | VA cause VAs-01.09 Pulmonary tuberculosis; VA cause VAs-01.03 HIV/AIDS related death |
| chain-mi-diabetes | adult | M P66Y: BA41.Z Heart attack [PT3H] **due to** BA52.Z Blocked coronary arteries [P5Y] **due to** 5A11 Diabetes [P12Y] | Three lines: MI due to coronary atherosclerosis due to diabetes | VA cause VAs-04.01 Acute cardiac disease; VA cause VAs-03.03 Diabetes mellitus |
| chain-stroke-hypertension | adult | F P68Y: 8B00.Z Brain haemorrhage [P2D] **due to** BA00.Z High blood pressure [P15Y] | Two lines: intracerebral haemorrhage due to hypertension | VA cause VAs-04.02 Stroke; VA cause VAs-04.99 Other and unspecified cardiac disease |
| chain-sepsis-pneumonia | adult | M P59Y: 1G40 Sepsis [P3D] **due to** CA40.Z Pneumonia [P7D] | Two lines: sepsis due to pneumonia | VA cause VAs-01.01 Sepsis; VA cause VAs-01.02 Acute respiratory infection, including pneumonia |
| chain-renal-diabetes | adult | F P61Y: GB61.5 Kidney failure [P2Y] **due to** 5A11 Diabetes [P14Y] | Two lines: chronic kidney disease due to diabetes | VA cause VAs-07.01 Renal failure; VA cause VAs-03.03 Diabetes mellitus |
| chain-cirrhosis-hepatic-failure | adult | M P47Y: DB99.7 Liver failure [P1M] **due to** DB94.3 Alcoholic cirrhosis [P6Y] | Two lines: hepatic failure due to alcoholic cirrhosis | VA cause VAs-06.02 Liver cirrhosis |
| chain-cancer-metastasis | adult | F P55Y: 2D70 Lung metastases [P4M] **due to** 2C60 Breast cancer [P3Y] | Two lines: lung metastasis due to breast cancer | VA cause VAs-02.04 Breast neoplasms; VA cause VAs-02.99 Other and unspecified neoplasms |
| chain-heart-failure-hypertension | adult | M P73Y: BD10 Heart failure [P6M] **due to** BA01 Hypertensive heart disease [P10Y] | Two lines: congestive heart failure due to hypertensive heart disease | VA cause VAs-04.01 Acute cardiac disease; VA cause VAs-04.99 Other and unspecified cardiac disease |
| chain-copd-pneumonia | adult | M P70Y: CA40.Z Pneumonia [P5D] **due to** CA22.Z COPD [P8Y] | Two lines: pneumonia due to COPD | VA cause VAs-05.01 Chronic obstructive pulmonary disease (COPD); VA cause VAs-01.02 Acute respiratory infection, including pneumonia |
| chain-malaria-anaemia | adult | F P27Y: 3A9Z Severe anaemia [P4D] **due to** 1F40.Z Malaria [P10D] | Two lines: severe anaemia due to falciparum malaria | VA cause VAs-03.01 Severe anaemia; VA cause VAs-01.05 Malaria |
| chain-diarrhoea-dehydration | child | F P14M: 5C70.0 Dehydration [P1D] **due to** 1A40.Z Diarrhoea [P3D] | Two lines: dehydration due to acute diarrhoea in a child | VA cause VAs-01.04 Diarrhoeal diseases |
| chain-measles-pneumonia | child | M P3Y: CA40.Z Pneumonia [P6D] **due to** 1F03.0 Measles [P12D] | Two lines: pneumonia due to measles | VA cause VAs-01.06 Measles; VA cause VAs-01.02 Acute respiratory infection, including pneumonia |
| chain-neonatal-sepsis-preterm | neonatal | F P4D: KA60 Sepsis of newborn [P2D] **due to** KA21.4Z Prematurity [P4D] ; blocks: FetalOrInfantDeath | Two lines: neonatal sepsis due to prematurity | VA cause VAs-10.04 Neonatal sepsis; VA cause VAs-10.01 Prematurity or low birth weight |
| chain-asphyxia-rds | neonatal | M PT20H: KB23.0Z Respiratory distress syndrome [PT18H] **due to** KB21.Z Birth asphyxia [PT20H] ; blocks: FetalOrInfantDeath | Two lines: respiratory distress syndrome due to birth asphyxia | VA cause VAs-10.02 Birth asphyxia |
| chain-pph-atony | maternal | F P29Y: JA43.1 Bleeding after delivery [PT4H] **due to** JB02.2 Uterine atony [PT6H] ; blocks: MaternalDeath | Two lines: haemorrhage after delivery due to uterine inertia | VA cause VAs-09.04 Obstetric haemorrhage |
| chain-sepsis-obstructed-labour | maternal | F P21Y: JB40.0 Puerperal sepsis [P6D] **due to** JB04.Z Obstructed labour [P9D] ; blocks: MaternalDeath | Two lines: puerperal sepsis due to obstructed labour | VA cause VAs-09.06 Pregnancy-related sepsis; VA cause VAs-09.05 Obstructed labour |
| chain-eclampsia-preeclampsia | maternal | F P24Y: JA25 Fits in pregnancy [PT5H] **due to** JA24.1 Severe pre-eclampsia [P3D] ; blocks: MaternalDeath | Two lines: eclampsia due to severe pre-eclampsia | VA cause VAs-09.03 Pregnancy-induced hypertension |
| chain-4lines | adult | M P39Y: MG40.1 Shock [PT6H] **due to** 1G40 Sepsis [P2D] **due to** DC50.Z Peritonitis [P4D] **due to** DB10.01 Burst appendix [P6D] | Four lines: shock, sepsis, peritonitis, appendicitis | VA cause VAs-06.01 Acute abdomen; VA cause VAs-01.01 Sepsis |
| chain-5lines-max | adult | F P65Y: CB41.0Z Respiratory failure [PT5H] **due to** CA40.Z Pneumonia [P4D] **due to** 5A22.0 Ketoacidosis [P6D] **due to** 5A11 Diabetes [P9Y] **due to** BA00.Z Hypertension [P12Y] | Five lines (the server maximum): respiratory failure down to diabetes | VA cause VAs-03.03 Diabetes mellitus; VA cause VAs-01.02 Acute respiratory infection, including pneumonia |
| p2-mi-diabetes | adult | M P63Y: BA41.Z Heart attack [PT2H] ; II: 5A11 | Part II: diabetes contributing to MI | VA cause VAs-04.01 Acute cardiac disease; VA cause VAs-03.03 Diabetes mellitus |
| p2-stroke-hypertension | adult | F P71Y: 8B11.5Z Stroke [P1D] ; II: BA00.Z | Part II: hypertension contributing to stroke | VA cause VAs-04.02 Stroke |
| p2-tb-hiv | adult | M P40Y: 1B10.Z TB [P5M] ; II: 1C62.Z | Part II: HIV contributing to tuberculosis | VA cause VAs-01.09 Pulmonary tuberculosis; VA cause VAs-01.03 HIV/AIDS related death |
| p2-two-conditions | adult | F P67Y: BA41.Z MI [PT5H] ; II: 5A11, BA00.Z | Part II with two conditions: diabetes and hypertension | VA cause VAs-04.01 Acute cardiac disease |
| p2-pneumonia-copd | adult | M P69Y: CA40.Z Pneumonia [P6D] ; II: CA22.Z | Part II: COPD contributing to pneumonia | VA cause VAs-01.02 Acute respiratory infection, including pneumonia; VA cause VAs-05.01 Chronic obstructive pulmonary disease (COPD) |
| p2-maternal-anaemia | maternal | F P26Y: JA43.1 Bleeding after delivery [PT3H] ; II: JB64.0 ; blocks: MaternalDeath | Part II: anaemia contributing to maternal haemorrhage | VA cause VAs-09.04 Obstetric haemorrhage; VA cause VAs-09.07 Anaemia of pregnancy |
| p2-neonatal-lbw | neonatal | M P5D: KA60 Sepsis of newborn [P3D] ; II: KA21.2Z ; blocks: FetalOrInfantDeath | Part II: low birth weight contributing to neonatal sepsis | VA cause VAs-10.04 Neonatal sepsis; VA cause VAs-10.01 Prematurity or low birth weight |
| p2-only-coded-in-part2 | adult | F P60Y: uncoded Heart problem ; II: 5A11 | Part I uncoded, Part II coded | DORIS contract: uncoded text may be entered |
| line-two-conditions | adult | M P56Y: 1B10.Z TB + CA40.Z Pneumonia [P2M] **due to** 1C62.Z HIV [P3Y] | Two coded conditions on one Part I line | docs/kb/doris-icd-api-and-va.md |
| line-three-conditions | adult | F P62Y: BD10 Heart failure [P3M] **due to** BA01 Hypertensive heart + 5A11 Diabetes + GB61.Z CKD [P9Y] | Three conditions on the last line | docs/kb/doris-icd-api-and-va.md |
| line-coded-and-uncoded | adult | M P66Y: BA41.Z MI + uncoded Chest infection [P2D] | A coded and an uncoded condition on one line | DORIS contract: uncoded text |
| cluster-tb-otitis-ext | adult | M P44Y: 1B12.2&XA0G74 Tuberculous otitis media + 1B10.Z TB of lungs [P14D] | Stem + extension on one line (the KB example 1B12.2&XA0G74) | docs/kb/doris-certificate-ui-contract.md |
| cluster-slash-pneumonia-listeria | adult | F P50Y: CA40.0Z/1C1A.1 Listerial pneumonia [P4D] | Slash cluster CA40.0Z/1C1A.1 from WHO search | scripts/icd11-parity/queries.json |
| cluster-slash-hiv-pneumonia | adult | M P61Y: GB61.Z/5A11 Diabetic kidney failure [P6Y] | Slash cluster with the stem first (GB61.Z/5A11 order bug, KB doris-picker-who-behaviour-rules 'To report to WHO') | docs/kb/doris-picker-who-behaviour-rules.md |
| cluster-ext-in-line-chain | adult | F P53Y: 1B12.2&XA0G74 Tuberculous otitis media [P2M] **due to** 1B10.Z Respiratory tuberculosis [P6M] | Cluster on the upper line, plain stem below | docs/kb/doris-certificate-ui-contract.md |
| cluster-cholera-ext | child | M P6Y: 1A00&XN8P1 Cholera O1 classical [P2D] | Cholera with a causing-organism extension | scripts/icd11-parity/queries.json |
| cluster-motor-ext | adult | M P24Y: NC72.Z Fractured thigh bone **due to** PA03&XE7ZZ Motorbike rider injured ; blocks: MannerOfDeath | External cause with extension codes (PA03&XE7ZZ) | docs/kb/doris-picker-who-behaviour-rules.md |
| cluster-diabetic-foot-gangrene | adult | F P68Y: BD54/MC85 Diabetic foot with gangrene [P3M] **due to** 5A11 Diabetes [P15Y] | Diabetic foot ulcer with gangrene (mandatory-axis stem, composite) | docs/kb/doris-picker-who-behaviour-rules.md |
| cluster-maternal-composite | maternal | F P33Y: JB64.4/BD54 Heart failure in pregnancy ; blocks: MaternalDeath | Maternal composite JB64.4/BD54 (WHO related maternal chapter) | docs/kb/doris-picker-who-behaviour-rules.md |
| cluster-ca-pertussis-pneumonia | child | F P7M: 1C12.0/CA40.0Y Whooping cough with pneumonia [P10D] | Whooping cough with pneumonia cluster 1C12.0/CA40.0Y | scripts/icd11-parity/queries.json |
| cluster-cancer-ext-site | adult | M P70Y: 2B90.0Z&XA95L3 Cancer of colon, hepatic flexure [P1Y] | Cancer with site extension (2B90.0Z&XA95L3) | scripts/icd11-parity/queries.json |
| cluster-sepsis-viral | adult | F P38Y: 1E1Y/1G40&XN3BH Viral sepsis [P5D] | WHO search returns 1E1Y/1G40&XN3BH but codeinfo does not resolve it, so the server refuses it (expected INVALID_INPUT, code and URI mismatch) | scripts/icd11-parity/queries.json |
| rej-uncoded-only | adult | M P40Y: uncoded Heart problem | Only an uncoded text condition: DORIS cannot assign a cause | DORIS contract: uncoded text |
| rej-uncoded-two-lines | adult | F P55Y: uncoded Stopped breathing **due to** uncoded Long illness | Two uncoded lines | DORIS contract: uncoded text |
| rej-symptom-fever | adult | M P40Y: MG26 Fever | Symptom code only (MG26 fever): ill-defined cause kept by DORIS | VA cause VAs-01.99 Unspecified infectious disease |
| rej-coded-below-uncoded | adult | M P62Y: uncoded Collapsed **due to** BA41.Z MI | Uncoded top line, coded line below | DORIS contract: uncoded text |
| rej-sudden-death | adult | M P35Y: MH12.Y Sudden death | Sudden death, cause unknown (MH12.Y) | VA cause VAs-99 Cause of death unknown |
| rej-shock-only | adult | F P77Y: MG40.Z Shock | Shock alone (MG40.Z): a mode of dying, not a cause | VA cause VAs-99 Cause of death unknown |
| rej-cardiac-arrest-only | adult | M P66Y: MC82.Z Cardiac arrest | Cardiac arrest alone | VA cause VAs-04.01 Acute cardiac disease |
| rej-old-age-and-disease | adult | M P92Y: MG2A Old age **due to** BA41.Z MI | Old age above a specific disease | VA cause VAs-99 Cause of death unknown; VA cause VAs-04.01 Acute cardiac disease |
| rej-sids | child | F P3M: MH11.Z Cot death | Sudden infant death syndrome | VA cause VAs-10.99 Other and unspecified perinatal cause of death |
| iv-unknown-empty | adult | M P36Y: CA40.Z Pneumonia **due to** 1C62.Z HIV | Pneumonia due to HIV, interval unknown interval as "" | VA cause VAs-01.02 Acute respiratory infection, including pneumonia; VA cause VAs-01.03 HIV/AIDS related death |
| iv-unknown-p | adult | M P36Y: CA40.Z Pneumonia [P] **due to** 1C62.Z HIV [P] | Pneumonia due to HIV, interval unknown interval as "P" | VA cause VAs-01.02 Acute respiratory infection, including pneumonia; VA cause VAs-01.03 HIV/AIDS related death |
| iv-unknown-pt | adult | M P36Y: CA40.Z Pneumonia [PT] **due to** 1C62.Z HIV [PT] | Pneumonia due to HIV, interval unknown interval as "PT" | VA cause VAs-01.02 Acute respiratory infection, including pneumonia; VA cause VAs-01.03 HIV/AIDS related death |
| iv-weeks | adult | M P36Y: CA40.Z Pneumonia [P2W] **due to** 1C62.Z HIV [P6W] | Pneumonia due to HIV, interval weeks | VA cause VAs-01.02 Acute respiratory infection, including pneumonia; VA cause VAs-01.03 HIV/AIDS related death |
| iv-years-months | adult | M P36Y: CA40.Z Pneumonia [P1Y6M] **due to** 1C62.Z HIV [P8Y2M] | Pneumonia due to HIV, interval years and months combined | VA cause VAs-01.02 Acute respiratory infection, including pneumonia; VA cause VAs-01.03 HIV/AIDS related death |
| iv-omitted | adult | M P36Y: CA40.Z Pneumonia **due to** 1C62.Z HIV | Pneumonia due to HIV, interval no Interval key at all | VA cause VAs-01.02 Acute respiratory infection, including pneumonia; VA cause VAs-01.03 HIV/AIDS related death |
| manner-accident-full | adult | F P30Y: NA02.Z Skull fracture **due to** PA01 Rider hit by lorry ; blocks: MannerOfDeath | Accident with date, description and place | VA cause VAs-12.01 Road traffic accident |
| manner-self-harm | adult | M P26Y: NF05 Asphyxia **due to** PC71 Hanging ; blocks: MannerOfDeath | Intentional self-harm | VA cause VAs-12.08 Intentional self-harm |
| manner-assault | adult | M P31Y: ND56.1 Gunshot wound **due to** PD50 Shot by another person ; blocks: MannerOfDeath | Assault (firearm) | VA cause VAs-12.09 Assault |
| manner-legal-intervention | adult | M P29Y: ND56.1 Gunshot wound **due to** PD50 Shot during arrest ; blocks: MannerOfDeath | Legal intervention | WHO DORIS manner enum |
| manner-war | adult | M P27Y: ND37 Multiple injuries **due to** PK02 Explosion in war ; blocks: MannerOfDeath | War | WHO DORIS manner enum |
| manner-undetermined | adult | F P34Y: NF08.1 Drowned **due to** PA90 Drowning ; blocks: MannerOfDeath | Could not be determined | WHO DORIS manner enum |
| manner-pending | adult | M P33Y: NE61 Poisoning **due to** PB28 Poisoning by an unknown substance ; blocks: MannerOfDeath | Pending investigation | WHO DORIS manner enum |
| manner-disease | adult | M P55Y: BA41.Z MI ; blocks: MannerOfDeath | Manner is disease (external cause fields are dropped) | docs/policy/doris-certificate-rules.md |
| manner-unknown | adult | F P45Y: MG26 Fever ; blocks: MannerOfDeath | Manner unknown (9) | docs/policy/doris-certificate-rules.md |
| manner-inconsistent | adult | M P50Y: NC72.Z Fractured femur **due to** PA60 Fall ; blocks: MannerOfDeath | External cause with manner disease (DORIS inconsistency warning) | tests/fixtures/doris_warning_cases.json |
| manner-external-no-injury | adult | M P40Y: PA61 Fell from roof ; blocks: MannerOfDeath | External cause only: 'No injury found to postcoordinate' warning | tests/fixtures/doris_warning_cases.json |
| manner-poisoning-intent | adult | F P19Y: NE61 Pesticide poisoning **due to** PD03 Swallowed pesticide on purpose ; blocks: MannerOfDeath | Self-poisoning with pesticide | VA cause VAs-12.07 Accidental poisoning and exposure to noxious substances; VA cause VAs-12.08 Intentional self-harm |
| manner-snakebite | adult | M P38Y: NE61 Envenomation **due to** PA78&XE9H6 Venomous snake bite ; blocks: MannerOfDeath | Snake bite with extension (PA78&XE9H6) | tests/fixtures/doris_warning_cases.json |
| surgery-yes-date-reason | adult | M P61Y: BA41.Z MI [PT3H] **due to** BA52.Z Coronary disease [P3Y] ; blocks: Surgery | Surgery performed with date and reason | WHO DORIS certificate format |
| surgery-no | adult | M P61Y: BA41.Z MI [PT3H] **due to** BA52.Z Coronary disease [P3Y] ; blocks: Surgery | Surgery not performed (Date/Reason dropped) | docs/policy/doris-certificate-rules.md |
| autopsy-requested-findings-yes | adult | F P52Y: BA41.Z MI [PT3H] **due to** BA52.Z Coronary disease [P3Y] ; blocks: Autopsy | Autopsy requested, findings used | WHO DORIS certificate format |
| autopsy-requested-findings-no | adult | F P52Y: BA41.Z MI [PT3H] **due to** BA52.Z Coronary disease [P3Y] ; blocks: Autopsy | Autopsy requested, findings not used | WHO DORIS certificate format |
| autopsy-not-requested | adult | F P52Y: BA41.Z MI [PT3H] **due to** BA52.Z Coronary disease [P3Y] ; blocks: Autopsy | Autopsy not requested (Findings dropped) | docs/policy/doris-certificate-rules.md |
| surgery-autopsy-manner-all | adult | M P45Y: NA07.Z Head injury **due to** PA60 Fall ; blocks: Surgery, Autopsy, MannerOfDeath | Surgery, autopsy and manner blocks together | WHO DORIS certificate format |
| maternal-block-1 | maternal | F P28Y: JA43.1 Bleeding after delivery [PT5H] ; blocks: MaternalDeath | Maternal block: pregnant 1, timing 0, contribution 1 | WHO DORIS certificate format |
| maternal-block-2 | maternal | F P28Y: JA43.1 Bleeding after delivery [PT5H] ; blocks: MaternalDeath | Maternal block: pregnant 1, timing 0, contribution 0 | WHO DORIS certificate format |
| maternal-block-3 | maternal | F P28Y: JA43.1 Bleeding after delivery [PT5H] ; blocks: MaternalDeath | Maternal block: pregnant 0, timing 1, contribution 1 | WHO DORIS certificate format |
| maternal-block-4 | maternal | F P28Y: JA43.1 Bleeding after delivery [PT5H] ; blocks: MaternalDeath | Maternal block: pregnant 0, timing 2, contribution 1 | WHO DORIS certificate format |
| maternal-block-5 | maternal | F P28Y: JA43.1 Bleeding after delivery [PT5H] ; blocks: MaternalDeath | Maternal block: pregnant 0, timing 3, contribution 0 | WHO DORIS certificate format |
| maternal-block-6 | maternal | F P28Y: JA43.1 Bleeding after delivery [PT5H] ; blocks: MaternalDeath | Maternal block: pregnant 0, timing 9, contribution 9 | WHO DORIS certificate format |
| maternal-block-7 | maternal | F P28Y: JA43.1 Bleeding after delivery [PT5H] ; blocks: MaternalDeath | Maternal block: pregnant 9, timing 9, contribution 9 | WHO DORIS certificate format |
| maternal-male-dropped | adult | M P40Y: BA41.Z MI ; blocks: MaternalDeath | Male with a maternal block (block dropped by the server) | docs/policy/doris-certificate-rules.md |
| fetal-stillborn | stillbirth | M : KD3B.1 Stillbirth ; blocks: FetalOrInfantDeath | Stillborn with weight, weeks, mother's age | VA cause VAs-11.01 Fresh stillbirth |
| fetal-stillborn-cause-known | stillbirth | F : KD3B.0 Stillbirth **due to** KA02.0 Placental problem ; blocks: FetalOrInfantDeath | Stillbirth with a known cause (placental) | VA cause VAs-11.02 Macerated stillbirth |
| fetal-multiple-pregnancy | neonatal | F PT15H: KA21.4Z Premature ; blocks: FetalOrInfantDeath | Twin neonate, death within 24 h | VA cause VAs-10.01 Prematurity or low birth weight |
| fetal-perinatal-description | neonatal | M P2D: KB88.Z Necrotising enterocolitis ; blocks: FetalOrInfantDeath | Neonate with a free-text perinatal description | VA cause VAs-10.99 Other and unspecified perinatal cause of death |
| fetal-minimal-neonate | neonatal | F P2D: KB23.0Z RDS of newborn | Neonate with no fetal block (CoDEdit asks for birth weight) | docs/kb/doris-picker-who-behaviour-rules.md |
| fetal-adult-dropped | adult | M P44Y: BA41.Z MI ; blocks: FetalOrInfantDeath | Adult with a fetal block (dropped by the server) | docs/policy/doris-certificate-rules.md |
| fetal-week-old-drops-24h | neonatal | M P8D: KA60 Sepsis of newborn ; blocks: FetalOrInfantDeath | Neonate at 8 days: DeathWithin24h dropped | docs/policy/doris-certificate-rules.md |
| fetal-unknown-measures | neonatal | M P3D: KA82.Z Brain bleed ; blocks: FetalOrInfantDeath | Unknown measurements sent as empty | app/services/doris_certificate.py unknown fetal measurements |
| date-full-dates | adult | M 1962-03-14/2026-02-08: BA41.Z MI | Birth and death as full dates | WHO DORIS certificate format |
| date-year-only-birth | adult | M 1962/2026-02-08: BA41.Z MI | Year-only birth date with a full death date: left out of the WHO request, who_notes | app/services/doris_certificate.py who_safe_certificate |
| date-year-only-both | adult | F 1950/2026: CA22.Z COPD | Year-only birth and death: both left out | app/services/doris_certificate.py who_safe_certificate |
| date-month-precision | adult | F 1950-06/2026-03: 5A11 Diabetes | Month-precision dates are accepted by WHO | app/services/doris_certificate.py who_safe_certificate |
| date-neonate-hours | neonatal | F 2026-03-01/2026-03-01: KB21.Z Birth asphyxia ; blocks: FetalOrInfantDeath | Newborn by dates, same day death | VA cause VAs-10.02 Birth asphyxia |
| date-datetime | neonatal | M 2026-04-01T06:30:00/2026-04-03T09:00:00: KA60 Sepsis of newborn | Birth and death with time of day | WHO DORIS certificate format |
| sex-unknown | adult | sex? P50Y: 1B10.Z TB | Sex unknown (9) | WHO DORIS certificate format |
| sex-male-pregnancy-code | adult | M P27Y: JA43.1 PPH | Male with a pregnancy code (WHO sex-consistency) | WHO DORIS sex check |
| age-child-vs-adult-cause | child | M P3Y: 2C82.0 Prostate cancer | Child with an adult-only cause (age check) | WHO DORIS age check |
| age-none | adult | M : BA41.Z MI | No age or date at all | WHO DORIS certificate format |
| bad-code-uri-mismatch | invalid | M P50Y: BA41.Z MI | Code and URI that do not agree (rejected before WHO) | docs/kb/doris-certificate-ui-contract.md |
| bad-unknown-code | invalid | M P50Y: ZZ99.9 MI | A code WHO does not know | docs/kb/doris-certificate-ui-contract.md |
| bad-mixed-intervals | invalid |  : BA41.Z MI + CA40.Z Pneumonia [P1D] | Two conditions on a line with different intervals | docs/kb/doris-certificate-ui-contract.md |
| bad-six-lines | invalid |  : uncoded Line 0 **due to** uncoded Line 1 **due to** uncoded Line 2 **due to** uncoded Line 3 **due to** uncoded Line 4 **due to** uncoded Line 5 | Six Part I lines (maximum five) | app/services/doris_certificate.py |
| bad-code-without-uri | invalid |  : BA41.Z MI | A code without its URI | app/services/doris_certificate.py |
| bad-unsupported-field | invalid |  : uncoded MI | Unsupported certificate field | app/services/doris_certificate.py |
| bad-interval-format | invalid |  : uncoded MI [3 days] | Interval that is not ISO 8601 | app/services/doris_certificate.py |
| bad-date | invalid |  2026-02-30: uncoded MI | Impossible date | app/services/doris_certificate.py |

## Postcoordination stems

Each stem is recorded through codeinfo, selection-check, postcoordination, postcoordination-options (first expandable root of every axis), hierarchy, related and details. Built expressions go through codeinfo, selection-check, hierarchy, related and details.

| id | stem | category | built expressions | why | source |
|---|---|---|---|---|---|
| pc-bd54 | BD54 | mandatory | `BD54/5A11` causing condition chosen (type 2 diabetes)<br>`BD54&XK9J/5A11` X extension (bilateral) before the / stem, WHO canonical order<br>`BD54&XK9J&XA47V8/5A11` two X extensions, then the causing condition<br>`BD54/5A11/MC85` causing condition and the gangrene manifestation as / stems<br>`BD54` stem alone: 'causing condition not known' (digitva-xmpx)<br>`BD54&XK9J` extension only, required axis missing<br>`BD54/MC85` manifestation only (search composite 'Diabetic foot ulcer with gangrene')<br>`BD54&XS5W` WHO refuses this extension for the stem (KB rule 6)<br>`BD54&XS5W/5A11` refused extension inside a longer expression | Diabetic foot ulcer: required 'Has causing condition' axis plus laterality, anatomy, manifestation; maternal link; coding note | docs/kb/doris-picker-who-behaviour-rules.md rules 2-3, 10 |
| pc-1g40 | 1G40 | mandatory | `1G40/CA40.0Z` sepsis due to bacterial pneumonia<br>`1G40/1A40.Z` sepsis due to gastroenteritis<br>`1G40` sepsis alone, causing condition unknown | Sepsis without septic shock (VA cause 01.01): required causing condition with 50 roots, cut to 12 (truncated axis) | VAs-01.01; docs/kb/doris-picker-who-behaviour-rules.md |
| pc-db93-1 | DB93.1 | mandatory | `DB93.1/1E51` cirrhosis due to chronic viral hepatitis<br>`DB93.1` stem alone | Hepatic cirrhosis (VA cause 06.02): required causing condition, 25 manifestation roots | VAs-06.02 |
| pc-ja43-1 | JA43.1 | mandatory | `JA43.1/JB02.2` haemorrhage due to uterine atony<br>`JA43.1/JB09.0` haemorrhage due to perineal laceration | Postpartum haemorrhage (VA cause 09.04): required causing condition, obstetric roots | VAs-09.04 |
| pc-jb40-0 | JB40.0 | mandatory | `JB40.0&XN74M/JB40.2` bacteria extension, then genital tract infection<br>`JB40.0/JB40.3` urinary tract infection | Puerperal sepsis (VA cause 09.06): required causing condition and an infectious-agent axis | VAs-09.06 |
| pc-ca40-0z | CA40.0Z | mandatory | `CA40.0Z/1G40` pneumonia with sepsis<br>`CA40.0Z&XK9J` laterality extension only<br>`CA40.0Z&XB25/1A07` nosocomial extension and typhoid cause | Bacterial pneumonia (VA cause 01.02): five axes, one required, mixed NotAllowed and AllowAlways | VAs-01.02 |
| pc-gb61-z | GB61.Z | mandatory | `GB61.Z/5A11` kidney disease due to type 2 diabetes (order that triggered the CoDEdit BER-CE-9 report)<br>`GB61.Z/BA00.Z` kidney disease due to hypertension | Chronic kidney disease (VA cause 07.01): required causing condition whose roots are uncoded groups (expand to pick) | VAs-07.01; docs/kb/doris-picker-who-behaviour-rules.md rule 17 |
| pc-3a71-2 | 3A71.2 | mandatory | `3A71.2/GB61.5` anaemia with stage 5 kidney disease | Anaemia in chronic kidney disease: single required axis with a single root | VAs-03.01 |
| pc-9b71-00 | 9B71.00 | mandatory | `9B71.00&XS25&XK9J/5A11` severe, bilateral, type 2 diabetes | Non-proliferative diabetic retinopathy: severity, laterality and required causing condition | docs/kb/doris-icd-api-and-va.md |
| pc-1d01-0z | 1D01.0Z | mandatory |  | Bacterial meningitis (VA cause 01.07): required axis with 25 roots | VAs-01.07 |
| pc-nc72-7 | NC72.7 | injury | `NC72.7&XK8G&XJ44E` left, closed<br>`NC72.7&XJ7YM&XK9K` open, right<br>`NC72.7&XK8G` left only | Multiple fractures of femur: five optional axes (fracture subtype has 26 roots), coding note | owner list 2026-10-29; docs/kb/doris-picker-who-behaviour-rules.md rule 2 |
| pc-nc71-z | NC71.Z | injury | `NC71.Z&XK8G&XA5S78` left thigh | Open wound of hip or thigh: laterality, anatomy and associated-with (external causes chapter) | owner list 2026-10-29 |
| pc-nc72-z | NC72.Z | injury |  | Fracture of femur, unspecified (VA cause 12.99): five axes, associated-with 2 | VAs-12.99 |
| pc-nc72 | NC72 | injury |  | Fracture of femur (parent category): 11 children shown in hierarchy | owner list 2026-10-29 |
| pc-na02-z | NA02.Z | injury |  | Skull fracture: fracture subtype, open/closed, anatomy, perinatal links | docs/kb/doris-picker-who-behaviour-rules.md rule 17 |
| pc-ne61 | NE61 | injury | `NE61&XM0231` poisoning with a specific chemical agent | Noxious substances (poisoning): chemical agent root with 50 children, coding note, exclusions | VAs-12.07 |
| pc-pa61 | PA61 | injury | `PA61&XE545&XE266` paid work at home | Fall from a height (VA cause 12.03): five external-cause axes, roots over 12 (truncated) | VAs-12.03 |
| pc-pa03 | PA03 | injury | `PA03&XE7ZZ` motorcycle rider injured (WHO search result) | Motorcycle traffic event (VA cause 12.01): built from the WHO search result PA03&XE7ZZ | VAs-12.01; scripts/icd11-parity/queries.json |
| pc-pc71 | PC71 | injury |  | Self-harm by threat to breathing (VA cause 12.08): self-harm aspects axis | VAs-12.08 |
| pc-pd50 | PD50 | injury |  | Assault by road traffic (VA cause 12.09): six axes with a long transport-event root list | VAs-12.09 |
| pc-pa50-z | PA50.Z | injury |  | Stem whose postcoordination read needs 46 of the 48 WHO calls the guidance budget allows (closest to the cap found) | app/services/icd11_postcoordination.py _MAX_CALLS |
| pc-pa78 | PA78 | injury | `PA78&XE9H6` venomous snake | Venomous animal (VA cause 12.06): snake bite extension PA78&XE9H6 from the DORIS warning cases | VAs-12.06; tests/fixtures/doris_warning_cases.json |
| pc-2a01-0y | 2A01.0Y | optional | `2A01.0Y&XA6HA2` cerebral meninges<br>`2A01.0Y&XA6HA2/MG30.10` cerebral meninges with cancer pain | Other specified meningiomas: all axes optional, uncoded histopathology roots | owner list 2026-10-29 |
| pc-2a01 | 2A01 | optional |  | Primary neoplasms of meninges: histopathology axis with 50 roots (truncated), three children | owner list 2026-10-29 |
| pc-2c25-z | 2C25.Z | optional |  | Lung cancer (VA cause 02.03): severity and alternative severity axes | VAs-02.03 |
| pc-1b12-2 | 1B12.2 | optional | `1B12.2&XA0G74` middle ear (the KB cluster)<br>`1B12.2&XA0G74&XK8G` middle ear, left<br>`1B12.2/MG52.0` antibiotic resistant organism | Tuberculosis of ear: stem of the KB cluster example 1B12.2&XA0G74; maternal and perinatal links, exclusions, inclusion | docs/kb/doris-certificate-ui-contract.md; docs/kb/doris-icd-api-and-va.md |
| pc-1a00 | 1A00 | optional | `1A00&XN8P1` Vibrio cholerae O1 biovar cholerae<br>`1A00/5A11` owner's example '1A00/5A11': WHO does not resolve it (expected not found) | Cholera (VA cause 01.04): infectious agent axis | VAs-01.04; owner list 2026-10-29 |
| pc-5a11 | 5A11 | optional | `5A11/8C03.0` diabetes with polyneuropathy<br>`5A24/5A11` WHO cluster for uncontrolled diabetes (search composite) | Type 2 diabetes mellitus (VA cause 03.03): hasManifestation with 16 roots (truncated), maternal and perinatal links, exclusions | VAs-03.03 |
| pc-ba41-z | BA41.Z | optional | `BA41.Z/BD10` infarction with congestive heart failure<br>`BA41.Z&XA0F62/BD10` left main coronary artery, with heart failure | Acute myocardial infarction (VA cause 04.01): anatomy, manifestation (7) and associated-with | VAs-04.01 |
| pc-1c62-z | 1C62.Z | optional |  | HIV disease (VA cause 01.03): associated-with with 15 roots (truncated) | VAs-01.03 |
| pc-ka60 | KA60 | optional | `KA60&XN74M` bacterial neonatal sepsis | Sepsis of newborn (VA cause 10.04): infectious agent and associated-with | VAs-10.04 |
| pc-1a07 | 1A07 | optional |  | Typhoid fever: hasManifestation with 9 roots, three children (expandable) | VAs-01.99 |
| pc-1c12-0 | 1C12.0 | optional | `1C12.0/CA40.0Y` whooping cough with pneumonia | Whooping cough: stem of the WHO search cluster 1C12.0/CA40.0Y | scripts/icd11-parity/queries.json |
| pc-5a24 | 5A24 | optional |  | Uncontrolled diabetes: stem of the WHO search cluster 5A24/5A11 | WHO search 'diabetes' |
| pc-jb64-4 | JB64.4 | optional | `JB64.4/BD54` maternal composite: related category joined with the stem | Maternal-chapter stem of the composite JB64.4/BD54 (KB rule 10) | docs/kb/doris-picker-who-behaviour-rules.md rule 10 |
| pc-ja25 | JA25 | plain |  | Eclampsia (VA cause 09.03): no axes, four children | VAs-09.03 |
| pc-kd3b-1 | KD3B.1 | plain |  | Intrapartum fetal death (VA cause 11.01): no axes, coding note, two inclusion terms | VAs-11.01 |
| pc-8a66-z | 8A66.Z | plain |  | Status epilepticus (VA cause 08.01): no axes, maternal and perinatal links | VAs-08.01 |
| pc-1f03-0 | 1F03.0 | plain |  | Measles (VA cause 01.06): no axes, perinatal link | VAs-01.06 |
| pc-xk9j | XK9J | plain |  | An extension code used as a stem: other_postcoordination must be null (stem starts with X) | docs/kb/doris-picker-who-behaviour-rules.md rule 6 |
| pc-err-unknown | ZZ99 | error |  | A code WHO does not know: CODE_NOT_FOUND on every operation | docs/kb/doris-certificate-ui-contract.md |
| pc-err-lowercase | bd54 | error |  | Lower-case code: WHO's codeinfo accepts it but DigitVA requires the exact code (CODE_NOT_FOUND / INVALID_INPUT) | app/services/icd11_postcoordination.py _CODE_RE |
| pc-err-expression-as-stem | BD54&XK9J | error |  | An expression passed where a stem is required | app/services/icd11_postcoordination.py _stem |
| pc-err-chapter-x | X | error |  | The extension chapter itself: not a code | KB rule 6 |

## Search terms

Recorded with the server's options (`q=<term>%`, includePostcoordination, flatResults, highlightingEnabled, medicalCodingMode), limit 20; the expected top 5 are kept in order.

| id | query | kind | why | source |
|---|---|---|---|---|
| s001-myocardial-infarction | myocardial infarction | disease | common disease name a medical officer types | VAs-04.01 |
| s002-acute-myocardial-infarction | acute myocardial infarction | disease | common disease name a medical officer types | VAs-04.01; scripts/icd11-parity/queries.json |
| s003-congestive-heart-failure | congestive heart failure | disease | common disease name a medical officer types | VAs-04.01 |
| s004-cardiomyopathy | cardiomyopathy | disease | common disease name a medical officer types | VAs-04.99 |
| s005-pulmonary-embolism | pulmonary embolism | disease | common disease name a medical officer types | VAs-04.01 |
| s006-ischaemic-stroke | ischaemic stroke | disease | common disease name a medical officer types | VAs-04.02 |
| s007-intracerebral-haemorrhage | intracerebral haemorrhage | disease | common disease name a medical officer types | VAs-04.02; scripts/icd11-parity/queries.json |
| s008-essential-hypertension | essential hypertension | disease | common disease name a medical officer types | VAs-04.99 |
| s009-type-2-diabetes-mellitus | type 2 diabetes mellitus | disease | common disease name a medical officer types | VAs-03.03 |
| s010-diabetic-ketoacidosis | diabetic ketoacidosis | disease | common disease name a medical officer types | VAs-03.03 |
| s011-diabetic-foot | diabetic foot | disease | common disease name a medical officer types | VAs-03.03; docs/kb/doris-picker-who-behaviour-rules.md |
| s012-chronic-kidney-disease | chronic kidney disease | disease | common disease name a medical officer types | VAs-07.01; scripts/icd11-parity/queries.json |
| s013-acute-kidney-failure | acute kidney failure | disease | common disease name a medical officer types | VAs-07.01 |
| s014-pneumonia | pneumonia | disease | common disease name a medical officer types | VAs-01.02; scripts/icd11-parity/queries.json |
| s015-pulmonary-tuberculosis | pulmonary tuberculosis | disease | common disease name a medical officer types | VAs-01.09 |
| s016-hiv-disease | HIV disease | disease | common disease name a medical officer types | VAs-01.03 |
| s017-falciparum-malaria | falciparum malaria | disease | common disease name a medical officer types | VAs-01.05 |
| s018-severe-dengue | severe dengue | disease | common disease name a medical officer types | VAs-01.12 |
| s019-typhoid-fever | typhoid fever | disease | common disease name a medical officer types | VAs-01.99 |
| s020-septic-shock | septic shock | disease | common disease name a medical officer types | VAs-01.01 |
| s021-bacterial-meningitis | bacterial meningitis | disease | common disease name a medical officer types | VAs-01.07 |
| s022-alcoholic-cirrhosis | alcoholic cirrhosis | disease | common disease name a medical officer types | VAs-06.02 |
| s023-hepatocellular-carcinoma | hepatocellular carcinoma | disease | common disease name a medical officer types | VAs-02.02 |
| s024-cancer-of-the-oesophagus | cancer of the oesophagus | disease | common disease name a medical officer types | VAs-02.02 |
| s025-carcinoma-of-cervix | carcinoma of cervix | disease | common disease name a medical officer types | VAs-02.05 |
| s026-prostate-cancer | prostate cancer | disease | common disease name a medical officer types | VAs-02.06 |
| s027-acute-leukaemia | acute leukaemia | disease | common disease name a medical officer types | VAs-02.99 |
| s028-severe-acute-malnutrition | severe acute malnutrition | disease | common disease name a medical officer types | VAs-03.02 |
| s029-sickle-cell-crisis | sickle cell crisis | disease | common disease name a medical officer types | VAs-04.03 |
| s030-status-epilepticus | status epilepticus | disease | common disease name a medical officer types | VAs-08.01 |
| s031-tetanus | tetanus | disease | common disease name a medical officer types | VAs-01.08 |
| s032-rabies | rabies | disease | common disease name a medical officer types | VAs-01.07 |
| s033-cholera | cholera | disease | common disease name a medical officer types | VAs-01.04 |
| s034-covid-19 | COVID-19 | disease | common disease name a medical officer types | VAs-01.13 |
| s035-peritonitis | peritonitis | disease | common disease name a medical officer types | VAs-06.01 |
| s036-heart-attack | heart attack | lay | lay wording used in verbal autopsy narratives | VAs-04.01; scripts/icd11-parity/queries.json |
| s037-fits | fits | lay | lay wording used in verbal autopsy narratives | VAs-08.01; scripts/icd11-parity/queries.json |
| s038-jaundice | jaundice | lay | lay wording used in verbal autopsy narratives | VAs-06.02; scripts/icd11-parity/queries.json |
| s039-sugar | sugar | lay | lay wording used in verbal autopsy narratives | VAs-03.03 |
| s040-high-blood-pressure | high blood pressure | lay | lay wording used in verbal autopsy narratives | VAs-04.99; scripts/icd11-parity/queries.json |
| s041-water-in-the-lungs | water in the lungs | lay | lay wording used in verbal autopsy narratives | VAs-04.99 |
| s042-kidney-failure | kidney failure | lay | lay wording used in verbal autopsy narratives | VAs-07.01; scripts/icd11-parity/queries.json |
| s043-blood-cancer | blood cancer | lay | lay wording used in verbal autopsy narratives | VAs-02.99 |
| s044-paralysis | paralysis | lay | lay wording used in verbal autopsy narratives | VAs-04.02; scripts/icd11-parity/queries.json |
| s045-brain-haemorrhage | brain haemorrhage | lay | lay wording used in verbal autopsy narratives | VAs-04.02 |
| s046-bleeding-after-delivery | bleeding after delivery | lay | lay wording used in verbal autopsy narratives | VAs-09.04; scripts/icd11-parity/queries.json |
| s047-convulsions | convulsions | lay | lay wording used in verbal autopsy narratives | VAs-08.01; scripts/icd11-parity/queries.json |
| s048-shortness-of-breath | shortness of breath | lay | lay wording used in verbal autopsy narratives | VAs-05.01 |
| s049-chest-pain | chest pain | lay | lay wording used in verbal autopsy narratives | VAs-04.01; scripts/icd11-parity/queries.json |
| s050-vomiting-blood | vomiting blood | lay | lay wording used in verbal autopsy narratives | VAs-06.01 |
| s051-watery-diarrhoea | watery diarrhoea | lay | lay wording used in verbal autopsy narratives | VAs-01.04 |
| s052-wasting | wasting | lay | lay wording used in verbal autopsy narratives | VAs-03.02 |
| s053-animal-bite | animal bite | lay | lay wording used in verbal autopsy narratives | VAs-12.99 |
| s054-snake-bite | snake bite | lay | lay wording used in verbal autopsy narratives | VAs-12.06; scripts/icd11-parity/queries.json |
| s055-poison | poison | lay | lay wording used in verbal autopsy narratives | VAs-12.07 |
| s056-drowned | drowned | lay | lay wording used in verbal autopsy narratives | VAs-12.04 |
| s057-cot-death | cot death | lay | lay wording used in verbal autopsy narratives | VAs-10.99 |
| s058-asphyxia-neonatorum | asphyxia neonatorum | lay | lay wording used in verbal autopsy narratives | VAs-10.02 |
| s059-premature-baby | premature baby | lay | lay wording used in verbal autopsy narratives | VAs-10.01; scripts/icd11-parity/queries.json |
| s060-old-age | old age | lay | lay wording used in verbal autopsy narratives | VAs-99; scripts/icd11-parity/queries.json |
| s061-mi | MI | abbreviation | abbreviation common on Indian death certificates | VAs-04.01 |
| s062-tb | TB | abbreviation | abbreviation common on Indian death certificates | VAs-01.09; scripts/icd11-parity/queries.json |
| s063-rta | RTA | abbreviation | abbreviation common on Indian death certificates | VAs-12.01 |
| s064-copd | COPD | abbreviation | abbreviation common on Indian death certificates | VAs-05.01; scripts/icd11-parity/queries.json |
| s065-pph | PPH | abbreviation | abbreviation common on Indian death certificates | VAs-09.04 |
| s066-hiv | HIV | abbreviation | abbreviation common on Indian death certificates | VAs-01.03; scripts/icd11-parity/queries.json |
| s067-aids | AIDS | abbreviation | abbreviation common on Indian death certificates | VAs-01.03; scripts/icd11-parity/queries.json |
| s068-ckd | CKD | abbreviation | abbreviation common on Indian death certificates | VAs-07.01 |
| s069-cva | CVA | abbreviation | abbreviation common on Indian death certificates | VAs-04.02 |
| s070-dm | DM | abbreviation | abbreviation common on Indian death certificates | VAs-03.03 |
| s071-htn | HTN | abbreviation | abbreviation common on Indian death certificates | VAs-04.99 |
| s072-urti | URTI | abbreviation | abbreviation common on Indian death certificates | VAs-01.02 |
| s073-ihd | IHD | abbreviation | abbreviation common on Indian death certificates | VAs-04.01 |
| s074-lbw | LBW | abbreviation | abbreviation common on Indian death certificates | VAs-10.01 |
| s075-hie | HIE | abbreviation | abbreviation common on Indian death certificates | VAs-10.02 |
| s076-rds | RDS | abbreviation | abbreviation common on Indian death certificates | VAs-10.02 |
| s077-gi-bleed | GI bleed | abbreviation | abbreviation common on Indian death certificates | VAs-06.01 |
| s078-aph | APH | abbreviation | abbreviation common on Indian death certificates | VAs-09.04 |
| s079-sids | SIDS | abbreviation | abbreviation common on Indian death certificates | VAs-10.99 |
| s080-covid | COVID | abbreviation | abbreviation common on Indian death certificates | VAs-01.13 |
| s081-diabetis | diabetis | typo | misspelling a hurried user types | scripts/icd11-parity/queries.json |
| s082-neumonia | neumonia | typo | misspelling a hurried user types | scripts/icd11-parity/queries.json |
| s083-tuberclosis | tuberclosis | typo | misspelling a hurried user types | scripts/icd11-parity/queries.json |
| s084-malnutriton | malnutriton | typo | misspelling a hurried user types | VAs-03.02 |
| s085-hypertention | hypertention | typo | misspelling a hurried user types | VAs-04.99 |
| s086-strok | strok | typo | misspelling a hurried user types | VAs-04.02 |
| s087-jaundise | jaundise | typo | misspelling a hurried user types | VAs-06.02 |
| s088-asma | asma | typo | misspelling a hurried user types | VAs-05.02 |
| s089-epilepsi | epilepsi | typo | misspelling a hurried user types | VAs-08.01 |
| s090-cirhosis | cirhosis | typo | misspelling a hurried user types | VAs-06.02 |
| s091-meningitus | meningitus | typo | misspelling a hurried user types | VAs-01.07 |
| s092-dehydraton | dehydraton | typo | misspelling a hurried user types | VAs-01.04 |
| s093-road-traffic-accident | road traffic accident | injury | injury or external-cause wording | VAs-12.01; scripts/icd11-parity/queries.json |
| s094-motorcycle-accident | motorcycle accident | injury | injury or external-cause wording | VAs-12.01 |
| s095-fall-from-height | fall from height | injury | injury or external-cause wording | VAs-12.03 |
| s096-drowning | drowning | injury | injury or external-cause wording | VAs-12.04; scripts/icd11-parity/queries.json |
| s097-burns | burns | injury | injury or external-cause wording | VAs-12.05; scripts/icd11-parity/queries.json |
| s098-hanging | hanging | injury | injury or external-cause wording | VAs-12.08; scripts/icd11-parity/queries.json |
| s099-pesticide-poisoning | pesticide poisoning | injury | injury or external-cause wording | VAs-12.07; scripts/icd11-parity/queries.json |
| s100-gunshot-wound | gunshot wound | injury | injury or external-cause wording | VAs-12.09 |
| s101-head-injury | head injury | injury | injury or external-cause wording | VAs-12.99 |
| s102-fracture-of-femur | fracture of femur | injury | injury or external-cause wording | VAs-12.99 |
| s103-postpartum-haemorrhage | postpartum haemorrhage | maternal | maternal death cause | VAs-09.04; scripts/icd11-parity/queries.json |
| s104-eclampsia | eclampsia | maternal | maternal death cause | VAs-09.03; scripts/icd11-parity/queries.json |
| s105-puerperal-sepsis | puerperal sepsis | maternal | maternal death cause | VAs-09.06; scripts/icd11-parity/queries.json |
| s106-obstructed-labour | obstructed labour | maternal | maternal death cause | VAs-09.05; scripts/icd11-parity/queries.json |
| s107-ectopic-pregnancy | ectopic pregnancy | maternal | maternal death cause | VAs-09.01 |
| s108-septic-abortion | septic abortion | maternal | maternal death cause | VAs-09.02 |
| s109-anaemia-in-pregnancy | anaemia in pregnancy | maternal | maternal death cause | VAs-09.07 |
| s110-preterm-birth | preterm birth | neonatal | neonatal or stillbirth cause | VAs-10.01 |
| s111-low-birth-weight | low birth weight | neonatal | neonatal or stillbirth cause | VAs-10.01; scripts/icd11-parity/queries.json |
| s112-birth-asphyxia | birth asphyxia | neonatal | neonatal or stillbirth cause | VAs-10.02; scripts/icd11-parity/queries.json |
| s113-neonatal-sepsis | neonatal sepsis | neonatal | neonatal or stillbirth cause | VAs-10.04; scripts/icd11-parity/queries.json |
| s114-respiratory-distress-syndrome-of-newborn | respiratory distress syndrome of newborn | neonatal | neonatal or stillbirth cause | VAs-10.02 |
| s115-congenital-heart-disease | congenital heart disease | neonatal | neonatal or stillbirth cause | VAs-10.06 |
| s116-neonatal-jaundice | neonatal jaundice | neonatal | neonatal or stillbirth cause | VAs-10.99 |
| s117-stillbirth | stillbirth | neonatal | neonatal or stillbirth cause | VAs-11.01; scripts/icd11-parity/queries.json |
| s118-diab | diab | partial | partial word typed before the user finishes | scripts/icd11-parity/queries.json |
| s119-pneum | pneum | partial | partial word typed before the user finishes | scripts/icd11-parity/queries.json |
| s120-tuber | tuber | partial | partial word typed before the user finishes | scripts/icd11-parity/queries.json |
| s121-partial-myocard | myocard | partial | partial word typed before the user finishes (owner 2026-10-29) | owner 2026-10-29 |
| s122-partial-hyperten | hyperten | partial | partial word typed before the user finishes (owner 2026-10-29) | owner 2026-10-29 |
| s123-partial-cirrho | cirrho | partial | partial word typed before the user finishes (owner 2026-10-29) | owner 2026-10-29 |
| s124-partial-pneumon | pneumon | partial | partial word typed before the user finishes (owner 2026-10-29) | owner 2026-10-29 |
| s125-partial-tubercul | tubercul | partial | partial word typed before the user finishes (owner 2026-10-29) | owner 2026-10-29 |
| s126-partial-septic | septic | partial | partial word typed before the user finishes (owner 2026-10-29) | owner 2026-10-29 |
| s127-partial-haemorrh | haemorrh | partial | partial word typed before the user finishes (owner 2026-10-29) | owner 2026-10-29 |
| s128-partial-hemorrh | hemorrh | partial | partial word typed before the user finishes (owner 2026-10-29) | owner 2026-10-29 |
| s129-partial-eclamp | eclamp | partial | partial word typed before the user finishes (owner 2026-10-29) | owner 2026-10-29 |
| s130-partial-asphyx | asphyx | partial | partial word typed before the user finishes (owner 2026-10-29) | owner 2026-10-29 |
| s131-partial-prematur | prematur | partial | partial word typed before the user finishes (owner 2026-10-29) | owner 2026-10-29 |
| s132-partial-malign | malign | partial | partial word typed before the user finishes (owner 2026-10-29) | owner 2026-10-29 |
| s133-partial-diabet | diabet | partial | partial word typed before the user finishes (owner 2026-10-29) | owner 2026-10-29 |
| s134-partial-drown | drown | partial | partial word typed before the user finishes (owner 2026-10-29) | owner 2026-10-29 |
| s135-mid-mellitus | mellitus | mid-title | word in the middle or end of a title, not its first word (owner 2026-10-29) | owner 2026-10-29 |
| s136-mid-insipidus | insipidus | mid-title | word in the middle or end of a title, not its first word (owner 2026-10-29) | owner 2026-10-29 |
| s137-mid-sarcoma | sarcoma | mid-title | word in the middle or end of a title, not its first word (owner 2026-10-29) | owner 2026-10-29 |
| s138-mid-carcinoma | carcinoma | mid-title | word in the middle or end of a title, not its first word (owner 2026-10-29) | owner 2026-10-29 |
| s139-mid-infarction | infarction | mid-title | word in the middle or end of a title, not its first word (owner 2026-10-29) | owner 2026-10-29 |
| s140-mid-failure | failure | mid-title | word in the middle or end of a title, not its first word (owner 2026-10-29) | owner 2026-10-29 |
| s141-mid-fracture | fracture | mid-title | word in the middle or end of a title, not its first word (owner 2026-10-29) | owner 2026-10-29 |
| s142-mid-obstruction | obstruction | mid-title | word in the middle or end of a title, not its first word (owner 2026-10-29) | owner 2026-10-29 |
| s143-mid-haemorrhage | haemorrhage | mid-title | word in the middle or end of a title, not its first word (owner 2026-10-29) | owner 2026-10-29 |
| s144-mid-mellit | mellit | mid-title-partial | word in the middle or end of a title, not its first word (owner 2026-10-29) | owner 2026-10-29 |
| s145-mid-sarcom | sarcom | mid-title-partial | word in the middle or end of a title, not its first word (owner 2026-10-29) | owner 2026-10-29 |
| s146-syn-cardiac-infarction | cardiac infarction | synonym | common synonym, abbreviation or spelling variant for myocardial infarction (owner 2026-10-29) | owner 2026-10-29 |
| s147-syn-coronary-thrombosis | coronary thrombosis | synonym | common synonym, abbreviation or spelling variant for myocardial infarction (owner 2026-10-29) | owner 2026-10-29 |
| s148-syn-cerebrovascular-accident | cerebrovascular accident | synonym | common synonym, abbreviation or spelling variant for stroke (owner 2026-10-29) | owner 2026-10-29 |
| s149-syn-cerebral-infarction | cerebral infarction | synonym | common synonym, abbreviation or spelling variant for stroke (owner 2026-10-29) | owner 2026-10-29 |
| s150-syn-paralysis-attack | paralysis attack | synonym | common synonym, abbreviation or spelling variant for stroke (owner 2026-10-29) | owner 2026-10-29 |
| s151-syn-raised-blood-pressure | raised blood pressure | synonym | common synonym, abbreviation or spelling variant for hypertension (owner 2026-10-29) | owner 2026-10-29 |
| s152-syn-hypertensive-heart-disease | hypertensive heart disease | synonym | common synonym, abbreviation or spelling variant for hypertension (owner 2026-10-29) | owner 2026-10-29 |
| s153-syn-phthisis | phthisis | synonym | common synonym, abbreviation or spelling variant for tuberculosis (owner 2026-10-29) | owner 2026-10-29 |
| s154-syn-koch-s-disease | koch's disease | synonym | common synonym, abbreviation or spelling variant for tuberculosis (owner 2026-10-29) | owner 2026-10-29 |
| s155-syn-diabetes | diabetes | synonym | common synonym, abbreviation or spelling variant for diabetes mellitus (owner 2026-10-29) | owner 2026-10-29 |
| s156-syn-sugar-disease | sugar disease | synonym | common synonym, abbreviation or spelling variant for diabetes mellitus (owner 2026-10-29) | owner 2026-10-29 |
| s157-syn-type-2-diabetes | type 2 diabetes | synonym | common synonym, abbreviation or spelling variant for diabetes mellitus (owner 2026-10-29) | owner 2026-10-29 |
| s158-syn-renal-failure | renal failure | synonym | common synonym, abbreviation or spelling variant for chronic kidney disease (owner 2026-10-29) | owner 2026-10-29 |
| s159-syn-end-stage-renal-disease | end stage renal disease | synonym | common synonym, abbreviation or spelling variant for chronic kidney disease (owner 2026-10-29) | owner 2026-10-29 |
| s160-syn-uraemia | uraemia | synonym | common synonym, abbreviation or spelling variant for chronic kidney disease (owner 2026-10-29) | owner 2026-10-29 |
| s161-syn-uremia | uremia | synonym | common synonym, abbreviation or spelling variant for chronic kidney disease (owner 2026-10-29) | owner 2026-10-29 |
| s162-syn-cirrhosis-of-liver | cirrhosis of liver | synonym | common synonym, abbreviation or spelling variant for liver cirrhosis (owner 2026-10-29) | owner 2026-10-29 |
| s163-syn-hepatic-cirrhosis | hepatic cirrhosis | synonym | common synonym, abbreviation or spelling variant for liver cirrhosis (owner 2026-10-29) | owner 2026-10-29 |
| s164-syn-alcoholic-liver-disease | alcoholic liver disease | synonym | common synonym, abbreviation or spelling variant for liver cirrhosis (owner 2026-10-29) | owner 2026-10-29 |
| s165-syn-chronic-liver-disease | chronic liver disease | synonym | common synonym, abbreviation or spelling variant for liver cirrhosis (owner 2026-10-29) | owner 2026-10-29 |
| s166-syn-septicaemia | septicaemia | synonym | common synonym, abbreviation or spelling variant for sepsis (owner 2026-10-29) | owner 2026-10-29 |
| s167-syn-septicemia | septicemia | synonym | common synonym, abbreviation or spelling variant for sepsis (owner 2026-10-29) | owner 2026-10-29 |
| s168-syn-blood-poisoning | blood poisoning | synonym | common synonym, abbreviation or spelling variant for sepsis (owner 2026-10-29) | owner 2026-10-29 |
| s169-syn-bacteraemia | bacteraemia | synonym | common synonym, abbreviation or spelling variant for sepsis (owner 2026-10-29) | owner 2026-10-29 |
| s170-syn-diarrhea | diarrhea | synonym | common synonym, abbreviation or spelling variant for diarrhoea (owner 2026-10-29) | owner 2026-10-29 |
| s171-syn-loose-motions | loose motions | synonym | common synonym, abbreviation or spelling variant for diarrhoea (owner 2026-10-29) | owner 2026-10-29 |
| s172-syn-gastroenteritis | gastroenteritis | synonym | common synonym, abbreviation or spelling variant for diarrhoea (owner 2026-10-29) | owner 2026-10-29 |
| s173-syn-acute-watery-diarrhoea | acute watery diarrhoea | synonym | common synonym, abbreviation or spelling variant for diarrhoea (owner 2026-10-29) | owner 2026-10-29 |
| s174-syn-dysentery | dysentery | synonym | common synonym, abbreviation or spelling variant for diarrhoea (owner 2026-10-29) | owner 2026-10-29 |
| s175-syn-chest-infection | chest infection | synonym | common synonym, abbreviation or spelling variant for pneumonia (owner 2026-10-29) | owner 2026-10-29 |
| s176-syn-lower-respiratory-tract-infection | lower respiratory tract infection | synonym | common synonym, abbreviation or spelling variant for pneumonia (owner 2026-10-29) | owner 2026-10-29 |
| s177-syn-bronchopneumonia | bronchopneumonia | synonym | common synonym, abbreviation or spelling variant for pneumonia (owner 2026-10-29) | owner 2026-10-29 |
| s178-syn-lrti | LRTI | synonym | common synonym, abbreviation or spelling variant for pneumonia (owner 2026-10-29) | owner 2026-10-29 |
| s179-syn-chronic-obstructive-pulmonary-disease | chronic obstructive pulmonary disease | synonym | common synonym, abbreviation or spelling variant for COPD (owner 2026-10-29) | owner 2026-10-29 |
| s180-syn-chronic-bronchitis | chronic bronchitis | synonym | common synonym, abbreviation or spelling variant for COPD (owner 2026-10-29) | owner 2026-10-29 |
| s181-syn-emphysema | emphysema | synonym | common synonym, abbreviation or spelling variant for COPD (owner 2026-10-29) | owner 2026-10-29 |
| s182-syn-bronchial-asthma | bronchial asthma | synonym | common synonym, abbreviation or spelling variant for asthma (owner 2026-10-29) | owner 2026-10-29 |
| s183-syn-wheezing | wheezing | synonym | common synonym, abbreviation or spelling variant for asthma (owner 2026-10-29) | owner 2026-10-29 |
| s184-syn-cardiac-failure | cardiac failure | synonym | common synonym, abbreviation or spelling variant for heart failure (owner 2026-10-29) | owner 2026-10-29 |
| s185-syn-chf | CHF | synonym | common synonym, abbreviation or spelling variant for heart failure (owner 2026-10-29) | owner 2026-10-29 |
| s186-syn-left-ventricular-failure | left ventricular failure | synonym | common synonym, abbreviation or spelling variant for heart failure (owner 2026-10-29) | owner 2026-10-29 |
| s187-syn-enteric-fever | enteric fever | synonym | common synonym, abbreviation or spelling variant for typhoid (owner 2026-10-29) | owner 2026-10-29 |
| s188-syn-plasmodium-falciparum | plasmodium falciparum | synonym | common synonym, abbreviation or spelling variant for malaria (owner 2026-10-29) | owner 2026-10-29 |
| s189-syn-cerebral-malaria | cerebral malaria | synonym | common synonym, abbreviation or spelling variant for malaria (owner 2026-10-29) | owner 2026-10-29 |
| s190-syn-acquired-immunodeficiency-syndrome | acquired immunodeficiency syndrome | synonym | common synonym, abbreviation or spelling variant for HIV (owner 2026-10-29) | owner 2026-10-29 |
| s191-syn-anemia | anemia | synonym | common synonym, abbreviation or spelling variant for anaemia (owner 2026-10-29) | owner 2026-10-29 |
| s192-syn-iron-deficiency-anaemia | iron deficiency anaemia | synonym | common synonym, abbreviation or spelling variant for anaemia (owner 2026-10-29) | owner 2026-10-29 |
| s193-syn-low-haemoglobin | low haemoglobin | synonym | common synonym, abbreviation or spelling variant for anaemia (owner 2026-10-29) | owner 2026-10-29 |
| s194-syn-edema | edema | synonym | common synonym, abbreviation or spelling variant for oedema (owner 2026-10-29) | owner 2026-10-29 |
| s195-syn-swelling-of-feet | swelling of feet | synonym | common synonym, abbreviation or spelling variant for oedema (owner 2026-10-29) | owner 2026-10-29 |
| s196-syn-malignant-neoplasm | malignant neoplasm | synonym | common synonym, abbreviation or spelling variant for cancer (owner 2026-10-29) | owner 2026-10-29 |
| s197-syn-malignancy | malignancy | synonym | common synonym, abbreviation or spelling variant for cancer (owner 2026-10-29) | owner 2026-10-29 |
| s198-syn-tumour | tumour | synonym | common synonym, abbreviation or spelling variant for cancer (owner 2026-10-29) | owner 2026-10-29 |
| s199-syn-tumor | tumor | synonym | common synonym, abbreviation or spelling variant for cancer (owner 2026-10-29) | owner 2026-10-29 |
| s200-syn-leukemia | leukemia | synonym | common synonym, abbreviation or spelling variant for leukaemia (owner 2026-10-29) | owner 2026-10-29 |
| s201-syn-ischemic-heart-disease | ischemic heart disease | synonym | common synonym, abbreviation or spelling variant for ischaemic heart disease (owner 2026-10-29) | owner 2026-10-29 |
| s202-syn-coronary-artery-disease | coronary artery disease | synonym | common synonym, abbreviation or spelling variant for ischaemic heart disease (owner 2026-10-29) | owner 2026-10-29 |
| s203-syn-cad | CAD | synonym | common synonym, abbreviation or spelling variant for ischaemic heart disease (owner 2026-10-29) | owner 2026-10-29 |
| s204-syn-angina | angina | synonym | common synonym, abbreviation or spelling variant for ischaemic heart disease (owner 2026-10-29) | owner 2026-10-29 |
| s205-syn-motor-vehicle-accident | motor vehicle accident | synonym | common synonym, abbreviation or spelling variant for road traffic accident (owner 2026-10-29) | owner 2026-10-29 |
| s206-syn-road-accident | road accident | synonym | common synonym, abbreviation or spelling variant for road traffic accident (owner 2026-10-29) | owner 2026-10-29 |
| s207-syn-traffic-injury | traffic injury | synonym | common synonym, abbreviation or spelling variant for road traffic accident (owner 2026-10-29) | owner 2026-10-29 |
| s208-syn-self-harm | self harm | synonym | common synonym, abbreviation or spelling variant for suicide (owner 2026-10-29) | owner 2026-10-29 |
| s209-syn-intentional-self-harm | intentional self-harm | synonym | common synonym, abbreviation or spelling variant for suicide (owner 2026-10-29) | owner 2026-10-29 |
| s210-syn-poisoning-by-pesticide | poisoning by pesticide | synonym | common synonym, abbreviation or spelling variant for suicide (owner 2026-10-29) | owner 2026-10-29 |
| s211-syn-organophosphate-poisoning | organophosphate poisoning | synonym | common synonym, abbreviation or spelling variant for suicide (owner 2026-10-29) | owner 2026-10-29 |
| s212-syn-snakebite | snakebite | synonym | common synonym, abbreviation or spelling variant for snake bite (owner 2026-10-29) | owner 2026-10-29 |
| s213-syn-venomous-snake | venomous snake | synonym | common synonym, abbreviation or spelling variant for snake bite (owner 2026-10-29) | owner 2026-10-29 |
| s214-syn-envenomation | envenomation | synonym | common synonym, abbreviation or spelling variant for snake bite (owner 2026-10-29) | owner 2026-10-29 |
| s215-syn-burn-injury | burn injury | synonym | common synonym, abbreviation or spelling variant for burns (owner 2026-10-29) | owner 2026-10-29 |
| s216-syn-thermal-burn | thermal burn | synonym | common synonym, abbreviation or spelling variant for burns (owner 2026-10-29) | owner 2026-10-29 |
| s217-syn-scald | scald | synonym | common synonym, abbreviation or spelling variant for burns (owner 2026-10-29) | owner 2026-10-29 |
| s218-syn-postpartum-hemorrhage | postpartum hemorrhage | synonym | common synonym, abbreviation or spelling variant for postpartum haemorrhage (owner 2026-10-29) | owner 2026-10-29 |
| s219-syn-pre-eclampsia | pre-eclampsia | synonym | common synonym, abbreviation or spelling variant for eclampsia (owner 2026-10-29) | owner 2026-10-29 |
| s220-syn-toxaemia-of-pregnancy | toxaemia of pregnancy | synonym | common synonym, abbreviation or spelling variant for eclampsia (owner 2026-10-29) | owner 2026-10-29 |
| s221-syn-pregnancy-induced-hypertension | pregnancy induced hypertension | synonym | common synonym, abbreviation or spelling variant for eclampsia (owner 2026-10-29) | owner 2026-10-29 |
| s222-syn-perinatal-asphyxia | perinatal asphyxia | synonym | common synonym, abbreviation or spelling variant for birth asphyxia (owner 2026-10-29) | owner 2026-10-29 |
| s223-syn-birth-hypoxia | birth hypoxia | synonym | common synonym, abbreviation or spelling variant for birth asphyxia (owner 2026-10-29) | owner 2026-10-29 |
| s224-syn-hypoxic-ischaemic-encephalopathy | hypoxic ischaemic encephalopathy | synonym | common synonym, abbreviation or spelling variant for birth asphyxia (owner 2026-10-29) | owner 2026-10-29 |
| s225-syn-sepsis-of-newborn | sepsis of newborn | synonym | common synonym, abbreviation or spelling variant for neonatal sepsis (owner 2026-10-29) | owner 2026-10-29 |
| s226-syn-neonatal-infection | neonatal infection | synonym | common synonym, abbreviation or spelling variant for neonatal sepsis (owner 2026-10-29) | owner 2026-10-29 |
| s227-syn-brain-fever | brain fever | synonym | common synonym, abbreviation or spelling variant for meningitis (owner 2026-10-29) | owner 2026-10-29 |
| s228-syn-seizure-disorder | seizure disorder | synonym | common synonym, abbreviation or spelling variant for epilepsy (owner 2026-10-29) | owner 2026-10-29 |
| s229-syn-hepatitis | hepatitis | synonym | common synonym, abbreviation or spelling variant for jaundice (owner 2026-10-29) | owner 2026-10-29 |
| s230-syn-yellow-fever | yellow fever | synonym | common synonym, abbreviation or spelling variant for jaundice (owner 2026-10-29) | owner 2026-10-29 |
| s231-syn-viral-hepatitis | viral hepatitis | synonym | common synonym, abbreviation or spelling variant for jaundice (owner 2026-10-29) | owner 2026-10-29 |
| s232-syn-dengue-fever | dengue fever | synonym | common synonym, abbreviation or spelling variant for dengue (owner 2026-10-29) | owner 2026-10-29 |
| s233-syn-dengue-haemorrhagic-fever | dengue haemorrhagic fever | synonym | common synonym, abbreviation or spelling variant for dengue (owner 2026-10-29) | owner 2026-10-29 |
| s234-syn-submersion | submersion | synonym | common synonym, abbreviation or spelling variant for drowning (owner 2026-10-29) | owner 2026-10-29 |
| s235-syn-accidental-fall | accidental fall | synonym | common synonym, abbreviation or spelling variant for fall (owner 2026-10-29) | owner 2026-10-29 |
| s236-syn-sudden-cardiac-death | sudden cardiac death | synonym | common synonym, abbreviation or spelling variant for cardiac arrest (owner 2026-10-29) | owner 2026-10-29 |
| s237-syn-heart-stopped | heart stopped | synonym | common synonym, abbreviation or spelling variant for cardiac arrest (owner 2026-10-29) | owner 2026-10-29 |
| s238-syn-senescence | senescence | synonym | common synonym, abbreviation or spelling variant for senility (owner 2026-10-29) | owner 2026-10-29 |
