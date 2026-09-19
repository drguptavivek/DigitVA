/**
 * DigitVA additions to the WHO 2022 instrument.
 *
 * These are the interviewer-answered fields DigitVA's ODK form carries beyond
 * the WHO questionnaire: narration language, the narrative image, medical and
 * death document images. (The WHO instrument already has `comment`.) Field names and relevance
 * mirror the ODK form so the stored payload is identical in shape to a synced
 * ODK submission (see docs/planning/who-va-2022-web-intake-plan.md, §3).
 *
 * Context fields (Site, unique_id, survey_state, org_<level>_code, ...) are
 * not questions: DigitVA's server injects them from the death register and
 * the interviewer's organization unit after validation.
 */
import { parseExpression } from "./engine/expression.js";

import type { InstrumentChoice, InstrumentQuestion, InstrumentSection, SourceExpression } from "./types.js";

export const DIGITVA_DOCUMENTS_SECTION = "digitva_documents";
/** ABHA number: 14 digits, optionally grouped 2-4-4-4 with hyphens. */
export const ABHA_NUMBER_PATTERN = "^([0-9]{14}|[0-9]{2}-[0-9]{4}-[0-9]{4}-[0-9]{4})$";
/** ABHA address: 4-32 characters of letters, digits, dot or underscore, then @abdm (or @sbx in the sandbox). */
export const ABHA_ADDRESS_PATTERN = "^[A-Za-z0-9._]{4,32}@(abdm|sbx)$";
export const DIGITVA_MEDICAL_IMAGE_SLOTS = 30;
export const DIGITVA_DEATH_IMAGE_SLOTS = 5;

/**
 * Extension names a project's `enabled_extensions` can carry. `digitva_core`,
 * `social_autopsy`, `intake_screen` and `geography` gate content outside this
 * file (the always-present WHO base and the client's own screens); the other
 * four gate the question groups this module emits.
 */
export const DIGITVA_LAYER_EXTENSIONS = [
  "narration_language",
  "abha",
  "death_summary",
  "medical_records",
  "social_autopsy"
] as const;
export type DigitVaLayerExtension = (typeof DIGITVA_LAYER_EXTENSIONS)[number];
/** All eight names DigitVA recognises in `enabled_extensions` (see docs/policy/va-form-project-configuration.md). */
export const ALL_DIGITVA_EXTENSIONS = [
  "digitva_core",
  "social_autopsy",
  "intake_screen",
  "geography",
  "narration_language",
  "death_summary",
  "medical_records",
  "abha"
] as const;

/**
 * Yes/no/refused choices, matching the WHO instrument's own `YES_NO_REF` list
 * (e.g. Id10020, Id10022) so the gate questions render and validate exactly
 * like WHO's own consent-style questions.
 */
const YES_NO_REF: ReadonlyArray<{ value: string; label: string }> = [
  { value: "yes", label: "Yes" },
  { value: "no", label: "No" },
  { value: "ref", label: "Refused to answer" }
];

/**
 * ND01's own `YES_NO` list (`sa02`), reused under the WHO base's own
 * `YES_NO` list name: the base already defines `yes`/`Yes`, `no`/`No` with
 * identical values, so this is the same choice list, not a lookalike (see
 * the "Choice-code convention" guard in
 * docs/policy/va-form-project-configuration.md).
 */
const YES_NO_CHOICES: ReadonlyArray<{ value: string; label: string }> = [
  { value: "yes", label: "Yes" },
  { value: "no", label: "No" }
];

/** Values match DigitVA's `mas_languages.language_code` and the ODK choice list. */
export const DIGITVA_NARRATION_LANGUAGES: ReadonlyArray<{ value: string; label: string }> = [
  { value: "english", label: "English" },
  { value: "hindi", label: "Hindi" },
  { value: "marathi", label: "Marathi" },
  { value: "kannada", label: "Kannada" },
  { value: "malayalam", label: "Malayalam" },
  { value: "bangla", label: "Bangla" }
];

/**
 * ND01's own social-autopsy choice lists (`sas01`..`sas07`, `sa_tu`), kept as
 * that form's ordinal values verbatim rather than DigitVA's own semantic-code
 * convention -- see docs/policy/va-form-project-configuration.md,
 * "Choice-code convention": `mas_choice_mappings` already carries live
 * ND01-ordinal rows for `sa01` against form type `WHO_2022_VA_SOCIAL`, and
 * app/services/submission_analytics_mv.py:371-374 projects `sa01`..`sa19`
 * raw into the COD-snapshot CSV export. Do not renumber these.
 */
