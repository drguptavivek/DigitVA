import { describe, expect, it } from "vitest";

import { createWhoVaSession, validateSubmission, whoVa2022Instrument } from "../src/index.js";

function contextQuestion(name: string, sectionPath: string[], order: number) {
  return {
    name,
    order,
    sourceRow: order,
    sourceType: "system",
    dataType: "string" as const,
    control: "system" as const,
    label: { en: name },
    hint: {},
    guidance: {},
    required: false,
    readOnly: true,
    constraintMessage: {},
    sectionPath
  };
}

describe("universal instrument session", () => {
  it("applies XLSForm group relevance separately from question relevance", () => {
    const sourceSection = whoVa2022Instrument.sections.find((section) => section.name === "illhistory");
    const neonatalQuestion = whoVa2022Instrument.questions.find((question) => question.name === "Id10351");
    const childQuestion = whoVa2022Instrument.questions.find((question) => question.name === "Id10408");
    if (!sourceSection || !neonatalQuestion || !childQuestion?.relevant || !neonatalQuestion.relevant) {
      throw new Error("Canonical illhistory fixtures are unavailable");
    }
    const { parent: _parent, ...topLevelSection } = sourceSection;
    const instrument = {
      ...whoVa2022Instrument,
      sections: [topLevelSection],
      questions: [
        contextQuestion("isChild", [sourceSection.name], 1),
        contextQuestion("isNeonatal", [sourceSection.name], 2),
        contextQuestion("Id10114", [sourceSection.name], 3),
        { ...neonatalQuestion, sectionPath: [sourceSection.name] },
        { ...childQuestion, sectionPath: [sourceSection.name] }
      ]
    };

    const childSession = createWhoVaSession(instrument, {
      initialData: { isChild: "1", isNeonatal: "0", Id10114: "no" }
    });
    expect(childSession.getSnapshot().currentSection.name).toBe("illhistory");
    expect(childSession.getSnapshot().questions.map((question) => question.name)).toEqual(["Id10408"]);

    const groupGatedInstrument = {
      ...instrument,
      sections: [{ ...topLevelSection, relevant: neonatalQuestion.relevant }],
      questions: [
        contextQuestion("isChild", [sourceSection.name], 1),
        contextQuestion("isNeonatal", [sourceSection.name], 2),
        contextQuestion("Id10114", [sourceSection.name], 3),
        { ...childQuestion, sectionPath: [sourceSection.name] }
      ]
    };
    expect(() =>
      createWhoVaSession(groupGatedInstrument, {
        initialData: { isChild: "1", isNeonatal: "0", Id10114: "no" }
      })
    ).toThrow("Instrument has no visible sections");
  });

  it("initializes system metadata and exposes the first WHO section", () => {
    const now = new Date("2026-07-17T10:30:00.000Z");
    const session = createWhoVaSession(whoVa2022Instrument, { now: () => now });
    const snapshot = session.getSnapshot();

    expect(snapshot.currentSection.name).toBe("Interviewer");
    expect(snapshot.data.Id10012).toBe("2026-07-17");
    expect(snapshot.data.Id10011).toBe(now.toISOString());
  });

  it("uses the same validator before navigation and submission", () => {
    const session = createWhoVaSession(whoVa2022Instrument);
    expect(session.next().advanced).toBe(false);
    expect(
      session.getSnapshot().issues.some((issue) => issue.question === "Id10010" && issue.code === "required")
    ).toBe(true);

    session.setAnswer("Id10010", "Interviewer One");
    session.setAnswer("Id10010a", 35);
    session.setAnswer("Id10010b", "female");
    session.setAnswer("Id10010c", "INT-1");
    session.setAnswer("language", "en");

    expect(session.next().advanced).toBe(true);
    expect(session.getSnapshot().currentSection.name).toBe("presets");
  });

  it("rejects values outside the question contract before mutating state", () => {
    const session = createWhoVaSession(whoVa2022Instrument);
    expect(() => session.setAnswer("Id10010b", "not-a-choice")).toThrow(/WHO choice list/);
    expect(session.getSnapshot().data.Id10010b).toBeUndefined();
  });

  it("drops host-only fields from session and normalized submission data", () => {
    const input = { Id10010: "Interviewer", hostRecordId: "host-only-123" };
    const session = createWhoVaSession(whoVa2022Instrument, { initialData: input });
    const result = validateSubmission(whoVa2022Instrument, input);

    expect(session.getSnapshot().data).not.toHaveProperty("hostRecordId");
    expect(result.data).not.toHaveProperty("hostRecordId");

    expect(() => session.replaceData(input)).not.toThrow();
    expect(session.getSnapshot().data).not.toHaveProperty("hostRecordId");
  });

  it("prevents interviewer edits to locked case-entry answers", () => {
    const session = createWhoVaSession(whoVa2022Instrument, {
      initialData: { Id10017: "Case Name", Id10019: "female", hostRecordId: "host-only-123" },
      lockedQuestionNames: ["Id10017", "Id10019", "hostRecordId"]
    });

    expect(session.getSnapshot().lockedQuestionNames).toEqual(["Id10017", "Id10019"]);
    expect(() => session.setAnswer("Id10017", "Edited Name")).toThrow(/cannot be edited/);
    expect(session.getSnapshot().data.Id10017).toBe("Case Name");

    session.setLockedQuestionNames(["Id10019"]);
    session.setAnswer("Id10017", "Respondent Corrected Name");
    expect(session.getSnapshot().data.Id10017).toBe("Respondent Corrected Name");
  });

  it("does not publish a redundant snapshot for the same instrument object", () => {
    const session = createWhoVaSession(whoVa2022Instrument);
    let notifications = 0;
    const unsubscribe = session.subscribe(() => {
      notifications += 1;
    });

    session.setInstrument(whoVa2022Instrument);

    expect(notifications).toBe(0);
    unsubscribe();
  });

  it("allows a temporary constraint-invalid value while the interviewer is typing", () => {
    const session = createWhoVaSession(whoVa2022Instrument);

    expect(() => session.setAnswer("Id10010a", 3)).not.toThrow();
    expect(session.getSnapshot().data.Id10010a).toBe(3);
    expect(session.getSnapshot().issues).toEqual(
      expect.arrayContaining([expect.objectContaining({ question: "Id10010a", code: "constraint" })])
    );

    session.setAnswer("Id10010a", 33);
    expect(session.getSnapshot().issues.some((issue) => issue.question === "Id10010a")).toBe(false);
  });

  it("keeps interview completion after the consented questionnaire sections", () => {
    const sectionNames = new Set(["stillbirth", "injuries_accidents", "consented"]);
    const questionNames = new Set(["Id10104", "nmh", "Id10077", "Id10481", "noteend", "comment"]);
    const instrument = {
      ...whoVa2022Instrument,
      sections: whoVa2022Instrument.sections.filter((section) => sectionNames.has(section.name)),
      questions: whoVa2022Instrument.questions.filter((question) => questionNames.has(question.name))
    };
    instrument.questions.push(
      contextQuestion("Id10013", ["stillbirth"], 1),
      contextQuestion("isNeonatal", ["stillbirth"], 2),
      contextQuestion("Id10114", ["stillbirth"], 3)
    );
    const session = createWhoVaSession(instrument, {
      initialData: { Id10013: "yes", isNeonatal: "1", Id10114: "no" }
    });

    expect(session.getSnapshot().currentSection.name).toBe("stillbirth");
    session.setAnswer("Id10104", "yes");
    expect(session.next().advanced).toBe(true);

    const injuries = session.getSnapshot();
    expect(injuries.currentSection.name).toBe("injuries_accidents");
    expect(injuries.questions.map((question) => question.name)).toEqual(["nmh", "Id10077"]);

    session.setAnswer("Id10077", "no");
    expect(session.next().advanced).toBe(true);
    expect(session.getSnapshot().currentSection).toMatchObject({
      name: "consented",
      label: { en: "Interview completion" }
    });
    expect(session.getSnapshot().questions.map((question) => question.name)).toEqual(["noteend", "comment"]);
  });
});
