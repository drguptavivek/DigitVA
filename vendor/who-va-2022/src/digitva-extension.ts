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
export const DIGITVA_LAYER_EXTENSIONS = ["narration_language", "abha", "death_summary", "medical_records"] as const;
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

/** Values match DigitVA's `mas_languages.language_code` and the ODK choice list. */
export const DIGITVA_NARRATION_LANGUAGES: ReadonlyArray<{ value: string; label: string }> = [
  { value: "english", label: "English" },
  { value: "hindi", label: "Hindi" },
  { value: "marathi", label: "Marathi" },
  { value: "kannada", label: "Kannada" },
  { value: "malayalam", label: "Malayalam" },
  { value: "bangla", label: "Bangla" }
];

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
 * and narrative image sit next to the narrative text. Groups whose extension
 * is absent from `enabledExtensions` are omitted entirely.
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

  const sections: InstrumentSection[] =
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
  return { sections, deceasedQuestions, narrativeQuestions, documentQuestions };
}