const SAS01_HEALTH_INSURANCE: ReadonlyArray<{ value: string; label: string }> = [
  { value: "1", label: "Private Cashless" },
  { value: "2", label: "Private Reimbursement" },
  { value: "3", label: "Ayushman Bharat" },
  { value: "4", label: "State/Central Government" },
  { value: "5", label: "Employee based(ESI/CGHS/Others)" },
  { value: "6", label: "None" }
];

const SAS02_NO_CARE_REASONS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "1", label: "Died very soon" },
  { value: "2", label: "Financial barrier" },
  { value: "3", label: "Lack of transport" },
  { value: "4", label: "Lack of people to help" },
  { value: "5", label: "Health facility too far" },
  { value: "6", label: "Others" }
];

const SAS03_FIRST_CONSULTATION_TYPE: ReadonlyArray<{ value: string; label: string }> = [
  { value: "1", label: "Home visit by physician" },
  { value: "2", label: "Individual Practitioner" },
  { value: "3", label: "Small hospital" },
  { value: "4", label: "Medium Hospital" },
  { value: "5", label: "Large hospital (Government/private medical colleges)" },
  { value: "6", label: "Others" }
];

const SAS04_PLACE_OF_DEATH: ReadonlyArray<{ value: string; label: string }> = [
  { value: "1", label: "Home" },
  { value: "2", label: "HCF" },
  { value: "3", label: "In transit" },
  { value: "4", label: "Others" }
];

const SAS05_TRANSPORT_TO_HCF: ReadonlyArray<{ value: string; label: string }> = [
  { value: "1", label: "Govt Ambulance" },
  { value: "2", label: "Non- Govt Ambulance" },
  { value: "3", label: "Own Motor Vehicle" },
  { value: "4", label: "Own non-motor vehicle" },
  { value: "5", label: "Hired Motor Vehicle" },
  { value: "6", label: "Hired non-motor vehicle" },
  { value: "7", label: "Physically carried" },
  { value: "8", label: "Others" }
];

const SAS06_TRANSPORT_TO_REFERRED: ReadonlyArray<{ value: string; label: string }> = [
  { value: "1", label: "Govt Ambulance" },
  { value: "2", label: "Non- Govt Ambulance" },
  { value: "3", label: "Own Motor Vehicle" },
  { value: "4", label: "Own non-motor vehicle" },
  { value: "5", label: "Physically carried" },
  { value: "6", label: "Not Applicable" }
];

const SAS07_REFERRAL_REASONS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "1", label: "Lack of facility" },
  { value: "2", label: "Specialist not available" },
  { value: "3", label: "Financial constraints" },
  { value: "4", label: "Patient/family decision" }
];

/** ND01's own time-unit list for the event-chronology questions (`sa_tu13`..`sa_tu19`). */
const SA_TU_UNITS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "minutes", label: "Minutes" },
  { value: "hours", label: "Hours" },
  { value: "days", label: "Days" },
  { value: "na", label: "Not Applicable" }
];

/**
 * ND01's own yes/no/don't-know list. Distinct from the WHO base's
 * `YES_NO_DK_REF` (which also carries a "refused" value): reusing that key
 * would silently diverge from ND01's `sa10`/`sa12` choice set, so this is
 * authored under its own name instead (see the "Choice-code convention"
 * guard in docs/policy/va-form-project-configuration.md).
 */
const SA_YES_NO_DK: ReadonlyArray<{ value: string; label: string }> = [
  { value: "yes", label: "Yes" },
  { value: "no", label: "No" },
  { value: "DK", label: "Doesn't Know" }
];

/** ND01's own literal constraint on the event-chronology duration fields (`sa13`..`sa19`). */
const SA_TIME_VALUE_CONSTRAINT = "regex(.,'^(?!0{1,3}$)\\d{1,3}$')";
const SA_TIME_VALUE_CONSTRAINT_MESSAGE = "Kindly enter a valid 1 to 3 digit number.";

function expression(source: string): SourceExpression {
  return { source, ast: parseExpression(source) };
}

