import React from "react";
import { useState } from "react";
import { act, create } from "react-test-renderer";

jest.mock("expo-router", () => ({ Redirect: () => null, useLocalSearchParams: () => ({}), useRouter: () => ({}) }));
jest.mock("../src/AppState", () => ({ useAppState: () => ({ accounts: [] }) }));
jest.mock("../src/ui", () => ({ Button: () => null, Row: () => null, Screen: () => null, useUiStyles: () => ({}) }));
jest.mock("../src/interviewerDb", () => ({ isUnlocked: () => true, openInterviewerDb: jest.fn() }));
jest.mock("../src/platform", () => ({ platformServices: {} }));
jest.mock("../src/sync", () => ({
  getCachedReferenceData: jest.fn(async () => undefined),
  registersDeaths: () => true,
  targetsFrom: () => []
}));
jest.mock("../src/i18n", () => ({ t: (key: string) => key, uiLocale: () => "hi" }));
jest.mock("@drguptavivek/who-2022-va/native", () => {
  const React = require("react") as typeof import("react");
  return {
    WhoVaQuestionControls: {
      Date: ({ onDraftIssue, question }: { onDraftIssue?: (name: string, issue?: unknown) => void; question: { name: string } }) => {
        React.useEffect(() => () => onDraftIssue?.(question.name), [onDraftIssue, question.name]);
        return null;
      },
      Integer: () => null,
      Text: () => null
    }
  };
}, { virtual: true });
jest.mock("@drguptavivek/who-2022-va", () => ({
  resolveUiMessages: (locale: string, translations: unknown) => ({ locale, translations }),
  WHO_VA_BUILT_IN_UI_TRANSLATIONS: { hi: { dateFormatHint: "हिंदी" } }
}), { virtual: true });

import { NativeRegistrationFieldControl, requiredBirthField } from "../src/nativeRoutes/register";
import type { RegistrationFields } from "../src/cases";

const base: RegistrationFields = { deceased_name: "Asha", deceased_sex: "female", date_of_death: "2026-09-30" };

describe("native death registration controls", () => {
  afterEach(() => jest.clearAllMocks());

  it("requires a value for every selected precision and defaults missing DOB to exact", () => {
    expect(requiredBirthField("exact", base)).toBe("date_of_birth");
    expect(requiredBirthField("month-year", base)).toBe("date_of_birth_partial");
    expect(requiredBirthField("year", base)).toBe("date_of_birth_partial");
    expect(requiredBirthField("exact", { ...base, date_of_birth: "1987-04-12" })).toBeUndefined();
    expect(requiredBirthField("month-year", { ...base, date_of_birth_partial: "1987-04" })).toBeUndefined();
    expect(requiredBirthField("year", { ...base, date_of_birth_partial: "1987" })).toBeUndefined();
  });

  it("passes the active Hindi locale and WHO Hindi UI messages to native controls", () => {
    let tree: ReturnType<typeof create>;
    act(() => {
      tree = create(
        <NativeRegistrationFieldControl
          field="date_of_birth_partial"
          label="जन्म तिथि"
          value=""
          appearance="month-year"
          onChange={jest.fn()}
        />
      );
    });
    const nativeControls = require("@drguptavivek/who-2022-va/native").WhoVaQuestionControls as { Date: React.ComponentType<Record<string, unknown>> };
    const control = tree!.root.findByType(nativeControls.Date);
    expect(control.props.locale).toBe("hi");
    expect(control.props.messages).toMatchObject({ locale: "hi", translations: { hi: { dateFormatHint: "हिंदी" } } });
    act(() => tree!.unmount());
  });

  it.each([
    ["year", "2000", "2000-01-01", "2001-01-01", "2001"],
    ["month-year", "2000-04", "2000-04-01", "2001-05-01", "2001-05"]
  ] as const)("keeps %s precision while passing canonical dates to WHO controls", (appearance, stored, canonical, selected, expected) => {
    const onChange = jest.fn();
    let tree: ReturnType<typeof create>;
    act(() => {
      tree = create(<NativeRegistrationFieldControl field="date_of_birth_partial" label="DOB" value={stored} appearance={appearance} onChange={onChange} />);
    });
    const nativeControls = require("@drguptavivek/who-2022-va/native").WhoVaQuestionControls;
    const control = tree!.root.findByType(nativeControls.Date);
    expect(control.props.value).toBe(canonical);
    act(() => control.props.onAnswer(selected));
    expect(onChange).toHaveBeenCalledWith(expected);
    act(() => tree!.unmount());
  });

  it("keeps an invalid date issue through unrelated input updates and clears it on unmount", () => {
    const reportedIssues: Array<string | undefined> = [];
    let selectedDate = "";
    function RegistrationHarness() {
      const [errors, setErrors] = useState<{ date_of_birth?: string; deceased_name?: string }>({});
      const [name, setName] = useState("");
      const [date, setDate] = useState("");
      selectedDate = date;
      return (
        <>
          <NativeRegistrationFieldControl
            field="date_of_birth"
            label="जन्म तिथि"
            value={date}
            issue={errors.date_of_birth as "errDate" | undefined}
            onChange={setDate}
            onIssue={(issue) => {
              reportedIssues.push(issue);
              setErrors((current) => current.date_of_birth === issue ? current : { ...current, date_of_birth: issue });
            }}
          />
          <input
            value={name}
            onChange={(event: { target: { value: string } }) => {
              setName(event.target.value);
              setErrors((current) => current.deceased_name === undefined ? current : { ...current, deceased_name: undefined });
            }}
          />
        </>
      );
    }

    let tree: ReturnType<typeof create>;
    act(() => {
      tree = create(<RegistrationHarness />);
    });
    const nativeControls = require("@drguptavivek/who-2022-va/native").WhoVaQuestionControls as { Date: React.ComponentType<Record<string, unknown>> };
    const dateControl = tree!.root.findByType(nativeControls.Date);
    act(() => {
      (dateControl.props.onDraftIssue as (name: string, issue?: unknown) => void)("date_of_birth", {
        question: "date_of_birth",
        code: "constraint",
        message: "invalid date"
      });
    });
    expect(dateControl.props.onDraftIssue).toBeDefined();
    expect(reportedIssues).toEqual(["errDate"]);

    act(() => {
      tree!.root.findByType("input").props.onChange({ target: { value: "Asha" } });
    });
    expect(reportedIssues).toEqual(["errDate"]);

    act(() => {
      (dateControl.props.onAnswer as (value: string) => void)("1987-04-12");
    });
    expect(selectedDate).toBe("1987-04-12");
    expect(reportedIssues).toEqual(["errDate", undefined]);

    act(() => tree!.unmount());
    expect(reportedIssues).toEqual(["errDate", undefined, undefined]);
  });
});
