// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createWhoVaSession } from "../src/engine/session.js";
import { createWhoVa2022Instrument } from "../src/instrument.js";
import type { InstrumentDefinition, InstrumentQuestion, WhoVaSession } from "../src/index.js";
import { WhoVaForm } from "../src/web.js";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let root: Root | undefined;
afterEach(async () => {
  await act(async () => root?.unmount());
  root = undefined;
  document.body.innerHTML = "";
  // The web form restores its position from history state; keep tests apart.
  window.history.replaceState(null, "");
});

async function mount(element: React.ReactElement) {
  const container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => {
    root!.render(element);
  });
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  return container;
}

const click = async (node: Element | null | undefined) => {
  await act(async () => {
    (node as HTMLElement | null | undefined)?.click();
  });
};
const byId = (id: string) => document.querySelector<HTMLElement>(`[data-testid="${id}"]`);

describe("age assists in the form", () => {
  const instrument = createWhoVa2022Instrument(["digitva_core", "doris_support_whova_2022"]);
  const years = {
    Id10013: "yes",
    Id10020: "no",
    dob_precision: "year",
    dob_year: "2017-01-01",
    Id10022: "no",
    Id10024: "2021-01-01"
  };
  const open = (data: Record<string, string | number>) => {
    const session = createWhoVaSession(instrument, { initialData: data, initialSection: "info_on_deceased" });
    return { session, element: <WhoVaForm instrument={instrument} session={session} /> };
  };

  it("pre-selects the group and the years from the dates and says so", async () => {
    const { session, element } = open(years);
    await mount(element);
    expect(session.getSnapshot().data).toMatchObject({
      age_group: "child",
      age_child_unit: "years",
      age_child_years: 4
    });
    expect(byId("assist-hint-age_group")?.textContent).toBe("Suggested from the dates");
    expect(byId("assist-hint-age_child_years")?.textContent).toBe("Estimate from the years");
  });

  const monthBirth = {
    Id10013: "yes",
    Id10020: "no",
    dob_precision: "month_year",
    dob_month_year: "2022-06-01",
    Id10022: "yes",
    Id10023_b: "2026-10-06"
  };

  it("estimates the age for a month of birth and says it comes from the dates", async () => {
    const { session, element } = open(monthBirth);
    await mount(element);
    expect(session.getSnapshot().data).toMatchObject({ age_group: "child", age_child_unit: "years", age_child_years: 4 });
    expect(byId("assist-hint-age_child_years")?.textContent).toBe("Estimated from the dates");
  });

  it("keeps an age the interviewer typed over the month-based estimate", async () => {
    const { session, element } = open({ ...monthBirth, age_group: "child", age_child_unit: "years", age_child_years: 7 });
    await mount(element);
    expect(session.getSnapshot().data.age_child_years).toBe(7);
    expect(byId("assist-confirm-age_child_years")?.textContent).toContain("The dates suggest 4 years. Keep 7?");
  });

  it("shows the range, and fills no number, when the dates span two ages", async () => {
    const { session, element } = open({ ...monthBirth, dob_month_year: "2026-09-01", Id10023_b: "2026-10-28" });
    await mount(element);
    expect(session.getSnapshot().data.age_group).toBe("child");
    expect(session.getSnapshot().data.age_child_days).toBeUndefined();
    await click(byId("question-age_child_unit-choice-days"));
    expect(byId("assist-hint-age_child_days")?.textContent).toBe("The dates suggest about 28 days to 1 month");
  });

  it("asks before keeping a group the dates contradict, and Keep is remembered", async () => {
    const { session, element } = open(years);
    await mount(element);
    await click(byId("question-age_group-choice-adult"));
    expect(byId("assist-confirm-age_group")?.textContent).toContain("The dates suggest Child (about 4 years). Keep Adult?");
    await click(byId("assist-keep-age_group"));
    expect(byId("assist-confirm-age_group")).toBeNull();
    expect(session.getSnapshot().data.age_group).toBe("adult");
  });

  it("Use suggestion restores the derived group", async () => {
    const { session, element } = open(years);
    await mount(element);
    await click(byId("question-age_group-choice-adult"));
    await click(byId("assist-use-age_group"));
    expect(session.getSnapshot().data.age_group).toBe("child");
    expect(byId("assist-confirm-age_group")).toBeNull();
  });

  it("re-checks when a date changes later and never overrides a chosen group", async () => {
    const { session, element } = open(years);
    await mount(element);
    await click(byId("question-age_group-choice-child"));
    await act(async () => session.setAnswer("Id10024", "2040-01-01"));
    expect(session.getSnapshot().data.age_group).toBe("child");
    expect(byId("assist-confirm-age_group")?.textContent).toContain("Adult");
  });

  it("offers a one-tap fix next to the WHO message for child days under 28", async () => {
    const { session, element } = open({ Id10013: "yes", Id10020: "no", Id10022: "no" });
    await mount(element);
    await click(byId("question-age_group-choice-child"));
    await click(byId("question-age_child_unit-choice-days"));
    await act(async () => session.setAnswer("age_child_days", 25));
    expect(byId("assist-fix-age_child_days")?.textContent).toContain("25 days is a neonate’s age");
    await click(byId("assist-fix-action-age_child_days"));
    expect(session.getSnapshot().data).toMatchObject({ age_group: "neonate", age_neonate_days: 25 });
    expect(session.getSnapshot().data.age_child_days).toBeUndefined();
  });

  it("offers months for child days over 60", async () => {
    const { session, element } = open({ Id10013: "yes", Id10020: "no", Id10022: "no" });
    await mount(element);
    await click(byId("question-age_group-choice-child"));
    await click(byId("question-age_child_unit-choice-days"));
    await act(async () => session.setAnswer("age_child_days", 90));
    await click(byId("assist-fix-action-age_child_days"));
    expect(session.getSnapshot().data).toMatchObject({ age_child_unit: "months", age_child_months: 3 });
  });
});