function choices(list: ReadonlyArray<{ value: string; label: string }>): InstrumentChoice[] {
  return list.map((item) => ({ value: item.value, label: { en: item.label }, sourceRow: 0 }));
}

function base(
  name: string,
  order: number,
  sectionPath: string[],
  label: string,
  overrides: Partial<InstrumentQuestion>
): InstrumentQuestion {
  return {
    name,
    order,
    sourceRow: 0,
    sourceType: "digitva-extension",
    dataType: "string",
    control: "text",
    label: { en: label },
    hint: {},
    guidance: {},
    required: false,
    readOnly: false,
    constraintMessage: {},
    validation: { required: false, dataType: "string", constraintMessage: {} },
    sectionPath,
    ageGroup: "ALL",
    ...overrides
  } as InstrumentQuestion;
}

function image(name: string, order: number, sectionPath: string[], label: string, relevantSource?: string): InstrumentQuestion {
  return base(name, order, sectionPath, label, {
    sourceType: "image",
    dataType: "attachment",
    control: "image",
    validation: { required: false, dataType: "attachment", constraintMessage: {} },
    ...(relevantSource ? { relevant: expression(relevantSource) } : {})
  });
}

/** A yes/no/refused gate question, e.g. `ds_available` / `md_available`. */
function yesNoRef(name: string, order: number, sectionPath: string[], label: string): InstrumentQuestion {
  return base(name, order, sectionPath, label, {
    sourceType: "select_one YES_NO_REF",
    control: "singleChoice",
    listName: "YES_NO_REF",
    choices: choices(YES_NO_REF),
    validation: {
      required: false,
      dataType: "string",
      constraintMessage: {},
      choiceValues: YES_NO_REF.map((item) => item.value)
    }
  });
}

function integer(name: string, order: number, sectionPath: string[], label: string, max: number): InstrumentQuestion {
  const constraint = `. >= 0 and . <= ${max}`;
  return base(name, order, sectionPath, label, {
    sourceType: "integer",
    dataType: "number",
    control: "integer",
    hint: { en: `0 to ${max}` },
    constraint: expression(constraint),
    constraintMessage: { en: `Enter a number from 0 to ${max}` },
    validation: {
      required: false,
      dataType: "number",
      constraint: expression(constraint),
      constraintMessage: { en: `Enter a number from 0 to ${max}` }
    }
  });
}

/** A required `select_one`, e.g. ND01's `sa01`, `sa06`, `sa07`, `sa10`. */
function selectOneRequired(
  name: string,
  order: number,
  sectionPath: string[],
  label: string,
  listName: string,
  choiceList: ReadonlyArray<{ value: string; label: string }>,
  overrides: Partial<InstrumentQuestion> = {}
): InstrumentQuestion {
  return base(name, order, sectionPath, label, {
    sourceType: `select_one ${listName}`,
    control: "singleChoice",
    listName,
    choices: choices(choiceList),
    required: true,
    validation: {
      required: true,
      dataType: "string",
      constraintMessage: {},
      choiceValues: choiceList.map((item) => item.value)
    },
    ...overrides
  });
}

/** A required `select_multiple`, e.g. ND01's `sa03`, `sa11`. */
function selectMultipleRequired(
  name: string,
  order: number,
  sectionPath: string[],
  label: string,
  listName: string,
  choiceList: ReadonlyArray<{ value: string; label: string }>,
  overrides: Partial<InstrumentQuestion> = {}
): InstrumentQuestion {
  return base(name, order, sectionPath, label, {
    sourceType: `select_multiple ${listName}`,
    dataType: "string[]",
    control: "multipleChoice",
    listName,
    choices: choices(choiceList),
    required: true,
    validation: {
      required: true,
      dataType: "string[]",
      constraintMessage: {},
      choiceValues: choiceList.map((item) => item.value)
    },
    ...overrides
  });
}

/** A required free-text field that is only relevant once `relevantSource` holds, e.g. ND01's `sa06_a`, `sa04`, `sa05_a`, `sa07_a`. */
function requiredText(
  name: string,
  order: number,
  sectionPath: string[],
  label: string,
  relevantSource: string
): InstrumentQuestion {
  return base(name, order, sectionPath, label, {
    required: true,
    relevant: expression(relevantSource),
    validation: { required: true, dataType: "string", constraintMessage: {} }
  });
}

