// @vitest-environment jsdom

import React from "react";
import { createRoot } from "react-dom/client";
import { act } from "react-dom/test-utils";
import { afterEach, describe, expect, it } from "vitest";

import vectors from "./national-id-vectors.json";
import {
  createWhoVaSession,
  decodeWhoVaDraft,
  reduceNationalId,
  WHO_VA_FORM_VERSION,
  type InstrumentDefinition
} from "../src/index.js";
import { WhoVaForm } from "../src/web.js";

const instrument: InstrumentDefinition = {
  id: "national-id-test",
  title: "National id test",
  version: "1",
  defaultLanguage: "English (en)",
  sourceFile: "national-id-test.json",
  sections: [{ name: "one", sourceRow: 1, order: 1, label: { en: "One" } }],
  questions: [
    {
      name: "Id10073",
      order: 1,
      sourceRow: 2,
      sourceType: "text",
      dataType: "string" as const,
      control: "text" as const,
      label: { en: "National ID" },
      hint: {},
      guidance: {},
      required: false,
      readOnly: false,
      constraintMessage: {},
      sectionPath: ["one"]
    }
  ]
};

afterEach(() => document.body.replaceChildren());

describe("national ID reduction", () => {
  it.each(vectors)("reduces $input to the server form", ({ input, expected }) => {
    expect(reduceNationalId(input)).toBe(expected);
  });

  it("reduces on setAnswer, initial data and replaceData, and keeps '-' as typed", () => {
    const session = createWhoVaSession(instrument, { initialData: { Id10073: "1234 5678 9012" } });
    expect(session.getSnapshot().data.Id10073).toBe("XXXXXXXXX012");
    session.setAnswer("Id10073", "9999-8888-7777");
    expect(session.getSnapshot().data.Id10073).toBe("XXXXXXXXX777");
    session.setAnswer("Id10073", "-");
    expect(session.getSnapshot().data.Id10073).toBe("-");
    session.replaceData({ Id10073: "123456789012" });
    expect(session.getSnapshot().data.Id10073).toBe("XXXXXXXXX012");
    session.replaceData({ Id10073: "XXXXXXXXX012" });
    expect(session.getSnapshot().data.Id10073).toBe("XXXXXXXXX012");
  });

  it("reduces a draft stored before the reduction existed when it is decoded", () => {
    const draft = decodeWhoVaDraft({
      id: "d1",
      instrumentId: "x",
      instrumentVersion: "1",
      currentSection: "one",
      formVersion: WHO_VA_FORM_VERSION,
      createdAt: "2026-10-21T00:00:00Z",
      updatedAt: "2026-10-21T00:00:00Z",
      data: { Id10073: "123456789012", Id10001: "keep" }
    });
    expect(draft.data).toEqual({ Id10073: "XXXXXXXXX012", Id10001: "keep" });
  });

  it("lets the field be typed whole and commits only the reduced value on blur", async () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    const seen: unknown[] = [];
    await act(async () => {
      root.render(<WhoVaForm instrument={instrument} onChange={(data) => seen.push(data.Id10073)} />);
    });
    const input = container.querySelector<HTMLInputElement>('[data-testid="question-Id10073"]')!;
    const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    const type = async (text: string) => {
      await act(async () => {
        setValue.call(input, text);
        input.dispatchEvent(new Event("input", { bubbles: true }));
      });
    };
    await type("1");
    await type("1234 5678 9012");
    expect(input.value).toBe("1234 5678 9012");
    expect(seen.filter((value) => value !== undefined)).toEqual([]);
    await act(async () => {
      input.dispatchEvent(new FocusEvent("focusout", { bubbles: true }));
      input.blur();
    });
    expect(input.value).toBe("XXXXXXXXX012");
    expect(seen.at(-1)).toBe("XXXXXXXXX012");
    expect(JSON.stringify(seen)).not.toContain("123456789012");
  });

  it("commits the reduced value when Next is tapped with the field still focused (no blur)", async () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    const seen: unknown[] = [];
    const completed: unknown[] = [];
    await act(async () => {
      root.render(
        <WhoVaForm
          instrument={instrument}
          onChange={(data) => seen.push(data.Id10073)}
          onComplete={(result) => completed.push(result.data.Id10073)}
        />
      );
    });
    const input = container.querySelector<HTMLInputElement>('[data-testid="question-Id10073"]')!;
    const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    await act(async () => {
      input.focus();
      setValue.call(input, "1234 5678 9012");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(seen.filter((value) => value !== undefined)).toEqual([]);
    const next = Array.from(container.querySelectorAll('[role="button"]')).find(
      (candidate) => ["Next", "Complete"].includes(candidate.textContent ?? "")
    ) as HTMLElement;
    await act(async () => {
      next.click();
    });
    expect(completed).toEqual(["XXXXXXXXX012"]);
    expect(JSON.stringify([seen, completed])).not.toContain("123456789012");
  });
});
