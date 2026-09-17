import { describe, expect, it } from "vitest";

import {
  WHO_VA_DRAFT_SCHEMA_VERSION,
  WHO_VA_FORM_VERSION,
  compileInstrumentDefinition,
  createWhoVaInitialDataFromPrefill,
  createWhoVaSession,
  decodeWhoVaDraft,
  parseExpression,
  type InstrumentDefinition,
  type WhoVaDeceasedPrefill,
  type WhoVaFormProps,
  type WhoVaPlatformServices
} from "../src/index.js";

const instrument: InstrumentDefinition = {
  id: "model-test",
  title: "Model test",
  version: "1",
  defaultLanguage: "English (en)",
  sourceFile: "model-test.json",
  sections: [{ name: "main", sourceRow: 1, order: 1, label: { en: "Main" } }],
  questions: [
    {
      name: "name",
      order: 1,
      sourceRow: 2,
      sourceType: "text",
      dataType: "string",
      control: "text",
      label: { en: "Name" },
      hint: {},
      guidance: {},
      required: false,
      readOnly: false,
      constraintMessage: {},
      sectionPath: ["main"]
    }
  ]
};

describe("cohesive runtime models", () => {
  it("compiles only structurally coherent instruments", () => {
    expect(compileInstrumentDefinition(instrument).definition).toBe(instrument);

    expect(() =>
      compileInstrumentDefinition({
        ...instrument,
        questions: [instrument.questions[0]!, { ...instrument.questions[0]!, order: 2 }]
      })
    ).toThrow(/duplicate question/i);

    expect(() =>
      compileInstrumentDefinition({
        ...instrument,
        questions: [{ ...instrument.questions[0]!, control: "integer", dataType: "string" }]
      })
    ).toThrow(/integer.*number/i);

    expect(() =>
      compileInstrumentDefinition({
        ...instrument,
        questions: [{ ...instrument.questions[0]!, sectionPath: ["missing"] }]
      })
    ).toThrow(/unknown section/i);
    expect(() =>
      compileInstrumentDefinition({
        ...instrument,
        questions: [
          {
            ...instrument.questions[0]!,
            validation: { required: true, dataType: "string", constraintMessage: {} }
          }
        ]
      })
    ).toThrow(/validation\.required/i);
  });

  it("rejects malformed expression calls and divergent source/AST pairs", () => {
    expect(() => parseExpression("selected(${answer})")).toThrow(/selected.*2 arguments/i);
    expect(() => parseExpression("today(1)")).toThrow(/today.*0 arguments/i);
    expect(() => parseExpression("if(true, 1)")).toThrow(/if.*3 arguments/i);

    expect(() =>
      compileInstrumentDefinition({
        ...instrument,
        questions: [
          {
            ...instrument.questions[0]!,
            relevant: { source: "true", ast: { type: "literal", value: false } }
          }
        ]
      })
    ).toThrow(/expression source and AST differ/i);
  });

  it("does not allow a language refresh to change questionnaire semantics", () => {
    const session = createWhoVaSession(instrument);
    expect(() =>
      session.setInstrument({
        ...instrument,
        questions: [{ ...instrument.questions[0]!, required: true, label: { en: "Translated name" } }]
      })
    ).toThrow(/semantic contract/i);

    expect(() =>
      session.setInstrument({
        ...instrument,
        questions: [{ ...instrument.questions[0]!, label: { en: "Translated name" } }]
      })
    ).not.toThrow();
  });

  it("decodes and migrates versioned draft envelopes", () => {
    const decoded = decodeWhoVaDraft({
      id: "1f2cc7d7-f88a-449c-8523-b47be9c52a40",
      instrumentId: instrument.id,
      instrumentVersion: instrument.version,
      currentSection: "main",
      createdAt: "2026-07-20T00:00:00.000Z",
      updatedAt: "2026-07-20T00:01:00.000Z",
      data: { name: "Amina" }
    });

    expect(decoded.schemaVersion).toBe(WHO_VA_DRAFT_SCHEMA_VERSION);
    expect(decoded.formVersion).toBe(WHO_VA_FORM_VERSION);
    expect(decoded.data.name).toBe("Amina");
    expect(() => decodeWhoVaDraft({ id: "broken", data: [] })).toThrow(/draft/i);
    expect(() => decodeWhoVaDraft({ ...decoded, schemaVersion: 999 })).toThrow(/draft schema version/i);
  });

  it("rejects contradictory host prefill evidence instead of choosing silently", () => {
    expect(() =>
      createWhoVaInitialDataFromPrefill({
        deceased: { dateOfBirth: "1980-01-01", ageInYears: 45 } as WhoVaDeceasedPrefill
      })
    ).toThrow(/dateOfBirth.*ageInYears/i);
    expect(() =>
      createWhoVaInitialDataFromPrefill({
        deceased: { dateOfDeath: "2026-01-01", yearOfDeath: "2026" } as WhoVaDeceasedPrefill
      })
    ).toThrow(/dateOfDeath.*yearOfDeath/i);
  });

  it("returns discriminated navigation outcomes", () => {
    const session = createWhoVaSession(instrument);
    const result = session.next();

    expect(result).toMatchObject({ status: "completed", advanced: true, completed: true });
    if (result.status === "completed") {
      expect(result.result).toMatchObject({
        valid: true,
        formVersion: WHO_VA_FORM_VERSION,
        instrumentId: instrument.id,
        instrumentVersion: instrument.version
      });
    }
  });

  it("keeps section navigation aligned to current form relevance", () => {
    const branchingInstrument: InstrumentDefinition = {
      ...instrument,
      sections: [
        instrument.sections[0]!,
        {
          name: "child_branch",
          sourceRow: 10,
          order: 2,
          label: { en: "Child branch" },
          relevant: { source: "${age_group} = 'child'" }
        }
      ],
      questions: [
        instrument.questions[0]!,
        {
          ...instrument.questions[0]!,
          name: "age_group",
          order: 2,
          sourceRow: 11,
          dataType: "string",
          control: "singleChoice",
          label: { en: "Age group" },
          choices: [{ value: "child", label: { en: "Child" }, sourceRow: 11 }],
          sectionPath: ["main"]
        },
        {
          ...instrument.questions[0]!,
          name: "child_note",
          order: 3,
          sourceRow: 12,
          label: { en: "Child note" },
          sectionPath: ["child_branch"]
        }
      ]
    };
    const session = createWhoVaSession(branchingInstrument);

    expect(session.getSnapshot().visibleSections.map((section) => section.name)).toEqual(["main"]);
    expect(session.goToSection("child_branch")).toBe(false);

    session.setAnswer("age_group", "child");
    expect(session.getSnapshot().visibleSections.map((section) => section.name)).toEqual([
      "main",
      "child_branch"
    ]);
    expect(session.goToSection("child_branch")).toBe(true);
    expect(session.getSnapshot().questions.map((question) => question.name)).toEqual(["child_note"]);
  });
});

function assertTypeBoundaries(): void {
  const session = createWhoVaSession(instrument);

  // @ts-expect-error A caller-owned session cannot also receive replacement initial data.
  const invalidFormProps: WhoVaFormProps = { session, instrument, initialData: {} };

  // @ts-expect-error Known birth date and fallback age are mutually exclusive evidence.
  const invalidPrefill: WhoVaDeceasedPrefill = { dateOfBirth: "1980-01-01", ageInYears: 45 };

  const invalidPlatform: WhoVaPlatformServices = {
    // @ts-expect-error Audio capture must return an attachment reference, not an arbitrary answer.
    captureAudio: async () => 42
  };

  void invalidFormProps;
  void invalidPrefill;
  void invalidPlatform;
}

void assertTypeBoundaries;