/** ND01's `sa09`: how many HCF the patient was taken to, 0-99. */
function hcfCount(name: string, order: number, sectionPath: string[], label: string): InstrumentQuestion {
  const constraint = ". >= 0 and . < 100";
  const constraintMessage = "The number of HCF the patient was taken can only range between 0 to 99 (both included).";
  return base(name, order, sectionPath, label, {
    sourceType: "integer",
    dataType: "number",
    control: "integer",
    required: true,
    constraint: expression(constraint),
    constraintMessage: { en: constraintMessage },
    validation: {
      required: true,
      dataType: "number",
      constraint: expression(constraint),
      constraintMessage: { en: constraintMessage }
    }
  });
}

/**
 * One ND01 event-chronology step: a `select_one sa_tu` time-unit question
 * followed by its free-text duration, relevant only once the unit is
 * answered and not "na" (any case) -- reproduced as ND01's own literal
 * string comparisons (`sa13`..`sa19`), not rewritten as `selected()`, because
 * that would change which answers reveal the field.
 */
function chronologyStep(
  order: { next: () => number },
  sectionPath: string[],
  tuName: string,
  tuLabel: string,
  valueName: string,
  valueLabel: string,
  valueHint?: string,
  tuHint?: string
): InstrumentQuestion[] {
  const tu = selectOneRequired(tuName, order.next(), sectionPath, tuLabel, "sa_tu", SA_TU_UNITS, tuHint ? { hint: { en: tuHint } } : {});
  const relevantSource = `\${${tuName}}!="na" and \${${tuName}}!="Na" and \${${tuName}}!="nA" and \${${tuName}}!="NA" and \${${tuName}}!=""`;
  const value = base(valueName, order.next(), sectionPath, valueLabel, {
    required: true,
    relevant: expression(relevantSource),
    constraint: expression(SA_TIME_VALUE_CONSTRAINT),
    constraintMessage: { en: SA_TIME_VALUE_CONSTRAINT_MESSAGE },
    ...(valueHint ? { hint: { en: valueHint } } : {}),
    validation: {
      required: true,
      dataType: "string",
      constraint: expression(SA_TIME_VALUE_CONSTRAINT),
      constraintMessage: { en: SA_TIME_VALUE_CONSTRAINT_MESSAGE }
    }
  });
  return [tu, value];
}

/**
 * ND01's `socialautopsy` group: `socioeconomic`, `reachinghealthcare` and
 * `eventchronology`, reproduced verbatim (choice codes, relevance,
 * constraints) per docs/policy/va-form-project-configuration.md -- this is
 * the documented exemption from DigitVA's own semantic-choice-code
 * convention, not an oversight. `rootPath` is the section path this group's
 * questions sit under (one level above `narrativeAnchorPath`'s own group);
 * `parentSection` is the top-level section the `socialautopsy` group itself
 * nests under.
 */
