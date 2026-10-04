import React from "react";
import { act, create } from "react-test-renderer";

jest.mock("../src/i18n", () => ({ t: (key: string) => key, uiLocale: () => "hi" }));
jest.mock("../src/ui", () => ({ useUiStyles: () => ({ error: {}, input: {} }) }));
jest.mock("../src/theme", () => ({
  useTheme: () => ({ colors: { accent: "#00f", accentPressed: "#00f", accentSoft: "#00f", background: "#fff", surface: "#fff", text: "#000", textMuted: "#333", border: "#ccc", warning: "#a60", danger: "#d00", dangerSoft: "#fee" } })
}));

jest.mock(
  "@drguptavivek/who-2022-va/web",
  () => {
    const React = require("react") as typeof import("react");
    return {
    WhoVaQuestionControls: {
      Date: (props: Record<string, unknown>) => React.createElement("button", { "data-testid": "date-control", ...props }),
      Integer: (props: Record<string, unknown>) => React.createElement("button", { "data-testid": "integer-control", ...props }),
      Text: (props: Record<string, unknown>) => React.createElement("button", { "data-testid": "text-control", ...props })
    }
    };
  },
  { virtual: true }
);
jest.mock(
  "@drguptavivek/who-2022-va",
  () => ({
    resolveUiMessages: (locale: string) => ({ locale, dateFormatHint: "दिन-माह-वर्ष" }),
    WHO_VA_BUILT_IN_UI_TRANSLATIONS: { hi: { dateFormatHint: "दिन-माह-वर्ष" } }
  }),
  { virtual: true }
);

import { RegistrationFieldControl, registrationFieldKind } from "../src/web/registrationControls";

describe("death registration field controls", () => {
  it("maps registration data types to the corresponding WHO form control", () => {
    expect(registrationFieldKind("deceased_name")).toBe("text");
    expect(registrationFieldKind("date_of_death")).toBe("date");
    expect(registrationFieldKind("date_of_birth")).toBe("date");
    expect(registrationFieldKind("date_of_birth_partial")).toBe("date");
    expect(registrationFieldKind("age_years")).toBe("integer");
    expect(registrationFieldKind("informant_phone")).toBe("phone");
    expect(registrationFieldKind("informant_phone_2")).toBe("phone");
    expect(registrationFieldKind("address")).toBe("multiline");
    expect(registrationFieldKind("remarks")).toBe("multiline");
  });

  it("keeps out-of-range age visible and reports an issue until corrected", async () => {
    const onChange = jest.fn();
    const onIssue = jest.fn();
    let tree!: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<RegistrationFieldControl field="age_years" label="Age" value="" onChange={onChange} onIssue={onIssue} />);
    });
    const control = tree.root.findByProps({ "data-testid": "integer-control" });
    expect(control.props.question.required).toBe(false);
    act(() => control.props.onAnswer(-1));
    expect(onChange).toHaveBeenCalledWith("-1");
    expect(onIssue).toHaveBeenCalledWith("errAge");
    act(() => control.props.onAnswer(0));
    expect(onChange).toHaveBeenLastCalledWith("0");
    expect(onIssue).toHaveBeenLastCalledWith();
    act(() => control.props.onAnswer(42));
    expect(onChange).toHaveBeenLastCalledWith("42");
    expect(onIssue).toHaveBeenLastCalledWith();
    act(() => control.props.onAnswer(125));
    expect(onChange).toHaveBeenLastCalledWith("125");
    expect(onIssue).toHaveBeenLastCalledWith();
    act(() => control.props.onAnswer(126));
    expect(onChange).toHaveBeenLastCalledWith("126");
    expect(onIssue).toHaveBeenLastCalledWith("errAge");
    await act(async () => tree!.unmount());
  });

  it("marks deceased name and death date as required WHO questions", async () => {
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<RegistrationFieldControl field="date_of_death" label="Death date" value="" onChange={jest.fn()} />);
    });
    expect(tree!.root.findByProps({ "data-testid": "date-control" }).props.question.required).toBe(true);
    await act(async () => tree!.unmount());
  });

  it("converts WHO sentinel dates to partial registration values", async () => {
    const onChange = jest.fn();
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(
        <RegistrationFieldControl
          field="date_of_birth_partial"
          label="Birth date"
          value=""
          dateAppearance="month-year"
          onChange={onChange}
        />
      );
    });
    const control = tree!.root.findByProps({ "data-testid": "date-control" });
    expect(control.props.question.appearance).toBe("month-year");
    expect(control.props.locale).toBe("hi");
    expect(control.props.messages.dateFormatHint).toContain("दिन");
    act(() => control.props.onAnswer("1987-04-01"));
    expect(onChange).toHaveBeenCalledWith("1987-04");
    await act(async () => tree!.unmount());

    const yearChange = jest.fn();
    await act(async () => {
      tree = create(
        <RegistrationFieldControl
          field="date_of_birth_partial"
          label="Birth year"
          value=""
          dateAppearance="year"
          onChange={yearChange}
        />
      );
    });
    const yearControl = tree!.root.findByProps({ "data-testid": "date-control" });
    act(() => yearControl.props.onAnswer("1987-01-01"));
    expect(yearChange).toHaveBeenCalledWith("1987");
    await act(async () => tree!.unmount());
  });
});
