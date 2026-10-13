import React from "react";
import { act, create } from "react-test-renderer";

jest.mock("../src/theme", () => {
  const actual = jest.requireActual("../src/theme");
  return { ...actual, useTheme: () => actual.getTheme("light") };
});

import { DateField as WebDateField } from "../src/workspace/doris/DateField.web";
import { isFullIso, isoFromLocal, localDate, todayIso } from "../src/workspace/doris/dateFieldShared";

describe("todayIso", () => {
  // 2026-10-12 20:00 UTC is already the 13th in Kolkata and still the 12th in Los Angeles.
  const instant = new Date("2026-10-12T20:00:00Z");
  it("follows the user's timezone, not UTC", () => {
    expect(todayIso(instant, "Asia/Kolkata")).toBe("2026-10-13");
    expect(todayIso(instant, "America/Los_Angeles")).toBe("2026-10-12");
    expect(todayIso(instant, "UTC")).toBe("2026-10-12");
  });
  it("round-trips a local day without shifting it", () => {
    expect(isoFromLocal(localDate("2026-03-01"))).toBe("2026-03-01");
    expect(isFullIso("2026-02-30")).toBe(false);
    expect(isFullIso("1997-07")).toBe(false);
  });
});

const NOW = new Date("2026-10-12T20:00:00Z");
const ZONE = "Asia/Kolkata";

/** Controlled host so a precision switch that rewrites the value is visible to the field, as in the panel. */
function Host({ initial, label, precision, spy }: { initial: string; label: string; precision?: boolean; spy: (value: string) => void }) {
  const [value, setValue] = React.useState(initial);
  return <WebDateField label={label} value={value} precision={precision} now={NOW} timeZone={ZONE} onChange={(next) => { spy(next); setValue(next); }} />;
}

describe("DateField.web", () => {
  const mount = (props: { initial?: string; label?: string; precision?: boolean } = {}) => {
    const onChange = jest.fn();
    let tree!: ReturnType<typeof create>;
    act(() => { tree = create(<Host initial={props.initial ?? ""} label={props.label ?? "Date of death"} precision={props.precision} spy={onChange} />); });
    return { tree, onChange };
  };
  const precisionButton = (tree: ReturnType<typeof create>, label: string) => tree.root.findByProps({ accessibilityLabel: `${label} precision` });
  const choosePrecision = (tree: ReturnType<typeof create>, label: string, name: string) => {
    act(() => precisionButton(tree, label).props.onPress());
    act(() => tree.root.findByProps({ accessibilityLabel: `${label} precision: ${name}` }).props.onPress());
  };
  const input = (tree: ReturnType<typeof create>) => tree.root.findByType("input" as any);

  it("a plain date is a real date input with no max, with no precision dropdown", () => {
    const { tree, onChange } = mount();
    expect(input(tree).props.type).toBe("date");
    expect(input(tree).props.max).toBeUndefined();
    expect(tree.root.findAllByProps({ accessibilityLabel: "Date of death precision" })).toHaveLength(0);
    expect(JSON.stringify(tree.toJSON())).not.toContain("Year or month only");
    act(() => input(tree).props.onChange({ target: { value: "2026-10-01" } }));
    expect(onChange).toHaveBeenCalledWith("2026-10-01");
  });

  it("a stored partial plain date is kept in a text field and only a full date replaces it", () => {
    const { tree, onChange } = mount({ initial: "1997-07" });
    expect(tree.root.findAllByType("input" as any)).toHaveLength(0);
    const text = () => tree.root.findByProps({ accessibilityLabel: "Date of death", placeholder: "YYYY-MM-DD" });
    expect(text().props.value).toBe("1997-07");
    act(() => text().props.onChangeText("1998"));
    expect(onChange).not.toHaveBeenCalled();
    act(() => text().props.onChangeText("1998-02-30"));
    expect(onChange).not.toHaveBeenCalled();
    act(() => text().props.onChangeText("1998-02-03"));
    expect(onChange).toHaveBeenCalledWith("1998-02-03");
  });

  it("the precision dropdown starts at Date and shows the three choices", () => {
    const { tree } = mount({ label: "Date of birth", precision: true });
    expect(precisionButton(tree, "Date of birth").props.accessibilityValue).toEqual({ text: "Date" });
    expect(input(tree).props.type).toBe("date");
    act(() => precisionButton(tree, "Date of birth").props.onPress());
    for (const name of ["Date", "Year-Month", "Year"]) expect(tree.root.findAllByProps({ accessibilityLabel: `Date of birth precision: ${name}` }).length).toBeGreaterThan(0);
  });

  it("narrows a full date to a month and a year, and clears when the value is too coarse for the finer field", () => {
    const { tree, onChange } = mount({ initial: "1997-07-04", label: "Date of birth", precision: true });
    choosePrecision(tree, "Date of birth", "Year-Month");
    expect(onChange).toHaveBeenLastCalledWith("1997-07");
    expect(input(tree).props.type).toBe("month");
    expect(input(tree).props.value).toBe("1997-07");
    expect(input(tree).props.max).toBeUndefined();
    act(() => input(tree).props.onChange({ target: { value: "1998-03" } }));
    expect(onChange).toHaveBeenLastCalledWith("1998-03");
    choosePrecision(tree, "Date of birth", "Year");
    expect(onChange).toHaveBeenLastCalledWith("1998");
    expect(tree.root.findByType("select" as any).props.value).toBe("1998");
    choosePrecision(tree, "Date of birth", "Year-Month");
    expect(onChange).toHaveBeenLastCalledWith("");
    expect(input(tree).props.value).toBe("");
    choosePrecision(tree, "Date of birth", "Date");
    expect(input(tree).props.type).toBe("date");
  });

  it("opens a stored year or month in its own precision", () => {
    const year = mount({ initial: "1997", label: "Date of birth", precision: true });
    expect(precisionButton(year.tree, "Date of birth").props.accessibilityValue).toEqual({ text: "Year" });
    expect(year.tree.root.findByType("select" as any).props.value).toBe("1997");
    const month = mount({ initial: "2001-04", label: "Date of injury", precision: true });
    expect(precisionButton(month.tree, "Date of injury").props.accessibilityValue).toEqual({ text: "Year-Month" });
    expect(month.tree.root.findByType("input" as any).props.value).toBe("2001-04");
  });

  it("the year is a dropdown from the current year back 120 years, emitting a plain year or clearing", () => {
    const { tree, onChange } = mount({ label: "Surgery date", precision: true });
    choosePrecision(tree, "Surgery date", "Year");
    const select = () => tree.root.findByType("select" as any);
    const years = tree.root.findAllByType("option" as any).map((option) => option.props.value);
    expect(years.slice(0, 2)).toEqual(["", String(NOW.getFullYear())]);
    expect(years[years.length - 1]).toBe(String(NOW.getFullYear() - 120));
    act(() => select().props.onChange({ target: { value: "1990" } }));
    expect(onChange).toHaveBeenLastCalledWith("1990");
    act(() => select().props.onChange({ target: { value: "" } }));
    expect(onChange).toHaveBeenLastCalledWith("");
  });
});