function createSocialAutopsyExtension(
  next: () => number,
  rootPath: string[],
  parentSection: string
): { sections: InstrumentSection[]; questions: InstrumentQuestion[] } {
  const orderRef = { next };

  const saRoot = "socialautopsy";
  const socioeconomicPath = [...rootPath, saRoot, "socioeconomic"];
  const reachingPath = [...rootPath, saRoot, "reachinghealthcare"];
  const eventPath = [...rootPath, saRoot, "eventchronology"];

  const questions: InstrumentQuestion[] = [];

  // socioeconomic (field-list, always relevant once social_autopsy is on).
  questions.push(
    selectOneRequired(
      "sa01",
      next(),
      socioeconomicPath,
      "1. Did the deceased have any health insurance?",
      "sas01",
      SAS01_HEALTH_INSURANCE
    ),
    selectOneRequired("sa06", next(), socioeconomicPath, "2. Place of death", "sas04", SAS04_PLACE_OF_DEATH),
    requiredText("sa06_a", next(), socioeconomicPath, "2.1 Please specify the other place of death", "selected(${sa06}, '4')"),
    selectOneRequired(
      "sa02",
      next(),
      socioeconomicPath,
      "3. Was any health care sought for the illness that led to death?",
      "YES_NO",
      YES_NO_CHOICES
    ),
    selectMultipleRequired(
      "sa03",
      next(),
      socioeconomicPath,
      "4. If No health care was sought or treatment provided as per the advise, what were the reasons for the same?",
      "sas02",
      SAS02_NO_CARE_REASONS,
      { relevant: expression("selected(${sa02}, 'no')") }
    ),
    requiredText("sa04", next(), socioeconomicPath, "4.1 Please specify the other reasons", "selected(${sa03}, '6')"),
    selectOneRequired(
      "sa05",
      next(),
      socioeconomicPath,
      "5. If yes, type of first consultation",
      "sas03",
      SAS03_FIRST_CONSULTATION_TYPE,
      {
        relevant: expression("selected(${sa02}, 'yes')"),
        hint: {
          en:
            "Note:\nSmall Hospital(small nursing homes & clinics; <30 beds)\nMedium Hospital (polyclinics; 30-200 beds)\nLarge Hospital (corporate hospitals, Government/private medical colleges; ≥ 200 beds)"
        }
      }
    ),
    requiredText(
      "sa05_a",
      next(),
      socioeconomicPath,
      "5.1 Please specify the other type of first consultation",
      "selected(${sa05}, '6')"
    )
  );

  // reachinghealthcare (field-list, relevant selected(${sa02}, 'yes')).
  questions.push(
    selectOneRequired(
      "sa07",
      next(),
      reachingPath,
      "6. What transport was used to reach HCF from home",
      "sas05",
      SAS05_TRANSPORT_TO_HCF
    ),
    requiredText(
      "sa07_a",
      next(),
      reachingPath,
      "6.1 Please specify the other transport used to reach HCF from home",
      "selected(${sa07}, '8')"
    ),
    hcfCount("sa09", next(), reachingPath, "7. How many HCF did you take the patient"),
    selectOneRequired("sa10", next(), reachingPath, "8. Was the patient referred to another health facility?", "YES_NO_DK", SA_YES_NO_DK),
    selectMultipleRequired("sa11", next(), reachingPath, "9. What was the reason for referral?", "sas07", SAS07_REFERRAL_REASONS, {
      relevant: expression("selected(${sa10}, 'yes')")
    }),
    selectOneRequired("sa12", next(), reachingPath, "10. Did the patient go to the referred institution?", "YES_NO_DK", SA_YES_NO_DK, {
      relevant: expression("selected(${sa10}, 'yes')")
    }),
    selectOneRequired(
      "sa08",
      next(),
      reachingPath,
      "11. In case of referral to higher center, transport used",
      "sas06",
      SAS06_TRANSPORT_TO_REFERRED,
      { relevant: expression("selected(${sa12}, 'yes')") }
    )
  );

  // eventchronology (field-list, relevant selected(${sa02}, 'yes')).
  questions.push(
    base("sa_note", next(), eventPath, "Take the first onset of sign/symptom as “zero”. Please give the time taken for each of the following action points.", {
      sourceType: "note",
      dataType: "none",
      control: "note",
      validation: { required: false, dataType: "none", constraintMessage: {} }
    })
  );
  questions.push(
    ...chronologyStep(
      orderRef,
      eventPath,
      "sa_tu13",
      "12. Time taken to make the decision to seek healthcare",
      "sa13",
      "12.1. Enter the time taken to make the decision to seek healthcare (in ${sa_tu13})"
    ),
    ...chronologyStep(
      orderRef,
      eventPath,
      "sa_tu14",
      "13. Time taken to make transport arrangement",
      "sa14",
      "13.1. Enter the time taken to make transport arrangement (in ${sa_tu14})"
    ),
    ...chronologyStep(
      orderRef,
      eventPath,
      "sa_tu15",
      "14. Time taken to reach first HCF/physician consultant",
      "sa15",
      "14.1. Enter the time taken to reach first HCF/physician consultation (in ${sa_tu15})"
    ),
    ...chronologyStep(
      orderRef,
      eventPath,
      "sa_tu16",
      "15. Time taken for the doctor to attend the patient",
      "sa16",
      "15.1. Enter the time taken for the doctor to attend the patient (in ${sa_tu16})"
    ),
    ...chronologyStep(
      orderRef,
      eventPath,
      "sa_tu17",
      "16. Time taken for the initiation of the treatment or referral to higher center",
      "sa17",
      "16.1. Enter the time taken for the initiation of the treatment or referral to higher center (in ${sa_tu17})"
    ),
    ...chronologyStep(
      orderRef,
      eventPath,
      "sa_tu18",
      "17. Time taken to reach the HCF where he/she died",
      "sa18",
      "17.1. Enter the time taken to reach the HCF where he/she died  (in ${sa_tu18})"
    ),
    ...chronologyStep(
      orderRef,
      eventPath,
      "sa_tu19",
      "18. Unit for Time of Death",
      "sa19",
      "18.1. Time of Death (in ${sa_tu19})",
      "Please enter the total duration from the time the decision to seek healthcare was made until the time of death (in ${sa_tu19}).",
      "Please mention the total duration from the time the decision to seek healthcare was made until the time of death."
    )
  );

  // Section order values are drawn from the same counter as the questions
  // above (not checked for cross-question uniqueness, but kept distinct on
  // general principle rather than reused arbitrarily).
  const sections: InstrumentSection[] = [
    {
      name: saRoot,
      sourceRow: 0,
      order: next(),
      label: { en: "Social Autopsy Questionnaire" },
      ageGroup: "ALL",
      parent: parentSection
    },
    {
      name: "socioeconomic",
      sourceRow: 0,
      order: next(),
      label: { en: "Socio Economic Details" },
      ageGroup: "ALL",
      parent: saRoot
    },
    {
      name: "reachinghealthcare",
      sourceRow: 0,
      order: next(),
      label: { en: "Reaching health care facility (HCF)" },
      ageGroup: "ALL",
      parent: saRoot,
      relevant: expression("selected(${sa02}, 'yes')")
    },
    {
      name: "eventchronology",
      sourceRow: 0,
      order: next(),
      label: { en: "Event Chronology" },
      ageGroup: "ALL",
      parent: saRoot,
      relevant: expression("selected(${sa02}, 'yes')")
    }
  ];

  return { sections, questions };
}

