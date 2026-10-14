import type React from "react";
import { Modal, ScrollView, View } from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

import { hsl, palette, ui, uiRadius } from "../src/theme";
import { Alert, Badge, Button, Card, Chip, Input, MenuSelect, RadioRow, Separator, chartFor, menuTop } from "../src/workspace/doris/ui";

const mockTheme: { mode: "light" | "dark" } = { mode: "light" };
jest.mock("../src/theme", () => {
  const actual = jest.requireActual("../src/theme");
  return { ...actual, useTheme: () => actual.getTheme(mockTheme.mode) };
});

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
const contrast = (a: string, b: string) => { const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x); return (hi + 0.05) / (lo + 0.05); };

const flat = (style: unknown, state = { pressed: false }) => Object.assign({}, ...[typeof style === "function" ? style(state) : style].flat(3).filter(Boolean));
function render(node: React.ReactElement): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => { tree = create(node); });
  return tree;
}
const pressable = (tree: ReactTestRenderer) => tree.root.findAll((n) => n.props.hitSlop !== undefined && n.props.accessibilityRole !== undefined)[0];

describe("shadcn zinc tokens", () => {
  it("converts shadcn HSL numbers to the published zinc hex values", () => {
    expect(ui.light.background).toBe("#FFFFFF");
    expect(hsl(240, 10, 3.9)).toBe("#09090B");
    expect(ui.light.border).toBe("#CBD5E1");
    expect(ui.dark.background).toBe("#131E2E");
    expect(ui.dark.card).toBe("#1B2A3D");
    expect(ui.dark.destructive).toBe(hsl(0, 62.8, 30.6));
    expect(ui.light.destructive).toBe(hsl(0, 72.2, 50.6));
    expect(uiRadius).toMatchObject({ lg: 8, md: 6, sm: 4 });
  });

  it("never makes DORIS surfaces darker than the app page surface, with borders lighter than the fills", () => {
    const lum = (hex: string) => luminance(hex);
    expect(lum(ui.dark.background)).toBeGreaterThanOrEqual(lum(palette.dark.background) - 0.001);
    expect(lum(ui.dark.card)).toBeGreaterThanOrEqual(lum(ui.dark.background));
    for (const mode of ["light", "dark"] as const) {
      const t = ui[mode];
      expect(contrast(t.border, t.card)).toBeGreaterThan(1.15);
      expect(contrast(t.foreground, t.card)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(t.mutedForeground, t.card)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(t.mutedForeground, t.muted)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(t.foreground, t.background)).toBeGreaterThanOrEqual(4.5);
      // The control edge (inputs, choice rows, outline buttons) is a non-text UI component: >= 3:1 on the fill.
      expect(contrast(t.input, t.background)).toBeGreaterThanOrEqual(3);
    }
    expect(lum(ui.light.card)).toBeGreaterThanOrEqual(lum(palette.light.surface) - 0.001);
  });

  it("keeps brand blue as primary in both modes", () => {
    expect(ui.light.primary).toBe("#1D4ED8");
    expect(ui.dark.primary).toBe("#78A9FF");
  });

  it.each(["light", "dark"] as const)("keeps every text/background token pair at 4.5:1 in %s mode", (mode) => {
    const t = ui[mode];
    const pairs: Array<[string, string, string]> = [
      ["foreground/background", t.foreground, t.background],
      ["cardForeground/card", t.cardForeground, t.card],
      ["popoverForeground/popover", t.popoverForeground, t.popover],
      ["primaryForeground/primary", t.primaryForeground, t.primary],
      ["secondaryForeground/secondary", t.secondaryForeground, t.secondary],
      ["mutedForeground/background", t.mutedForeground, t.background],
      ["accentForeground/accent", t.accentForeground, t.accent],
      ["foreground/accent", t.foreground, t.accent],
      ["field label foreground/card", t.foreground, t.card],
      ["destructiveForeground/destructive", t.destructiveForeground, t.destructive],
      ["destructiveText/background", t.destructiveText, t.background],
      ["warningForeground/warning", t.warningForeground, t.warning],
      ["letter: background/bar part2", t.background, t.chartPart2.bar],
    ];
    t.chart.forEach((c, i) => {
      pairs.push([`chart-${i + 1} foreground/soft`, c.foreground, c.soft], [`chart-${i + 1} foreground/tint`, c.foreground, c.tint], [`chart-${i + 1} letter`, t.background, c.bar]);
    });
    pairs.push(["chart part2 foreground/soft", t.chartPart2.foreground, t.chartPart2.soft], ["chart part2 foreground/tint", t.chartPart2.foreground, t.chartPart2.tint]);
    for (const [name, fg, bg] of pairs) expect({ name, ratio: contrast(fg, bg) >= 4.5 }).toEqual({ name, ratio: true });
  });

  it.each(["light", "dark"] as const)("keeps borders, ring and warning edge visible (>= 3:1 where they mark a control) in %s mode", (mode) => {
    const t = ui[mode];
    expect(contrast(t.ring, t.background)).toBeGreaterThanOrEqual(3);
    expect(contrast(t.warningBorder, t.warning)).toBeGreaterThanOrEqual(3);
    expect(contrast(t.primary, t.background)).toBeGreaterThanOrEqual(3);
  });

  it("cycles chart-1..5 for Part I and uses slate for Part II", () => {
    expect(chartFor(ui.light, 5, false)).toEqual(ui.light.chart[0]);
    expect(chartFor(ui.dark, 0, true)).toEqual(ui.dark.chartPart2);
  });
});

