import { describe, expect, it } from "vitest";

import {
  createWhoVaSession,
  isQuestionRelevant,
  whoVa2022Instrument,
  type AnswerValue,
  type InstrumentQuestion,
  type WhoVaSession
} from "../src/index.js";

const INTERVIEW_DATE = "2026-07-17";
const NOW = new Date(`${INTERVIEW_DATE}T10:30:00.000Z`);

interface AgePath {
  label: string;
  born: string;
  ageInDays: number;
  classification: "isNeonatal" | "isChild" | "isAdult";
  ageDisplay: "displayAgeNeonate" | "displayAgeChild" | "displayAgeAdult";
  visibleFields: string[];
  hiddenFields: string[];
  branchAnswers?: Record<string, AnswerValue>;
  firstAgeSpecificScreen: "stillbirth" | "med_hist_final_illness";
}

const agePaths: AgePath[] = [
  {
    label: "27-day neonate",
    born: "2026-06-20",
    ageInDays: 27,
    classification: "isNeonatal",
    ageDisplay: "displayAgeNeonate",
    visibleFields: ["Id10061", "Id10062"],
    hiddenFields: ["Id10059", "Id10063", "Id10065"],
    firstAgeSpecificScreen: "stillbirth"
  },
  {
    label: "28-day child",
    born: "2026-06-19",
    ageInDays: 28,
    classification: "isChild",
    ageDisplay: "displayAgeChild",
    visibleFields: ["Id10061", "Id10062"],
    hiddenFields: ["Id10059", "Id10063", "Id10065"],
    firstAgeSpecificScreen: "med_hist_final_illness"
  },
  {
    label: "4-year-old child",
    born: "2022-07-17",
    ageInDays: 1461,
    classification: "isChild",
    ageDisplay: "displayAgeChild",
    visibleFields: ["Id10061", "Id10062", "Id10063"],
    hiddenFields: ["Id10059", "Id10065"],
    firstAgeSpecificScreen: "med_hist_final_illness"
  },
  {
    label: "8-year-old child",
    born: "2018-07-17",
    ageInDays: 2922,
    classification: "isChild",
    ageDisplay: "displayAgeChild",
    visibleFields: ["Id10061", "Id10062", "Id10063", "Id10065"],
    hiddenFields: ["Id10059"],
    firstAgeSpecificScreen: "med_hist_final_illness"
  },
  {
    label: "10-year-old child",
    born: "2016-07-16",
    ageInDays: 3653,
    classification: "isChild",
    ageDisplay: "displayAgeChild",
    visibleFields: ["Id10061", "Id10062", "Id10063", "Id10065", "Id10099"],
    hiddenFields: ["Id10059"],
    branchAnswers: { Id10077: "yes", Id10098: "no" },
    firstAgeSpecificScreen: "med_hist_final_illness"
  },
  {
    label: "12-year-old adult",
    born: "2014-07-16",
    ageInDays: 4384,
    classification: "isAdult",
    ageDisplay: "displayAgeAdult",
    visibleFields: ["Id10059", "Id10063", "Id10065"],
    hiddenFields: ["Id10061", "Id10062"],
    firstAgeSpecificScreen: "med_hist_final_illness"
  },
  {
    label: "40-year-old adult woman",
    born: "1986-07-16",
    ageInDays: 14611,
    classification: "isAdult",
    ageDisplay: "displayAgeAdult",
    visibleFields: ["Id10059", "Id10063", "Id10065", "Id10299"],
    hiddenFields: ["Id10061", "Id10062"],
    branchAnswers: { Id10296: "yes" },
    firstAgeSpecificScreen: "med_hist_final_illness"
  },
  {
    label: "50-year-old adult woman",
    born: "1976-07-16",
    ageInDays: 18263,
    classification: "isAdult",
    ageDisplay: "displayAgeAdult",
    visibleFields: ["Id10059", "Id10063", "Id10065", "Id10299"],
    hiddenFields: ["Id10061", "Id10062", "Id10305", "Id10313"],
    branchAnswers: { Id10296: "yes", Id10299: "yes" },
    firstAgeSpecificScreen: "med_hist_final_illness"
  }
];

