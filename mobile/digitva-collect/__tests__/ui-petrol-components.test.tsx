/** Petrol theme components in src/ui.tsx: equal-width segmented control, whole-row choices, notices, buttons. */
import { StyleSheet, Text } from "react-native";
import { act, create, type ReactTestInstance } from "react-test-renderer";


import { Button, Card, ChoiceRow, FieldLabel, ListRow, Notice, SegmentedControl, Separator, styles, TextLink, ThemedSwitch } from "../src/ui";
import { contrastRatio, disabledButtonTone, getTheme, SWITCH_THUMB, ui } from "../src/theme";

async function render(element: React.ReactElement) {
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(element); });
  return tree.root;
}

const hosts = (root: ReactTestInstance, role: string) =>
  root.findAll((n) => typeof n.type === "string" && n.props.accessibilityRole === role);
const flat = (node: ReactTestInstance, pressed = false) =>
  StyleSheet.flatten(typeof node.props.style === "function" ? node.props.style({ pressed }) : node.props.style);
const texts = (root: ReactTestInstance) => root.findAllByType(Text).map((n) => [n.props.children].flat().join(""));

describe("SegmentedControl", () => {
  const options = [
    { value: "male", label: "Male" },
    { value: "female", label: "Female" },
    { value: "undetermined", label: "Undetermined" },
    { value: "unknown", label: "Unknown" }
  ] as const;

  test("every segment takes an equal share, the chosen one is checked and changes the value", async () => {
    const onChange = jest.fn();
    const root = await render(<SegmentedControl accessibilityLabel="Sex" options={options} value="female" onChange={onChange} />);
    const segments = hosts(root, "radio");
    expect(segments).toHaveLength(4);
    expect(segments.map((s) => flat(s).flex)).toEqual([1, 1, 1, 1]);
    expect(segments.map((s) => flat(s).flexBasis)).toEqual([0, 0, 0, 0]);
    expect(segments.map((s) => s.props.accessibilityState.checked)).toEqual([false, true, false, false]);
    expect(hosts(root, "radiogroup")[0].props.accessibilityLabel).toBe("Sex");
    act(() => root.findAll((n) => n.props.accessibilityLabel === "Undetermined" && typeof n.props.onPress === "function")[0].props.onPress());
    expect(onChange).toHaveBeenCalledWith("undetermined");
  });

  test("with no value nothing is checked, and disabled segments do not fire", async () => {
    const onChange = jest.fn();
    const root = await render(<SegmentedControl accessibilityLabel="Sex" options={options} value={undefined} disabled onChange={onChange} />);
    const segments = hosts(root, "radio");
    expect(segments.length).toBe(4);
    expect(segments.every((s) => s.props.accessibilityState.checked === false && s.props.accessibilityState.disabled === true)).toBe(true);
  });
});

