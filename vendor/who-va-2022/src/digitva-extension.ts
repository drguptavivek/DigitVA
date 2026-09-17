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
export const DIGITVA_MEDICAL_IMAGE_SLOTS = 30;
export const DIGITVA_DEATH_IMAGE_SLOTS = 5;

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
 * Build the DigitVA questions, numbered after `startOrder`, under the given
 * parent section. `narrativeAnchorPath` is the section of Id10476 so the
 * narration language and narrative image sit next to the narrative text.
 */
export function createDigitVaExtension(startOrder: number, narrativeAnchorPath: string[], parentSection: string): {
  sections: InstrumentSection[];
  narrativeQuestions: InstrumentQuestion[];
  documentQuestions: InstrumentQuestion[];
} {
  let order = startOrder;
  const next = () => ++order;

  const narrativeQuestions: InstrumentQuestion[] = [
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
  ];

  const docPath = [...narrativeAnchorPath.slice(0, -1), DIGITVA_DOCUMENTS_SECTION];
  const documentQuestions: InstrumentQuestion[] = [
    integer("md_count", next(), docPath, "How many medical document pages will you photograph?", DIGITVA_MEDICAL_IMAGE_SLOTS)
  ];
  for (let slot = 1; slot <= DIGITVA_MEDICAL_IMAGE_SLOTS; slot += 1) {
    documentQuestions.push(
      image(`md_im${slot}`, next(), docPath, `Medical Document Image ${String(slot).padStart(2, "0")}`, `\${md_count} >= ${slot}`)
    );
  }
  documentQuestions.push(
    integer("ds_count", next(), docPath, "How many death document pages will you photograph?", DIGITVA_DEATH_IMAGE_SLOTS)
  );
  for (let slot = 1; slot <= DIGITVA_DEATH_IMAGE_SLOTS; slot += 1) {
    documentQuestions.push(
      image(`ds_im${slot}`, next(), docPath, `Death Document Image ${String(slot).padStart(2, "0")}`, `\${ds_count} >= ${slot}`)
    );
  }

  const sections: InstrumentSection[] = [
    {
      name: DIGITVA_DOCUMENTS_SECTION,
      sourceRow: 0,
      order: startOrder + 1,
      label: { en: "Medical and death documents" },
      ageGroup: "ALL",
      parent: parentSection
    }
  ];
  return { sections, narrativeQuestions, documentQuestions };
}