describe("narration language from the narrative", () => {
  const instrument = createWhoVa2022Instrument(["digitva_core", "narration_language"]);
  const open = () => {
    const session = createWhoVaSession(instrument, { initialData: { Id10013: "yes" }, initialSection: "narrat" });
    return { session, element: <WhoVaForm instrument={instrument} session={session} locale="en" /> };
  };

  it("starts from the app language, follows the script, and stops after a manual choice", async () => {
    const { session, element } = open();
    await mount(element);
    expect(session.getSnapshot().data.narr_language).toBe("english");

    await act(async () => session.setAnswer("Id10476", "उसे बुखार था"));
    expect(session.getSnapshot().data.narr_language).toBe("hindi");

    await act(async () => session.setAnswer("Id10476", "He had fever"));
    expect(session.getSnapshot().data.narr_language).toBe("english");

    await click(byId("question-narr_language-choice-hindi"));
    await act(async () => session.setAnswer("Id10476", "He had a long fever"));
    expect(session.getSnapshot().data.narr_language).toBe("hindi");
  });

  it("shows the voice typing tip under the narrative", async () => {
    const { element } = open();
    await mount(element);
    expect(byId("narrative-voice-tip")?.textContent).toBe(
      "Tip: tap the microphone on your keyboard to dictate (Hindi or English)."
    );
  });
});