describe("ChoiceRow", () => {
  test("a selected radio row is a tint fill with a semibold label and no edge; the whole row presses", async () => {
    const onPress = jest.fn();
    const root = await render(<ChoiceRow label="Home" secondaryLabel="घर" selected onPress={onPress} />);
    const [row] = hosts(root, "radio");
    expect(row.props.accessibilityState).toEqual({ checked: true, disabled: false });
    expect(row.props.accessibilityLabel).toBe("Home, घर");
    const style = flat(row);
    expect(style.backgroundColor).toBe(ui.light.primaryTint);
    expect(style.borderWidth ?? 0).toBe(0);
    expect(style.minHeight).toBe(56);
    const [english, hindi] = root.findAllByType(Text);
    expect(StyleSheet.flatten(english.props.style).fontWeight).toBe("600");
    // The second language is ink, not grey.
    expect(StyleSheet.flatten(hindi.props.style).color).toBe(ui.light.foreground);
    act(() => root.findAll((n) => n.props.accessibilityRole === "radio" && typeof n.props.onPress === "function")[0].props.onPress());
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  test("an unselected checkbox row is 48pt on the card fill with a regular label", async () => {
    const root = await render(<ChoiceRow role="checkbox" label="Chest pain" selected={false} onPress={() => undefined} />);
    const [row] = hosts(root, "checkbox");
    expect(row).toBeDefined();
    expect(row.props.accessibilityState.checked).toBe(false);
    expect(flat(row)).toMatchObject({ minHeight: 48, backgroundColor: ui.light.card });
    expect(StyleSheet.flatten(root.findAllByType(Text)[0].props.style).fontWeight).toBe("400");
  });
});

describe("Notice and cards", () => {
  test("an error notice is an announced error-tint card with ink text", async () => {
    const root = await render(<Notice tone="error">Could not save</Notice>);
    const [alert] = hosts(root, "alert");
    expect(StyleSheet.flatten(alert.props.style).backgroundColor).toBe(ui.light.destructiveSoft);
    const text = root.findAllByType(Text).find((n) => n.props.children === "Could not save");
    expect(text).toBeDefined();
    expect(StyleSheet.flatten(text!.props.style).color).toBe(ui.light.foreground);
  });

  test("an info notice is not announced as an alert", async () => {
    const root = await render(<Notice tone="info">Hint</Notice>);
    expect(texts(root)).toContain("Hint");
    expect(hosts(root, "alert")).toHaveLength(0);
  });

  test("cards have no border", async () => {
    expect("borderWidth" in styles.card).toBe(false);
    const root = await render(<Card testID="c"><Text>x</Text></Card>);
    expect(StyleSheet.flatten(root.findAll((n) => typeof n.type === "string" && n.props.testID === "c")[0].props.style).backgroundColor).toBe(ui.light.card);
  });
});

describe("Button", () => {
  const pressableOf = (root: ReactTestInstance) => root.findAll((n) => n.props.hitSlop !== undefined && typeof n.props.style === "function")[0];

  test("secondary is tint-filled, danger is red text with no fill", async () => {
    const secondary = await render(<Button kind="secondary" label="Cancel" onPress={() => undefined} />);
    expect(flat(pressableOf(secondary))).toMatchObject({ backgroundColor: ui.light.primaryTint });
    const danger = await render(<Button kind="danger" label="Discard" onPress={() => undefined} />);
    expect(flat(pressableOf(danger))).toMatchObject({ backgroundColor: "transparent" });
    expect(StyleSheet.flatten(danger.findAllByType(Text)[0].props.style).color).toBe(ui.light.destructiveText);
  });

  test("a disabled primary keeps a readable label: tint fill, faded primary text at 4.5:1 or more, full opacity", async () => {
    const root = await render(<Button label="Save" disabled onPress={() => undefined} />);
    const tone = disabledButtonTone(ui.light);
    expect(flat(pressableOf(root))).toMatchObject({ backgroundColor: ui.light.primaryTint, opacity: 1 });
    const label = StyleSheet.flatten(root.findAllByType(Text)[0].props.style).color;
    expect(label).toBe(tone.fg);
    expect(label).not.toBe(ui.light.primary); // faded, so it reads as disabled
    expect(contrastRatio(label, ui.light.primaryTint)).toBeGreaterThanOrEqual(4.5);
  });
});

describe("TextLink", () => {
  test("is a 44pt button with no fill; destructive is red", async () => {
    const root = await render(<TextLink label="Forgot password" onPress={() => undefined} />);
    const link = hosts(root, "button")[0];
    expect(link.props.accessibilityLabel).toBe("Forgot password");
    expect(flat(link)).toMatchObject({ minHeight: 44, minWidth: 44 });
    expect(flat(link).backgroundColor).toBeUndefined();
    expect(StyleSheet.flatten(root.findAllByType(Text)[0].props.style).color).toBe(ui.light.primary);
    const red = await render(<TextLink label="Delete draft" tone="destructive" onPress={() => undefined} />);
    expect(StyleSheet.flatten(red.findAllByType(Text)[0].props.style).color).toBe(ui.light.destructiveText);
  });
});

describe("FieldLabel", () => {
  test("a required field reads its label then a grey Required, never an asterisk", async () => {
    const root = await render(<FieldLabel label="Name of the deceased" required />);
    const all = texts(root).join("|");
    expect(all).toContain("Name of the deceased");
    expect(all).toContain("Required");
    expect(all).not.toContain("*");
    const suffix = root.findAllByType(Text).find((n) => n.props.children === "  Required")!;
    expect(suffix).toBeDefined();
    expect(StyleSheet.flatten(suffix.props.style).color).toBe(ui.light.mutedForeground);
    // The suffix is at the secondary size, below the label's body size.
    const { typography } = getTheme("light");
    expect(StyleSheet.flatten(suffix.props.style).fontSize).toBe(typography.subhead.fontSize);
    expect(StyleSheet.flatten(suffix.props.style).fontSize).toBeLessThan(StyleSheet.flatten(suffix.parent!.props.style).fontSize as number);
    const plain = await render(<FieldLabel label="Father's name" />);
    expect(texts(plain).join("|")).toContain("Father's name");
    expect(texts(plain).join("|")).not.toContain("Required");
  });
});

describe("ListRow chevron slot", () => {
  const trailingWidth = (row: ReactTestInstance) => row.findAll((n) => typeof n.type === "string" && flat(n).width === 24);
  test("in a chevronSlot card a row without onPress keeps the 24pt slot, so values line up with pressable rows", async () => {
    const root = await render(
      <Card grouped chevronSlot>
        <ListRow label="Unsent" value="2" numeric />
        <Separator />
        <ListRow label="Need a visit" value="3" numeric onPress={() => undefined} />
      </Card>
    );
    const rows = root.findAll((n) => typeof n.type === "string" && flat(n).minHeight === 48);
    expect(rows.length).toBeGreaterThanOrEqual(2);
    expect(trailingWidth(rows[0])).toHaveLength(1);
    expect(trailingWidth(rows[rows.length - 1])).toHaveLength(1);
  });

  test("outside a chevronSlot card a plain row has no slot", async () => {
    const root = await render(<Card grouped><ListRow label="Version 1.0" /></Card>);
    expect(trailingWidth(root)).toHaveLength(0);
  });
});

describe("ListRow counts", () => {
  test("a count sits in a right-aligned tabular column; attention tints the row and the badge is amber with ink", async () => {
    const root = await render(<ListRow label="Ready to send" value="2" numeric tone="attention" badge />);
    const rowView = root.findAll((n) => typeof n.type === "string" && flat(n).minHeight === 48)[0];
    expect(flat(rowView).backgroundColor).toBe(ui.light.attentionTint);
    const badge = root.findAll((n) => typeof n.type === "string" && flat(n).backgroundColor === ui.light.attention);
    expect(badge).toHaveLength(1);
    const count = root.findAllByType(Text).find((n) => n.props.children === "2")!;
    expect(count).toBeDefined();
    expect(StyleSheet.flatten(count.props.style)).toMatchObject({ color: ui.light.onAttention, fontVariant: ["tabular-nums"] });
  });

  test("a plain count has no tint, a fixed-width right-aligned value, and a tappable row reads label and value", async () => {
    const onPress = jest.fn();
    const root = await render(<ListRow label="Need a visit" value="5" numeric onPress={onPress} />);
    const count = root.findAllByType(Text).find((n) => n.props.children === "5")!;
    expect(count).toBeDefined();
    expect(StyleSheet.flatten(count.props.style)).toMatchObject({ textAlign: "right", minWidth: 48, fontVariant: ["tabular-nums"] });
    const [button] = hosts(root, "button");
    expect(button.props.accessibilityLabel).toBe("Need a visit, 5");
    expect(flat(button).backgroundColor).toBeUndefined();
    act(() => root.findAll((n) => n.props.accessibilityLabel === "Need a visit, 5" && typeof n.props.onPress === "function")[0].props.onPress());
    expect(onPress).toHaveBeenCalledTimes(1);
  });
});

describe("ListRow value and action rows", () => {
  test("a plain value takes the rest of the row on one middle-ellipsised line; the label never shrinks", async () => {
    const root = await render(<ListRow label="Device ID" value="2201fd01-635a-4394-a2c3-ae07c7928ba9" mono />);
    const label = root.findAllByType(Text).find((n) => n.props.children === "Device ID")!;
    const value = root.findAllByType(Text).find((n) => n.props.children === "2201fd01-635a-4394-a2c3-ae07c7928ba9")!;
    expect(label).toBeDefined();
    expect(value).toBeDefined();
    expect(StyleSheet.flatten(label.parent!.props.style)).toMatchObject({ flexShrink: 0 });
    expect(StyleSheet.flatten(label.parent!.props.style).flex).toBeUndefined();
    expect(value.props.numberOfLines).toBe(1);
    expect(value.props.ellipsizeMode).toBe("middle");
    expect(StyleSheet.flatten(value.props.style)).toMatchObject({ flex: 1, minWidth: 0, textAlign: "right" });
    const plain = await render(<ListRow label="Auto-lock" value="5 minutes" />);
    const plainValue = plain.findAllByType(Text).find((n) => n.props.children === "5 minutes")!;
    expect(plainValue.props.numberOfLines).toBe(1);
    expect(plainValue.props.ellipsizeMode).toBe("middle");
  });

  test("a row with no value keeps a filling label, so its chevron sits at the end (Home and Interviews rows)", async () => {
    const root = await render(<ListRow label="Drafts in progress" onPress={jest.fn()} />);
    const label = root.findAllByType(Text).find((n) => n.props.children === "Drafts in progress")!;
    expect(StyleSheet.flatten(label.parent!.props.style)).toMatchObject({ flex: 1, minWidth: 0 });
  });

  test("an action row draws its label in primary with no chevron, and in secondary while disabled", async () => {
    const root = await render(<Card grouped><ListRow label="Export errors" action onPress={jest.fn()} /></Card>);
    const label = root.findAllByType(Text).find((n) => n.props.children === "Export errors")!;
    expect(StyleSheet.flatten(label.props.style).color).toBe(ui.light.primary);
    // A tappable row without `action` has its chevron: the slot view is the label's sibling after it.
    const nav = await render(<ListRow label="Help guide" onPress={jest.fn()} />);
    const navRow = hosts(nav, "button")[0];
    const actionRow = hosts(root, "button")[0];
    expect(navRow.findAll((n) => typeof n.type === "string" && StyleSheet.flatten(n.props.style)?.width === 24)).toHaveLength(1);
    expect(actionRow.findAll((n) => typeof n.type === "string" && StyleSheet.flatten(n.props.style)?.width === 24)).toHaveLength(0);
    const disabled = await render(<ListRow label="Export errors" action disabled onPress={jest.fn()} />);
    expect(StyleSheet.flatten(disabled.findAllByType(Text).find((n) => n.props.children === "Export errors")!.props.style).color).toBe(ui.light.mutedForeground);
  });

  test("a destructive second line is the error colour (Could not reach the server)", async () => {
    const root = await render(<ListRow label="Check server compatibility" secondary="Could not reach the server" secondaryTone="destructive" action onPress={jest.fn()} />);
    const line = root.findAllByType(Text).find((n) => n.props.children === "Could not reach the server")!;
    expect(StyleSheet.flatten(line.props.style).color).toBe(ui.light.destructiveText);
  });

  test("a TextLink in the trailing slot is the small in-row link; outside a row it keeps the body size", async () => {
    const root = await render(<ListRow label="This phone" trailing={<TextLink label="Sign out" onPress={jest.fn()} />} />);
    const link = StyleSheet.flatten(root.findAllByType(Text).find((n) => n.props.children === "Sign out")!.props.style);
    const { typography } = getTheme("light");
    expect(link).toMatchObject({ fontSize: typography.caption.fontSize, fontWeight: "600", color: ui.light.primary });
    const alone = await render(<TextLink label="Refresh devices" onPress={jest.fn()} />);
    expect(StyleSheet.flatten(alone.findAllByType(Text)[0].props.style)).toMatchObject({ fontSize: typography.body.fontSize, fontWeight: "500" });
    const [target] = hosts(root, "button");
    expect(flat(target)).toMatchObject({ minHeight: 44, minWidth: 44 });
  });
});

describe("ThemedSwitch", () => {
  test("primary track on, border track off, white thumb on both platforms", async () => {
    const root = await render(<ThemedSwitch accessibilityLabel="High contrast" value onValueChange={jest.fn()} />);
    const node = root.findAll((n) => n.props.trackColor !== undefined)[0];
    expect(node.props.trackColor).toEqual({ false: ui.light.border, true: ui.light.primary });
    expect(node.props.thumbColor).toBe(SWITCH_THUMB);
    expect(node.props.ios_backgroundColor).toBe(ui.light.border);
    expect(node.props.accessibilityLabel).toBe("High contrast");
  });
});

describe("round-4 row geometry", () => {
  test("a compact segmented control in a card trims 2pt top and bottom so its row is 48pt", async () => {
    const opts = [{ value: "a", label: "A" }, { value: "b", label: "B" }];
    const inCard = await render(<Card grouped><SegmentedControl compact options={opts} value="a" onChange={() => undefined} accessibilityLabel="x" testID="seg" /></Card>);
    const alone = await render(<SegmentedControl compact options={opts} value="a" onChange={() => undefined} accessibilityLabel="x" testID="seg" />);
    const margin = (r: ReactTestInstance) => flat(r.findAll((n) => typeof n.type === "string" && n.props.testID === "seg")[0]).marginVertical;
    // 36pt control + 2 x (8 row padding - 2) = 48
    expect(margin(inCard)).toBe(-2);
    expect(margin(alone)).toBe(0);
  });

  test("a choice separator starts at the label text, after the ring and gap", async () => {
    const root = await render(<Card grouped><Separator /><Separator choice /></Card>);
    const lines = root.findAll((n) => typeof n.type === "string" && flat(n)?.height === StyleSheet.hairlineWidth);
    expect(lines).toHaveLength(2);
    expect(flat(lines[0]).marginLeft).toBe(16);
    expect(flat(lines[1]).marginLeft).toBe(50);
  });
});