/**
 * `Id10013` records that consent was taken; the interview cannot proceed
 * (the `consented` group's own relevance) without it. This field is a
 * separate, optional record of *how* — in person or by phone — and does not
 * change what `Id10013` or `consented` mean. Relevant only once consent was
 * given, mirroring the `consented` group's own gate.
 */
export function createConsentModeQuestion(order: number, sectionPath: string[]): InstrumentQuestion {
  const choicesList: ReadonlyArray<{ value: string; label: string }> = [
    { value: "in_person", label: "In person" },
    { value: "telephonic", label: "Telephonic" }
  ];
  return base("consent_mode", order, sectionPath, "Mode in which consent was taken", {
    sourceType: "select_one CONSENT_MODE",
    control: "singleChoice",
    listName: "CONSENT_MODE",
    choices: choices(choicesList),
    relevant: expression("selected(${Id10013}, 'yes')"),
    validation: {
      required: false,
      dataType: "string",
      constraintMessage: {},
      choiceValues: choicesList.map((item) => item.value)
    }
  });
}

/**
 * Build the DigitVA layer questions, numbered after `startOrder`, under the
 * given parent section, for the extensions named in `enabledExtensions`.
 * `narrativeAnchorPath` is the section of Id10476 so the narration language
 * and narrative image sit next to the narrative text; it also anchors the
 * `socialautopsy` group's own top-level section, one level up. Groups whose
 * extension is absent from `enabledExtensions` are omitted entirely.
 */
