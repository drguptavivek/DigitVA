---
title: WHO 2022 ICD-11 coding-selectability policy draft (2026-01)
doc_type: migration-artifact
status: draft
owner: engineering
last_updated: 2026-09-24
---

# WHO 2022 ICD-11 coding-selectability policy draft (2026-01)

Written by `flask icd11 policy-draft` (`app/services/icd11_policy_draft_service.py`). Rules: `docs/policy/who-2022-icd11-coding-allowability.md` (draft, owner review pending). Nothing here has been imported into any database and no migration reads this folder.

Sources: annex ICD-11 ranges `docs/icd-causegrp-mappings/ICD-to-VA-Buckets/who_2022_va_cause_list_icd10_icd11.csv`; catalogue `mas_icd11_mms` release `2026-01`; ICD-10 restrictions `docs/icd-causegrp-mappings/migration-artifacts/who-2022-va-icd-cod-2026-revision/who_2022_icd10_2019_2_policy_reviewed.json`; ICD-10 to ICD-11 map `docs/icd-causegrp-mappings/migration-artifacts/icd11-icd10-mapping-tables-2025-01-base-2026-09-16/10To11MapToOneCategory.txt` (2025-01 codes translated to 2026-01 through the `MovedTo` rows of `docs/icd-causegrp-mappings/migration-artifacts/icd11-mms-changes-2026-01-vs-2025-01-2026-09-16/changes_MMS_2026-01_2025-01-main.xlsx`).

Owner decisions of 2026-09-24 applied: chapter 20 (LA-LD) is all ages (no neonate chapter rule), and ICD-10 O/P/Q restrictions (blanket chapter rules) are never carried to any ICD-11 code; chapters 18 and 19 take their chapter rules instead.

## Files

- `who_2022_icd11_mms_2026_01_policy_draft.json`: the selectable categories in the format `flask icd11 policy-import` and the admin ICD-11 browser import read. It is a full replacement: every active category it does not list (chapter X included) is reset to not selectable with no sex/age/note. Items carry no `policy_status`, so an import leaves each row's status as it is.
- `icd11_policy_review.csv`: every category outside chapter X, with the rule that decided it, its sex/age, where they came from, and review flags.

## Totals

- Active categories: 35664
- Selectable: 16204 (residual 4802, with children 2350)

## Categories per rule

| Rule | Categories |
|---|---:|
| `annex` | 16156 |
| `decision_5a` | 48 |
| `excluded_chapter` | 19260 |
| `excluded_emergency` | 17 |
| `not_in_annex` | 183 |

## Selectable per chapter

| Chapter | Categories | Selectable |
|---|---:|---:|
| 01 | 1025 | 1025 |
| 02 | 1247 | 1247 |
| 03 | 262 | 262 |
| 04 | 257 | 257 |
| 05 | 637 | 535 |
| 06 | 858 | 814 |
| 07 | 79 | 78 |
| 08 | 842 | 842 |
| 09 | 703 | 703 |
| 10 | 151 | 151 |
| 11 | 583 | 583 |
| 12 | 344 | 342 |
| 13 | 970 | 951 |
| 14 | 785 | 774 |
| 15 | 426 | 426 |
| 16 | 545 | 544 |
| 17 | 68 | 68 |
| 18 | 522 | 520 |
| 19 | 625 | 624 |
| 20 | 1323 | 1323 |
| 21 | 1241 | 1241 |
| 22 | 1982 | 1982 |
| 23 | 909 | 909 |
| 24 | 851 | 0 |
| 25 | 20 | 3 |
| 26 | 1120 | 0 |
| V | 130 | 0 |
| X | 17159 | 0 |

## Sex and age restrictions (selectable rows)

| Sex | Age | Categories |
|---|---|---:|
| both | infant | 4 |
| both | neonate | 625 |
| female | adult | 520 |
| female | all | 80 |
| male | all | 20 |

| Source of the restriction | Categories |
|---|---:|
| block | 99 |
| chapter 18 | 520 |
| chapter 19 | 624 |
| children | 1 |
| icd10 | 5 |

## Review flags (chapter X excluded)

| Flag | Categories |
|---|---:|
| `children_differ` | 1 |
| `past_written_end` | 12 |

## Not selectable outside the excluded chapters