describe("primitives", () => {
  beforeEach(() => { mockTheme.mode = "light"; });

  it("Button variants map to tokens in light and dark", () => {
    const expected = { default: ["primary", "primaryForeground"], secondary: ["secondary", "secondaryForeground"], destructive: ["destructive", "destructiveForeground"] } as const;
    for (const mode of ["light", "dark"] as const) {
      mockTheme.mode = mode;
      for (const [variant, [bg]] of Object.entries(expected)) {
        const tree = render(<Button label="Go" variant={variant as "default"} onPress={() => undefined} />);
        expect(flat(pressable(tree).props.style).backgroundColor).toBe((ui[mode] as any)[bg]);
      }
      const outline = render(<Button label="Go" variant="outline" onPress={() => undefined} />);
      expect(flat(pressable(outline).props.style)).toMatchObject({ backgroundColor: ui[mode].background, borderColor: ui[mode].input });
      const ghost = render(<Button label="Go" variant="ghost" onPress={() => undefined} />);
      expect(flat(ghost.root.findAll((n) => n.props.hitSlop !== undefined)[0].props.style)).toMatchObject({ backgroundColor: "transparent", borderColor: "transparent" });
    }
  });

  it("Button sizes are 40px, 44px on phones (sm trims padding, icon square) with 72px minimum width and 4pt hit-slop, disabled is half opacity and inert", () => {
    const press = jest.fn();
    const def = render(<Button label="Go" onPress={press} />);
    // The jest window is phone-sized, so the control height is the 44px phone step (40 on wide screens).
    expect(flat(pressable(def).props.style)).toMatchObject({ minHeight: 44, minWidth: 72 });
    expect(pressable(def).props.hitSlop).toBe(4);
    expect(flat(pressable(render(<Button label="Go" size="sm" onPress={press} />)).props.style)).toMatchObject({ minHeight: 44, paddingHorizontal: 12 });
    expect(flat(pressable(render(<Button size="icon" accessibilityLabel="x" onPress={press}><></></Button>)).props.style)).toMatchObject({ minHeight: 44, minWidth: 44 });
    const off = render(<Button label="Go" disabled onPress={press} />);
    expect(pressable(off).props.disabled).toBe(true);
    expect(flat(pressable(off).props.style).opacity).toBe(0.5);
    expect(pressable(off).props.accessibilityState).toMatchObject({ disabled: true });
  });

  it("Input uses the input border, ring on focus, muted placeholder and 40px height", () => {
    const tree = render(<Input accessibilityLabel="f" placeholder="p" />);
    const field = () => tree.root.findAll((n) => n.props.accessibilityLabel === "f" && n.props.placeholderTextColor !== undefined)[0];
    expect(field().props.placeholderTextColor).toBe(ui.light.mutedForeground);
    expect(flat(field().props.style)).toMatchObject({ borderColor: ui.light.input, borderWidth: 1 });
    expect(flat(field().props.style).minHeight).toBeGreaterThanOrEqual(40);
    act(() => field().props.onFocus({}));
    expect(flat(field().props.style).borderColor).toBe(ui.light.ring);
  });

  it("RadioRow and Chip show the primary border when selected", () => {
    const row = render(<RadioRow label="A" accessibilityLabel="a" selected onPress={() => undefined} />);
    expect(flat(row.root.findAll((n) => n.props.accessibilityRole === "radio")[0].props.style)).toMatchObject({ borderColor: ui.light.primary, backgroundColor: ui.light.accent, minHeight: 48, borderWidth: 1, borderRadius: 6 });
    const chip = render(<Chip accessibilityLabel="c" selected={false} onPress={() => undefined}>C</Chip>);
    expect(flat(pressable(chip).props.style)).toMatchObject({ borderColor: ui.light.input, borderRadius: 6, minWidth: 72, minHeight: 44, paddingHorizontal: 12 });
  });

  it("Card uses 16px inner padding and 12px gaps", () => {
    mockTheme.mode = "dark";
    const card = render(<Card testID="c"><Alert>x</Alert></Card>).root.findAll((n) => typeof n.type === "string" && n.props.testID === "c")[0];
    expect(flat(card.props.style)).toMatchObject({ padding: 16, gap: 12, backgroundColor: ui.dark.card, borderColor: ui.dark.border });
  });

  it("Badge, Alert and Separator follow their variants", () => {
    expect(flat(render(<Badge variant="destructive">x</Badge>).root.findAll((n) => n.props.style)[0].props.style).backgroundColor).toBe(ui.light.destructive);
    expect(flat(render(<Badge variant="outline">x</Badge>).root.findAll((n) => n.props.style)[0].props.style)).toMatchObject({ backgroundColor: "transparent", borderColor: ui.light.border });
    mockTheme.mode = "dark";
    const warn = render(<Alert variant="warning" testID="w">careful</Alert>).root.findAll((n) => n.props.testID === "w" && n.props.style)[0];
    expect(flat(warn.props.style)).toMatchObject({ backgroundColor: ui.dark.warning, borderColor: ui.dark.warningBorder, borderLeftWidth: 4 });
    expect(render(<Alert variant="destructive">bad</Alert>).root.findAll((n) => n.props.accessibilityRole === "alert").length).toBeGreaterThan(0);
    expect(flat(render(<Separator />).root.findAll((n) => n.props.style)[0].props.style)).toMatchObject({ height: 1, backgroundColor: ui.dark.border });
  });
});

