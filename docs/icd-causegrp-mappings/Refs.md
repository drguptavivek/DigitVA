



## CMEA10  for physican agreemnent
Central Medical Evaluation Agreement 10 (CMEA-10) codes, which group related ICD-10 codes into broader, clinically similar categories [37] 
If both codes fell within the same CMEA-10 group, the record was considered in agreement. - Bucekts for physician agreement



REFERENCE - Aleksandrowicz L, Malhotra V, Dikshit R, Gupta PC, Kumar R, Sheth J, et al. Performance criteria for verbal autopsy‐based systems to estimate national causes of death: development and application to the Indian Million Death Study. BMC Med. 2014;12:21. https://doi.org/10. 1186/1741‐7015‐12‐21

CROSS-REFERECE - Computer assisted verbal autopsy: comparing large language models to physicians for assigning causes to 6939 deaths in Sierra Leone from 2019–2022  Richard Wen1*, Anteneh Tesfaye Assalif1,2, Andy Sze‐Heng Lee1, Rajeev Kamadod1, Asha Behdinan1, Ronald Carshon‐Marsh1, Catherine Meh1, Thomas Kai Sze Ng1, Patrick Brown1, Prabhat Jha1* and Rashid Ansumana2



## CGHR-10 categories for tabulation of ICD-10 codes
CGHR-10 categories 
 - Adults - 12–69 years - 19 categories
 - Children (28 days to 11 years) - 10 categories
 - Neonates (under 28 days) - 7 categories


CROSS - REFERECE - Computer assisted verbal autopsy: comparing large language models to physicians for assigning causes to 6939 deaths in Sierra Leone from 2019–2022  Richard Wen1*, Anteneh Tesfaye Assalif1,2, Andy Sze‐Heng Lee1, Rajeev Kamadod1, Asha Behdinan1, Ronald Carshon‐Marsh1, Catherine Meh1, Thomas Kai Sze Ng1, Patrick Brown1, Prabhat Jha1* and Rashid Ansumana2



## LAVA -  Each age group has a pre-specified label set (34 adult, 21 child, 6 neonatal), derived from the PHMRC reference standard verbal autopsy study and WHO PHMRC Reference STandard Cause Groups

- ADULTS - 34 : AIDS; Acute Myocardial Infarction; Asthma; Bite of Venomous Animal; Breast Cancer; COPD; Cervical Cancer; Cirrhosis; Colorectal Cancer; Diabetes; Diarrhea/Dysentery; Drowning; Epilepsy; Esophageal Cancer; Falls; Fires; Homicide; Leukemia/Lymphomas; Lung Cancer; Malaria; Maternal; Other Cardiovascular Diseases; Other Infectious Diseases; Other Injuries; Other Non-communicable Diseases; Pneumonia; Poisonings; Prostate Cancer; Renal Failure; Road Traffic; Stomach Cancer; Stroke; Suicide; TB.
- CHILDREN - 21: AIDS; Bite of Venomous Animal; Diarrhea/Dysentery; Drowning; Encephalitis; Falls; Fires; Hemorrhagic fever; Malaria; Measles; Meningitis; Other Cancers; Other Cardiovascular Diseases; Other Defined Causes of Child Deaths; Other Digestive Diseases; Other Infectious Diseases; Pneumonia; Poisonings; Road Traffic; Sepsis; Violent Death.
- NEONATES - 6: Birth asphyxia; Congenital malformation; Meningitis/Sepsis; Pneumonia; Preterm Delivery; Stillbirth.


*Used In*
- LAVA: Language Model Assisted Verbal Autopsy for  Cause-of-Death Determination  Yiqun T. Chen yiqunc@jhu.edu Departments of Biostatistics and Computer Science, Johns Hopkins University  Tyler H. McCormick tylermc@uw.edu Department of Statistics, University of Washington  Li Liu lliu26@jhu.edu Departments of Population, Family and Reproductive Health and International Health, Johns Hopkins University  Abhirup Datta abhidatta@jhu.edu Department of Biostatistics, Johns Hopkins University

- 


## SMART-VA Analyze

- internal SmartVA cause selection -> reported `cause34`
- reported `cause34` -> ICD10-like code
- reported `cause34` -> GBD level 1 group

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

## WHO-VA 2022


