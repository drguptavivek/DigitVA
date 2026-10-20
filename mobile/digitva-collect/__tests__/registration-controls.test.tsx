import React from "react";
import { act, create } from "react-test-renderer";
import { StyleSheet, TextInput } from "react-native";

jest.mock("../src/i18n", () => ({ t: (key: string) => key, uiLocale: () => "hi" }));
jest.mock("../src/ui", () => ({ useUiStyles: () => ({ error: {}, input: { minHeight: 44 } }) }));
jest.mock("../src/theme", () => {
  const actual = jest.requireActual("../src/theme");
  return { ...actual, useTheme: () => ({ ...actual.getTheme("light"), colors: { ...actual.getTheme("light").colors } }) };
});

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

  it("draws date of death with the shared DateControl, capped at today, and shows its error", async () => {
    const onChange = jest.fn();
    const { localToday } = require("../src/cases") as typeof import("../src/cases");
    let tree!: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<RegistrationFieldControl field="date_of_death" label="Death date" value="" issueMessage="errFutureDate" onChange={onChange} />);
    });
    expect(tree.root.findAllByProps({ "data-testid": "date-control" })).toHaveLength(0);
    const input = tree.root.findByType("input" as any);
    expect(input.props.type).toBe("date");
    expect(input.props.max).toBe(localToday());
    expect(input.props["aria-invalid"]).toBe(true);
    expect(tree.root.findByProps({ children: "errFutureDate" })).toBeDefined();
    act(() => input.props.onChange({ target: { value: "2026-09-30" } }));
    expect(onChange).toHaveBeenLastCalledWith("2026-09-30");
    await act(async () => tree.unmount());
  });

  it("draws the browser's own control per birth precision and emits the stored format", async () => {
    const mount = async (dateAppearance: "exact" | "month-year" | "year", onChange: jest.Mock) => {
      let tree!: ReturnType<typeof create>;
      await act(async () => {
        tree = create(<RegistrationFieldControl field="date_of_birth_partial" label="Birth" value="" dateAppearance={dateAppearance} onChange={onChange} />);
      });
      return tree;
    };
    const onChange = jest.fn();
    let tree = await mount("exact", onChange);
    expect(tree.root.findAllByProps({ "data-testid": "date-control" })).toHaveLength(0);
    expect(tree.root.findByType("input" as any).props.type).toBe("date");
    expect(tree.root.findAllByType("button" as any)).toHaveLength(1);
    expect(tree.root.findAllByType("svg" as any)).toHaveLength(1);
    act(() => tree.root.findByType("input" as any).props.onChange({ target: { value: "1987-04-12" } }));
    expect(onChange).toHaveBeenLastCalledWith("1987-04-12");
    await act(async () => tree.unmount());

    tree = await mount("month-year", onChange);
    expect(tree.root.findByType("input" as any).props.type).toBe("month");
    expect(() => tree.root.findByType("button" as any).props.onClick()).not.toThrow();
    act(() => tree.root.findByType("input" as any).props.onChange({ target: { value: "1987-04" } }));
    expect(onChange).toHaveBeenLastCalledWith("1987-04");
    await act(async () => tree.unmount());

    tree = await mount("year", onChange);
    const select = tree.root.findByType("select" as any);
    expect(tree.root.findAllByType("input" as any)).toHaveLength(0);
    expect(tree.root.findAllByType("button" as any)).toHaveLength(0);
    const years = tree.root.findAllByType("option" as any).map((option) => option.props.value);
    expect(years[0]).toBe("");
    expect(years[1]).toBe(String(new Date().getFullYear()));
    expect(years[years.length - 1]).toBe(String(new Date().getFullYear() - 120));
    act(() => select.props.onChange({ target: { value: "1987" } }));
    expect(onChange).toHaveBeenLastCalledWith("1987");
    await act(async () => tree.unmount());
  });

  it("draws address and remarks as a plain two-line box that grows to six lines, not the narrative box", async () => {
    const onChange = jest.fn();
    const onIssue = jest.fn();
    let tree!: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<RegistrationFieldControl field="address" label="Address" value="Ward 4" issueMessage="errAddress" onChange={onChange} onIssue={onIssue} />);
    });
    expect(tree.root.findAllByProps({ "data-testid": "text-control" })).toHaveLength(0);
    const input = tree.root.findByType(TextInput);
    expect(input.props.accessibilityLabel).toBe("Address");
    expect(input.props.multiline).toBe(true);
    expect(input.props.value).toBe("Ward 4");
    expect(tree.root.findByProps({ children: "errAddress" })).toBeDefined();
    const height = () => StyleSheet.flatten(tree.root.findByType(TextInput).props.style).height;
    expect(height()).toBe(66);
    act(() => input.props.onContentSizeChange({ nativeEvent: { contentSize: { width: 100, height: 72 } } }));
    expect(height()).toBe(66 + 24);
    act(() => input.props.onContentSizeChange({ nativeEvent: { contentSize: { width: 100, height: 600 } } }));
    expect(height()).toBe(162);
    act(() => input.props.onChangeText("Ward 5"));
    expect(onChange).toHaveBeenLastCalledWith("Ward 5");
    expect(onIssue).toHaveBeenLastCalledWith();
    await act(async () => tree.unmount());
  });
});
