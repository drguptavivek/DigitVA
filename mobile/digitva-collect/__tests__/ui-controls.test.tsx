import { StyleSheet, Text, View } from "react-native";
import { act, create, type ReactTestInstance } from "react-test-renderer";

import { Checkbox, MenuChoiceRow, RemovableChip } from "../src/ui/controls";
import { ui } from "../src/theme";

async function render(element: React.ReactElement) {
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(element); });
  return tree.root;
}

const byRole = (root: ReactTestInstance, role: string) => [...new Map(root.findAll((n) => n.props?.accessibilityRole === role && typeof n.props.onPress === "function").map((n) => [n.props.accessibilityLabel, n])).values()];
const texts = (root: ReactTestInstance) => root.findAllByType(Text).map((n) => [n.props.children].flat().join(""));
const GLYPHS = /[✓✔×✕•]/;

describe("Checkbox", () => {
  test("announces role, label and checked state, and toggles", async () => {
    const onChange = jest.fn();
    const root = await render(<Checkbox checked={false} onChange={onChange} label="Show coder" />);
    const [box] = byRole(root, "checkbox");
    expect(box).toBeDefined();
    expect(box.props.accessibilityLabel).toBe("Show coder");
    expect(box.props.accessibilityState).toEqual({ checked: false, disabled: false });
    act(() => box.props.onPress());
    expect(onChange).toHaveBeenCalledWith(true);
  });

  test("draws the tick as a vector, never a glyph, with a 44px target", async () => {
    const root = await render(<Checkbox checked onChange={() => undefined} label="Coder" hideLabel />);
    const [box] = byRole(root, "checkbox");
    expect(box.props.accessibilityState.checked).toBe(true);
    expect(root.findAll((n) => n.props.d === "M5 12l5 5l10 -10").length).toBeGreaterThan(0);
    expect(texts(root).some((text) => GLYPHS.test(text))).toBe(false);
    expect(texts(root)).not.toContain("Coder");
    const host = root.findAll((n) => typeof n.type === "string" && n.props.accessibilityRole === "checkbox")[0];
    expect(StyleSheet.flatten(host.props.style).minHeight).toBeGreaterThanOrEqual(44);
  });
});

describe("MenuChoiceRow", () => {
  test("a radio row carries checked state and a vector tick only when selected", async () => {
    const root = await render(<View><MenuChoiceRow label="English" selected onPress={() => undefined} /><MenuChoiceRow label="Hindi" selected={false} onPress={() => undefined} /></View>);
    const rows = byRole(root, "radio");
    expect(rows.map((row) => row.props.accessibilityState.checked)).toEqual([true, false]);
    expect(rows[0].findAll((n) => n.props.d === "M5 12l5 5l10 -10").length).toBeGreaterThan(0);
    expect(rows[1].findAll((n) => n.props.d === "M5 12l5 5l10 -10")).toHaveLength(0);
    expect(texts(root).some((text) => GLYPHS.test(text))).toBe(false);
  });
});

describe("RemovableChip", () => {
  test("the whole chip removes, labelled for assistive tech, with a vector ✕", async () => {
    const onRemove = jest.fn();
    const root = await render(<RemovableChip label="Site: KA01" removeLabel="Remove Site: KA01" onRemove={onRemove} />);
    const [chip] = byRole(root, "button");
    expect(chip.props.accessibilityLabel).toBe("Remove Site: KA01");
    expect(texts(root)).toContain("Site: KA01");
    expect(texts(root).some((text) => GLYPHS.test(text))).toBe(false);
    act(() => chip.props.onPress());
    expect(onRemove).toHaveBeenCalledTimes(1);
  });
});

test("scrim and shadow tokens exist in both themes", () => {
  for (const mode of ["light", "dark"] as const) {
    expect(ui[mode].scrim).toMatch(/^rgba\(/);
    expect(ui[mode].shadow).toMatch(/rgba\(/);
  }
});