describe("choice layout", () => {
  const { choiceColumns } = jest.requireActual("../src/workspace/doris/compact") as typeof import("../src/workspace/doris/compact");
  const short = ["Not stated", "Yes", "No", "Unknown"];

  it("uses 2 columns on phones and one per option (up to 4) on wide screens", () => {
    expect(choiceColumns(375, short)).toBe(2);
    expect(choiceColumns(1200, short)).toBe(4);
    expect(choiceColumns(1200, short.slice(0, 3))).toBe(3);
  });

  it("keeps one column on phones for a label over 28 characters", () => {
    expect(choiceColumns(375, [...short, "Place of occurrence that is not further specified"])).toBe(1);
    expect(choiceColumns(1200, [...short, "Place of occurrence that is not further specified"])).toBe(2);
  });

  it("falls back to one phone column when a single word cannot fit a measured two-column cell", () => {
    expect(choiceColumns(375, ["Not stated", "Undetermined"], 0)).toBe(2);
    expect(choiceColumns(375, ["Not stated", "Undetermined"], 290)).toBe(1);
    expect(choiceColumns(375, short, 290)).toBe(2);
  });

  it("5+ short options on wide screens use 3 columns", () => {
    expect(choiceColumns(1200, [...short, "Other"])).toBe(3);
  });

  it("sizes the group by its measured width, not the window", () => {
    const sex = ["Not stated", "Male", "Female", "Undetermined"];
    expect(choiceColumns(1200, sex)).toBe(4); // before the first layout the window stands in
    expect(choiceColumns(1200, sex, 240)).toBe(1); // a grid cell: "Undetermined" needs a full-width tile
    expect(choiceColumns(1200, sex, 1100)).toBe(4);
    expect(choiceColumns(1200, short, 1100)).toBe(4);
  });
});