function question(name: string): InstrumentQuestion {
  const item = whoVa2022Instrument.questions.find((candidate) => candidate.name === name);
  if (!item) throw new Error(`Unknown test question ${name}`);
  return item;
}

function representativeAnswer(item: InstrumentQuestion): AnswerValue | undefined {
  const firstChoice = item.choices?.[0];
  if (firstChoice) return item.dataType === "string[]" ? [firstChoice.value] : firstChoice.value;
  switch (item.dataType) {
    case "string":
      return "E2E answer";
    case "number":
      return 30;
    case "boolean":
      return true;
    case "date":
      return INTERVIEW_DATE;
    case "dateTime":
      return NOW.toISOString();
    case "attachment":
      return { uri: "attachment://age-path-e2e" };
    case "audit":
      return { startedAt: NOW.toISOString() };
    case "string[]":
      return ["E2E answer"];
    case "calculated":
    case "none":
      return undefined;
  }
}

function answerVisibleQuestions(session: WhoVaSession, overrides: Record<string, AnswerValue> = {}): void {
  for (let pass = 0; pass < whoVa2022Instrument.questions.length; pass += 1) {
    const snapshot = session.getSnapshot();
    const unanswered = snapshot.questions.filter(
      (item) => !["note", "calculated", "system"].includes(item.control) && snapshot.data[item.name] == null
    );
    if (!unanswered.length) return;
    for (const item of unanswered) {
      const value = overrides[item.name] ?? representativeAnswer(item);
      if (value !== undefined) session.setAnswer(item.name, value);
    }
  }
  throw new Error(`Could not settle conditional fields on ${session.getSnapshot().currentSection.name}`);
}

function advance(session: WhoVaSession): void {
  const from = session.getSnapshot().currentSection.name;
  const result = session.next();
  expect(result.issues, `Could not leave ${from}`).toEqual([]);
  expect(result.advanced, `Did not advance from ${from}`).toBe(true);
}

function reachDeceasedScreen(session: WhoVaSession): void {
  answerVisibleQuestions(session);
  advance(session);
  answerVisibleQuestions(session);
  advance(session);
  answerVisibleQuestions(session, { Id10013: "yes" });
  advance(session);
  expect(session.getSnapshot().currentSection.name).toBe("info_on_deceased");
}

function finishDeceasedScreen(session: WhoVaSession, born: string): void {
  // Answer the date-availability filters first, as an interviewer would. This
  // prevents the fallback age-group controls from being populated before the
  // known DOB/death-date path makes them irrelevant.
  session.setAnswer("Id10019", "female");
  session.setAnswer("Id10020", "yes");
  session.setAnswer("Id10021", born);
  session.setAnswer("Id10022", "yes");
  session.setAnswer("Id10023_a", INTERVIEW_DATE);
  session.setAnswer("Id10051", "yes");
  answerVisibleQuestions(session);
}

describe("age-wise WHO VA screen paths from Id10021", () => {
  it.each(agePaths)("$label derives the age path and exposes the expected fields and screens", (path) => {
    const session = createWhoVaSession(whoVa2022Instrument, { now: () => NOW });
    reachDeceasedScreen(session);
    finishDeceasedScreen(session, path.born);

    const deceased = session.getSnapshot();
    expect(deceased.data.Id10021).toBe(path.born);
    expect(deceased.data.ageInDays).toBe(path.ageInDays);
    expect(deceased.data[path.classification]).toBe("1");
    expect(deceased.questions.map((item) => item.name)).toContain(path.ageDisplay);

    const relevanceData = { ...deceased.data, ...path.branchAnswers };

    for (const name of path.visibleFields) {
      expect(
        isQuestionRelevant(whoVa2022Instrument, question(name), relevanceData),
        `${name} should be visible`
      ).toBe(true);
    }
    for (const name of path.hiddenFields) {
      expect(
        isQuestionRelevant(whoVa2022Instrument, question(name), relevanceData),
        `${name} should be hidden`
      ).toBe(false);
    }

    advance(session);
    expect(session.getSnapshot().currentSection.name).toBe("narrat");
    answerVisibleQuestions(session);
    advance(session);
    expect(session.getSnapshot().currentSection.name).toBe(path.firstAgeSpecificScreen);
  });
});