const question = (name: string, order: number, section: string, extra: Partial<InstrumentQuestion> = {}): InstrumentQuestion => ({
  name,
  order,
  sourceRow: order + 1,
  sourceType: "text",
  dataType: "string",
  control: "text",
  label: { en: `Question ${name}` },
  hint: {},
  guidance: {},
  required: true,
  readOnly: false,
  constraintMessage: {},
  sectionPath: [section],
  ...extra
});
const problemsInstrument: InstrumentDefinition = {
  id: "problems-test",
  title: "Problems",
  version: "1",
  defaultLanguage: "English (en)",
  sourceFile: "test",
  sections: [
    { name: "one", sourceRow: 1, order: 1, label: { en: "Part one" } },
    { name: "two", sourceRow: 2, order: 2, label: { en: "Part two" } }
  ],
  questions: [
    question("q_flag", 1, "one", {
      sourceType: "select_one yn",
      control: "singleChoice",
      listName: "yn",
      choices: [
        { value: "yes", sourceRow: 3, label: { en: "Yes" } },
        { value: "no", sourceRow: 4, label: { en: "No" } }
      ]
    }),
    question("q_a", 2, "one"),
    question("q_b", 3, "two"),
    question("q_hidden", 4, "two", { relevant: { source: "selected(${q_flag}, 'yes')" } })
  ]
};

describe("problems list", () => {
  type Extra = {
    serverProblems?: Array<{ question?: string; message: string }>;
    onProblemsChange?: (count: number) => void;
    onDraftController?: (controller: never) => void;
  };
  const open = (props: Extra = {}) => {
    const session: WhoVaSession = createWhoVaSession(problemsInstrument, {
      initialData: { q_flag: "no" },
      initialSection: "two"
    });
    return { session, element: <WhoVaForm instrument={problemsInstrument} session={session} {...(props as object)} /> };
  };

  it("opens on Complete with errors, lists every problem with section and question, and Go opens the question", async () => {
    const { session, element } = open();
    await mount(element);
    await click(Array.from(document.querySelectorAll<HTMLElement>('[role="button"]')).find((b) => b.textContent === "Complete"));
    expect(byId("problems-dialog")).not.toBeNull();
    expect(byId("problem-q_a")?.textContent).toContain("Part one › Question q_a");
    expect(byId("problem-q_b")?.textContent).toContain("Part two › Question q_b");
    expect(byId("problem-q_b")?.textContent).toContain("This question is required.");
    expect(byId("problem-q_hidden")).toBeNull();

    await click(byId("problem-go-q_a"));
    expect(byId("problems-dialog")).toBeNull();
    expect(session.getSnapshot().currentSection.name).toBe("one");
    await vi.waitFor(() => expect(document.activeElement).toBe(byId("question-q_a")));
    expect(byId("question-card-q_a")).not.toBeNull();
  });

  it("includes server problems, reports the count and explains a question hidden by skip logic", async () => {
    const counts: number[] = [];
    const { session, element } = open({
      serverProblems: [
        { question: "q_hidden", message: "The server needs this answered." },
        { message: "The interview was refused." }
      ],
      onProblemsChange: (count) => counts.push(count)
    });
    await mount(element);
    expect(counts.at(-1)).toBe(2);
    expect(session.getSnapshot().currentSection.name).toBe("two");
  });

  it("goToQuestion on a hidden question lands on its controller and says why", async () => {
    let controller: { goToQuestion(name: string): unknown; showProblems(): void } | undefined;
    const { session, element } = open({ onDraftController: (next) => (controller = next as never) });
    await mount(element);
    await act(async () => {
      controller?.goToQuestion("q_hidden");
    });
    expect(session.getSnapshot().currentSection.name).toBe("one");
    expect(byId("focus-notice")?.textContent).toContain("Question q_flag");
  });

  it("showProblems lists the host's server problems and drops one when its answer changes", async () => {
    let controller: { showProblems(): void } | undefined;
    const { session, element } = open({
      serverProblems: [{ question: "q_b", message: "Refused by the server." }],
      onDraftController: (next) => (controller = next as never)
    });
    await mount(element);
    await act(async () => controller?.showProblems());
    const rows = () => Array.from(document.querySelectorAll('[data-testid="problem-q_b"]')).map((row) => row.textContent);
    expect(rows().join("|")).toContain("Refused by the server.");
    await act(async () => session.setAnswer("q_b", "fixed"));
    expect(rows()).toEqual([]);
  });
});