export function createDigitVaExtension(
  startOrder: number,
  narrativeAnchorPath: string[],
  parentSection: string,
  deceasedAnchorPath: string[],
  enabledExtensions: ReadonlySet<string> | ReadonlyArray<string>
): {
  sections: InstrumentSection[];
  deceasedQuestions: InstrumentQuestion[];
  narrativeQuestions: InstrumentQuestion[];
  documentQuestions: InstrumentQuestion[];
  socialAutopsyQuestions: InstrumentQuestion[];
} {
  const enabled = enabledExtensions instanceof Set ? enabledExtensions : new Set(enabledExtensions);
  let order = startOrder;
  const next = () => ++order;

  const deceasedQuestions: InstrumentQuestion[] = [];
  if (enabled.has("abha")) {
    deceasedQuestions.push(
      base("abha_number", next(), deceasedAnchorPath, "ABHA number of the deceased (14 digits), if known", {
        hint: { en: "Ayushman Bharat Health Account number, e.g. 12-3456-7890-1234" },
        constraint: expression(`regex(., '${ABHA_NUMBER_PATTERN}')`),
        constraintMessage: { en: "Enter the 14-digit ABHA number" },
        validation: {
          required: false,
          dataType: "string",
          constraint: expression(`regex(., '${ABHA_NUMBER_PATTERN}')`),
          constraintMessage: { en: "Enter the 14-digit ABHA number" }
        }
      }),
      base("abha_address", next(), deceasedAnchorPath, "ABHA address of the deceased, if known", {
        hint: { en: "e.g. name@abdm" },
        constraint: expression(`regex(., '${ABHA_ADDRESS_PATTERN}')`),
        constraintMessage: { en: "Enter an ABHA address such as name@abdm" },
        validation: {
          required: false,
          dataType: "string",
          constraint: expression(`regex(., '${ABHA_ADDRESS_PATTERN}')`),
          constraintMessage: { en: "Enter an ABHA address such as name@abdm" }
        }
      })
    );
  }

  const narrativeQuestions: InstrumentQuestion[] = [];
  if (enabled.has("narration_language")) {
    narrativeQuestions.push(
      base("narr_language", next(), narrativeAnchorPath, "Narration language", {
        sourceType: "select_one language",
        control: "singleChoice",
        listName: "language",
        choices: choices(DIGITVA_NARRATION_LANGUAGES),
        required: true,
        validation: {
          required: true,
          dataType: "string",
          constraintMessage: {},
          choiceValues: DIGITVA_NARRATION_LANGUAGES.map((item) => item.value)
        }
      }),
      image(
        "imagenarr",
        next(),
        narrativeAnchorPath,
        "(Capture image for narration) Photograph of the written narrative, if the narrative was recorded on paper"
      )
    );
  }

  const docPath = [...narrativeAnchorPath.slice(0, -1), DIGITVA_DOCUMENTS_SECTION];
  const documentQuestions: InstrumentQuestion[] = [];
  if (enabled.has("medical_records")) {
    documentQuestions.push(yesNoRef("md_available", next(), docPath, "Are there any medical documents available related to the deceased?"));
    const mdCount = integer("md_count", next(), docPath, "How many medical document pages will you photograph?", DIGITVA_MEDICAL_IMAGE_SLOTS);
    documentQuestions.push({ ...mdCount, relevant: expression("selected(${md_available}, 'yes')") });
    for (let slot = 1; slot <= DIGITVA_MEDICAL_IMAGE_SLOTS; slot += 1) {
      documentQuestions.push(
        image(`md_im${slot}`, next(), docPath, `Medical Document Image ${String(slot).padStart(2, "0")}`, `\${md_count} >= ${slot}`)
      );
    }
  }
  if (enabled.has("death_summary")) {
    documentQuestions.push(
      yesNoRef("ds_available", next(), docPath, "Is there any death summary / certificate document (images) available for the deceased?")
    );
    const dsCount = integer("ds_count", next(), docPath, "How many death document pages will you photograph?", DIGITVA_DEATH_IMAGE_SLOTS);
    documentQuestions.push({ ...dsCount, relevant: expression("selected(${ds_available}, 'yes')") });
    for (let slot = 1; slot <= DIGITVA_DEATH_IMAGE_SLOTS; slot += 1) {
      documentQuestions.push(
        image(`ds_im${slot}`, next(), docPath, `Death Document Image ${String(slot).padStart(2, "0")}`, `\${ds_count} >= ${slot}`)
      );
    }
  }

  const documentSections: InstrumentSection[] =
    documentQuestions.length > 0
      ? [
          {
            name: DIGITVA_DOCUMENTS_SECTION,
            sourceRow: 0,
            order: startOrder + 1,
            label: { en: "Medical and death documents" },
            ageGroup: "ALL",
            parent: parentSection
          }
        ]
      : [];

  let socialAutopsyQuestions: InstrumentQuestion[] = [];
  let socialAutopsySections: InstrumentSection[] = [];
  if (enabled.has("social_autopsy")) {
    const socialAutopsy = createSocialAutopsyExtension(next, narrativeAnchorPath.slice(0, -1), parentSection);
    socialAutopsyQuestions = socialAutopsy.questions;
    socialAutopsySections = socialAutopsy.sections;
  }

  const sections: InstrumentSection[] = [...documentSections, ...socialAutopsySections];
  return { sections, deceasedQuestions, narrativeQuestions, documentQuestions, socialAutopsyQuestions };
}