describe("MenuSelect dropdown", () => {
  const options = [
    { value: "Y", label: "Years", accessibilityLabel: "Unit: Years" },
    { value: "D", label: "Days", accessibilityLabel: "Unit: Days", dimmed: true },
  ];
  const mountMenu = (onSelect = jest.fn()) => render(<MenuSelect triggerLabel="Unit" valueText="Units" selected="" options={options} onSelect={onSelect} />);
  const trigger = (tree: ReactTestRenderer) => tree.root.findByProps({ accessibilityLabel: "Unit" });
  const item = (tree: ReactTestRenderer, name: string) => tree.root.findByProps({ accessibilityLabel: name });

  it("is closed until the trigger opens it, with the trigger reporting expanded", () => {
    const tree = mountMenu();
    expect(tree.root.findAllByType(Modal)).toHaveLength(0);
    expect(trigger(tree).props.accessibilityState).toEqual({ expanded: false });
    act(() => trigger(tree).props.onPress());
    expect(trigger(tree).props.accessibilityState).toEqual({ expanded: true });
    expect(item(tree, "Unit: Years").props.accessibilityState).toEqual({ selected: false });
    expect(flat(item(tree, "Unit: Days").props.style)).toMatchObject({ opacity: 0.45 });
  });

  it("selects an option, passes it on and closes", () => {
    const onSelect = jest.fn();
    const tree = mountMenu(onSelect);
    act(() => trigger(tree).props.onPress());
    act(() => item(tree, "Unit: Days").props.onPress());
    expect(onSelect).toHaveBeenCalledWith("D");
    expect(tree.root.findAllByType(Modal)).toHaveLength(0);
    expect(trigger(tree).props.accessibilityState).toEqual({ expanded: false });
  });

  it("scrolls a long list inside the window and keeps the menu on screen, opening upward near the bottom", () => {
    const many = Array.from({ length: 40 }, (_item, index) => ({ value: `V${index}`, label: `Value ${index}`, accessibilityLabel: `Value: ${index}` }));
    // The trigger sits near the bottom of a 1334pt window (jest's default window height): the menu cannot fit below it.
    let tree!: ReactTestRenderer;
    act(() => { tree = create(<MenuSelect triggerLabel="Long" valueText="Units" selected="" options={many} onSelect={jest.fn()} />); });
    // jest's View mock has no native measure: the trigger wrapper reports a fixed window position instead.
    const wrapper = tree.root.findByType(View).instance as { measureInWindow?: (cb: (x: number, y: number, w: number, h: number) => void) => void };
    wrapper.measureInWindow = (cb) => cb(10, 1200, 100, 40);
    act(() => tree.root.findByProps({ accessibilityLabel: "Long" }).props.onPress());
    const list = tree.root.findByType(ScrollView);
    const menu = () => tree.root.findByProps({ accessibilityRole: "menu" });
    expect(tree.root.findByType(Modal).props.statusBarTranslucent).toBe(true);
    expect(list.props.style.maxHeight).toBeLessThanOrEqual(1334);
    expect(menu().props.style[0].opacity).toBe(0);
    act(() => menu().props.onLayout({ nativeEvent: { layout: { height: 900 } } }));
    const style = menu().props.style[0];
    expect(style.opacity).toBe(1);
    expect(style.top).toBe(1200 - 4 - 900);
    expect(style.top).toBeGreaterThanOrEqual(0);
    expect(style.top + 900).toBeLessThanOrEqual(1334);
    expect(tree.root.findAll((n) => typeof n.type === "string" && n.props.accessibilityRole === "menuitem")).toHaveLength(40);
  });

  it("places a menu that fits neither above nor below inside the window, and hides it until measured", () => {
    expect(menuTop({ x: 0, y: 300, width: 100, height: 40 }, 1300, 1334)).toBe(26);
    expect(menuTop({ x: 0, y: 100, width: 100, height: 40 }, 300, 1334)).toBe(144);
    expect(menuTop({ x: 0, y: 1200, width: 100, height: 40 }, 2000, 1334)).toBe(8);
    const tree = render(<MenuSelect triggerLabel="Unit" valueText="Units" selected="" options={options} onSelect={jest.fn()} />);
    act(() => tree.root.findByProps({ accessibilityLabel: "Unit" }).props.onPress());
    expect(tree.root.findByProps({ accessibilityRole: "menu" }).props.style[0].opacity).toBe(0);
  });

  it("closes on an outside press and on Escape (the modal's request-close)", () => {
    const onSelect = jest.fn();
    const tree = mountMenu(onSelect);
    act(() => trigger(tree).props.onPress());
    act(() => item(tree, "Close menu").props.onPress());
    expect(tree.root.findAllByType(Modal)).toHaveLength(0);
    act(() => trigger(tree).props.onPress());
    act(() => tree.root.findByType(Modal).props.onRequestClose());
    expect(tree.root.findAllByType(Modal)).toHaveLength(0);
    expect(onSelect).not.toHaveBeenCalled();
  });
});