Categories no annex range or decision 5a covers (`not_in_annex`) and the non-RA01 emergency codes (`excluded_emergency`):

- `5C52` Inborn errors of lipid metabolism (not_in_annex)
- `5C52.0` Inborn errors of fatty acid oxidation or ketone body metabolism (not_in_annex)
- `5C52.00` Disorders of carnitine transport or the carnitine cycle (not_in_annex)
- `5C52.01` Disorders of mitochondrial fatty acid oxidation (not_in_annex)
- `5C52.02` Disorders of ketone body metabolism (not_in_annex)
- `5C52.03` Sjögren-Larsson syndrome (not_in_annex)
- `5C52.0Y` Other specified inborn errors of fatty acid oxidation or ketone body metabolism (not_in_annex)
- `5C52.0Z` Inborn errors of fatty acid oxidation or ketone body metabolism, unspecified (not_in_annex)
- `5C52.1` Inborn errors of sterol metabolism (not_in_annex)
- `5C52.10` Disorders of cholesterol synthesis (not_in_annex)
- `5C52.11` Bile acid synthesis defect with cholestasis (not_in_annex)
- `5C52.1Y` Other specified inborn errors of sterol metabolism (not_in_annex)
- `5C52.1Z` Inborn errors of sterol metabolism, unspecified (not_in_annex)
- `5C52.2` Neutral lipid storage disease (not_in_annex)
- `5C53` Inborn errors of energy metabolism (not_in_annex)
- `5C53.0` Disorders of pyruvate metabolism (not_in_annex)
- `5C53.00` Pyruvate kinase deficiency (not_in_annex)
- `5C53.01` Lactate dehydrogenase deficiency (not_in_annex)
- `5C53.02` Pyruvate dehydrogenase complex deficiency (not_in_annex)
- `5C53.03` Pyruvate carboxylase deficiency (not_in_annex)
- `5C53.0Y` Other specified disorders of pyruvate metabolism (not_in_annex)
- `5C53.0Z` Disorders of pyruvate metabolism, unspecified (not_in_annex)
- `5C53.1` Disorders of the citric acid cycle (not_in_annex)
- `5C53.2` Disorders of mitochondrial oxidative phosphorylation (not_in_annex)
- `5C53.20` Mitochondrial DNA depletion syndromes (not_in_annex)
- `5C53.21` Multiple mitochondrial DNA deletion syndromes (not_in_annex)
- `5C53.22` Coenzyme Q10 deficiency (not_in_annex)
- `5C53.23` Mitochondrial protein translation defects (not_in_annex)
- `5C53.24` Leigh syndrome (not_in_annex)
- `5C53.25` Isolated ATP synthase deficiency (not_in_annex)
- `5C53.2Y` Other specified disorders of mitochondrial oxidative phosphorylation (not_in_annex)
- `5C53.2Z` Disorders of mitochondrial oxidative phosphorylation, unspecified (not_in_annex)
- `5C53.3` Disorders of mitochondrial membrane transport (not_in_annex)
- `5C53.30` Mitochondrial substrate carrier disorders (not_in_annex)
- `5C53.31` Mitochondrial protein import disorders (not_in_annex)
- `5C53.3Y` Other specified disorders of mitochondrial membrane transport (not_in_annex)
- `5C53.3Z` Disorders of mitochondrial membrane transport, unspecified (not_in_annex)
- `5C53.4` Disorders of creatine metabolism (not_in_annex)
- `5C53.Y` Other specified inborn errors of energy metabolism (not_in_annex)
- `5C53.Z` Inborn errors of energy metabolism, unspecified (not_in_annex)
- `5C54` Inborn errors of glycosylation or other specified protein modification (not_in_annex)
- `5C54.0` Disorders of protein N-glycosylation (not_in_annex)
- `5C54.1` Disorders of protein O-glycosylation (not_in_annex)
- `5C54.2` Disorders of multiple glycosylation or other pathways (not_in_annex)
- `5C54.Y` Other specified inborn errors of glycosylation or other specified protein modification (not_in_annex)
- `5C54.Z` Inborn errors of glycosylation or protein modification, unspecified (not_in_annex)
- `5C56` Lysosomal diseases (not_in_annex)
- `5C56.4` Disorders of sialic acid metabolism (not_in_annex)
- `5C56.Y` Other specified lysosomal diseases (not_in_annex)
- `5C56.Z` Lysosomal diseases, unspecified (not_in_annex)
- `5C57` Peroxisomal diseases (not_in_annex)
- `5C57.0` Disorders of peroxisome biogenesis (not_in_annex)
- `5C57.1` Disorders of peroxisomal alpha-, beta- or omega-oxidation (not_in_annex)
- `5C57.Y` Other specified peroxisomal diseases (not_in_annex)
- `5C57.Z` Peroxisomal diseases, unspecified (not_in_annex)
- `5C59` Inborn errors of neurotransmitter metabolism (not_in_annex)
- `5C59.0` Disorders of biogenic amine metabolism (not_in_annex)
- `5C59.00` Disorders of catecholamine synthesis (not_in_annex)
- `5C59.01` Disorders of pterin metabolism (not_in_annex)
- `5C59.0Y` Other specified disorders of biogenic amine metabolism (not_in_annex)
- `5C59.0Z` Disorders of biogenic amine metabolism, unspecified (not_in_annex)
- `5C59.1` Disorders of gamma aminobutyric acid metabolism (not_in_annex)
- `5C59.2` Disorders of pyridoxine metabolism (not_in_annex)
- `5C59.Y` Other specified inborn errors of neurotransmitter metabolism (not_in_annex)
- `5C59.Z` Inborn errors of neurotransmitter metabolism, unspecified (not_in_annex)
- `5C5Y` Other specified inborn errors of metabolism (not_in_annex)
- `5C5Z` Inborn errors of metabolism, unspecified (not_in_annex)
- `5C60` Disorders of amino acid absorption or transport (not_in_annex)
- `5C60.0` Oculocerebrorenal syndrome (not_in_annex)
- `5C60.1` Cystinosis (not_in_annex)
- `5C60.2` Cystinuria (not_in_annex)
- `5C60.Y` Other specified disorders of amino acid absorption or transport (not_in_annex)
- `5C60.Z` Disorders of amino acid absorption or transport, unspecified (not_in_annex)
- `5C61` Disorders of carbohydrate absorption or transport (not_in_annex)
- `5C61.0` Glucose-galactose malabsorption (not_in_annex)
- `5C61.1` Maltase-glucoamylase deficiency (not_in_annex)
- `5C61.2` Congenital sucrase-isomaltase deficiency (not_in_annex)
- `5C61.3` Alpha, alpha trehalase deficiency (not_in_annex)
- `5C61.4` Acquired monosaccharide malabsorption (not_in_annex)
- `5C61.40` Fructose malabsorption (not_in_annex)
- `5C61.4Y` Other specified acquired monosaccharide malabsorption (not_in_annex)
- `5C61.4Z` Acquired monosaccharide malabsorption, unspecified (not_in_annex)
- `5C61.5` Disorders of facilitated glucose transport (not_in_annex)
- `5C61.Y` Other specified disorders of carbohydrate absorption or transport (not_in_annex)
- `5C61.Z` Disorders of carbohydrate absorption or transport, unspecified (not_in_annex)
- `5C62` Disorders of lipid absorption or transport (not_in_annex)
- `5C63` Disorders of vitamin or non-protein cofactor absorption or transport (not_in_annex)
- `5C63.0` Disorders of cobalamin metabolism or transport (not_in_annex)
- `5C63.1` Disorders of folate metabolism or transport (not_in_annex)
- `5C63.2` Disorders of vitamin D metabolism or transport (not_in_annex)
- `5C63.20` Hypocalcaemic vitamin D dependent rickets (not_in_annex)
- `5C63.21` Hypocalcaemic vitamin D resistant rickets (not_in_annex)
- `5C63.22` Hypophosphataemic rickets (not_in_annex)
- `5C63.2Y` Other specified disorders of vitamin D metabolism or transport (not_in_annex)
- `5C63.2Z` Disorders of vitamin D metabolism or transport, unspecified (not_in_annex)
- `5C63.Y` Other specified disorders of vitamin or non-protein cofactor absorption or transport (not_in_annex)
- `5C63.Z` Disorders of vitamin or non-protein cofactor absorption or transport, unspecified (not_in_annex)
- `5C6Y` Other specified disorders of metabolite absorption or transport (not_in_annex)
- `5C6Z` Disorders of metabolite absorption or transport, unspecified (not_in_annex)
- `5C78` Fluid overload (not_in_annex)
- `5C7Y` Other specified disorders of fluid, electrolyte or acid-base balance (not_in_annex)
- `5C7Z` Disorders of fluid, electrolyte or acid-base balance, unspecified (not_in_annex)
- `6A00` Disorders of intellectual development (not_in_annex)
- `6A00.0` Disorder of intellectual development, mild (not_in_annex)
- `6A00.1` Disorder of intellectual development, moderate (not_in_annex)
- `6A00.2` Disorder of intellectual development, severe (not_in_annex)
- `6A00.3` Disorder of intellectual development, profound (not_in_annex)
- `6A00.4` Disorder of intellectual development, provisional (not_in_annex)
- `6A00.Z` Disorders of intellectual development, unspecified (not_in_annex)
- `6A01` Developmental speech or language disorders (not_in_annex)
- `6A01.0` Developmental speech sound disorder (not_in_annex)
- `6A01.1` Developmental speech fluency disorder (not_in_annex)
- `6A01.2` Developmental language disorder (not_in_annex)
- `6A01.20` Developmental language disorder with impairment of receptive and expressive language (not_in_annex)
- `6A01.21` Developmental language disorder with impairment of mainly expressive language (not_in_annex)
- `6A01.22` Developmental language disorder with impairment of mainly pragmatic language (not_in_annex)
- `6A01.23` Developmental language disorder, with other specified language impairment (not_in_annex)
- `6A01.Y` Other specified developmental speech or language disorders (not_in_annex)
- `6A01.Z` Developmental speech or language disorders, unspecified (not_in_annex)
- `6A02` Autism spectrum disorder (not_in_annex)
- `6A02.0` Autism spectrum disorder without disorder of intellectual development and with mild or no impairment of functional language (not_in_annex)
- `6A02.1` Autism spectrum disorder with disorder of intellectual development and with mild or no impairment of functional language (not_in_annex)
- `6A02.2` Autism spectrum disorder without disorder of intellectual development and with impaired functional language (not_in_annex)
- `6A02.3` Autism spectrum disorder with disorder of intellectual development and with impaired functional language (not_in_annex)
- `6A02.5` Autism spectrum disorder with disorder of intellectual development and with absence of functional language (not_in_annex)
- `6A02.Y` Other specified autism spectrum disorder (not_in_annex)
- `6A02.Z` Autism spectrum disorder, unspecified (not_in_annex)
- `6A03` Developmental learning disorder (not_in_annex)
- `6A03.0` Developmental learning disorder with impairment in reading (not_in_annex)
- `6A03.1` Developmental learning disorder with impairment in written expression (not_in_annex)
- `6A03.2` Developmental learning disorder with impairment in mathematics (not_in_annex)
- `6A03.3` Developmental learning disorder with other specified impairment of learning (not_in_annex)
- `6A03.Z` Developmental learning disorder, unspecified (not_in_annex)
- `6A04` Developmental motor coordination disorder (not_in_annex)
- `6A05` Attention deficit hyperactivity disorder (not_in_annex)
- `6A05.0` Attention deficit hyperactivity disorder, predominantly inattentive presentation (not_in_annex)
- `6A05.1` Attention deficit hyperactivity disorder, predominantly hyperactive-impulsive presentation (not_in_annex)
- `6A05.2` Attention deficit hyperactivity disorder, combined presentation (not_in_annex)
- `6A05.Y` Attention deficit hyperactivity disorder, other specified presentation (not_in_annex)
- `6A05.Z` Attention deficit hyperactivity disorder, presentation unspecified (not_in_annex)
- `6A06` Stereotyped movement disorder (not_in_annex)
- `6A06.0` Stereotyped movement disorder without self-injury (not_in_annex)
- `6A06.1` Stereotyped movement disorder with self-injury (not_in_annex)
- `6A06.Z` Stereotyped movement disorder, unspecified (not_in_annex)
- `6A0Y` Other specified neurodevelopmental disorders (not_in_annex)
- `6A0Z` Neurodevelopmental disorders, unspecified (not_in_annex)
- `7A82` Sleep-related leg cramps (not_in_annex)
- `CA44` Pyothorax (not_in_annex)
- `CA4Y` Other specified lung infections (not_in_annex)
- `DB95` Drug-induced or toxic liver disease (not_in_annex)
- `DB95.0` Drug-induced or toxic liver disease with acute hepatic necrosis or acute hepatitis (not_in_annex)
- `DB95.1` Drug-induced or toxic liver disease with chronic hepatitis (not_in_annex)
- `DB95.10` Drug-induced or toxic liver disease with chronic hepatitis with cirrhosis (not_in_annex)
- `DB95.11` Drug-induced or toxic liver disease with chronic hepatitis without cirrhosis (not_in_annex)
- `DB95.1Z` Drug-induced or toxic liver disease with chronic hepatitis, unspecified (not_in_annex)
- `DB95.2` Drug-induced or toxic liver disease with cholestasis (not_in_annex)
- `DB95.20` Chronic drug-induced or toxic liver disease with cholestasis (not_in_annex)
- `DB95.2Y` Other specified drug-induced or toxic liver disease with cholestasis (not_in_annex)
- `DB95.2Z` Drug-induced or toxic liver disease with cholestasis, unspecified (not_in_annex)
- `DB95.3` Drug-induced or toxic liver disease with fatty liver (not_in_annex)
- `DB95.30` Drug-induced or toxic liver disease with chronic fatty liver disease (not_in_annex)
- `DB95.3Y` Other specified drug-induced or toxic liver disease with fatty liver (not_in_annex)
- `DB95.3Z` Drug-induced or toxic liver disease with fatty liver, unspecified (not_in_annex)
- `DB95.4` Drug-induced or toxic liver disease with granulomatous hepatitis (not_in_annex)
- `DB95.6` Drug-induced or toxic liver disease with vascular disorders of the liver (not_in_annex)
- `DB95.7` Drug-induced or toxic liver disease with liver tumours (not_in_annex)
- `DB95.Y` Other specified drug-induced or toxic liver disease (not_in_annex)
- `DB95.Z` Drug-induced or toxic liver disease, unspecified (not_in_annex)
- `ED01` Simulated skin disease (not_in_annex)
- `EE00` Hyperhidrosis (not_in_annex)
- `EE00.0` Localised hyperhidrosis (not_in_annex)
- `EE00.00` Palmoplantar hyperhidrosis (not_in_annex)
- `EE00.01` Axillary hyperhidrosis (not_in_annex)
- `EE00.02` Craniofacial hyperhidrosis (not_in_annex)
- `EE00.0Y` Other specified localised hyperhidrosis (not_in_annex)
- `EE00.0Z` Localised hyperhidrosis, unspecified (not_in_annex)
- `EE00.1` Primary generalised hyperhidrosis (not_in_annex)
- `EE00.Z` Hyperhidrosis, unspecified (not_in_annex)
- `EE21` Epidermal fragility (not_in_annex)
- `GB83` Nephronophthisis (not_in_annex)
- `JB0A` Certain specified obstetric trauma (not_in_annex)
- `JB64` Certain maternal diseases classifiable elsewhere but complicating pregnancy, childbirth or the puerperium (not_in_annex)
- `KD30` Birth depression (not_in_annex)
- `RA00` Conditions of uncertain aetiology and emergency use (excluded_emergency)
- `RA00.0` Vaping related disorder (excluded_emergency)
- `RA02` Post COVID-19 condition (excluded_emergency)
- `RA03` Multisystem inflammatory syndrome associated with COVID-19 (excluded_emergency)
- `RA04` International emergency code 05 (excluded_emergency)
- `RA05` International emergency code 06 (excluded_emergency)
- `RA06` International emergency code 07 (excluded_emergency)
- `RA07` International emergency code 08 (excluded_emergency)
- `RA08` International emergency code 09 (excluded_emergency)
- `RA09` International emergency code 10 (excluded_emergency)
- `RA20` National emergency code 01 (excluded_emergency)
- `RA21` National emergency code 02 (excluded_emergency)
- `RA22` National emergency code 03 (excluded_emergency)
- `RA23` National emergency code 04 (excluded_emergency)
- `RA24` National emergency code 05 (excluded_emergency)
- `RA25` National emergency code 06 (excluded_emergency)
- `RA26` National emergency code 07 (excluded_emergency)

## Range issues

- none
