/** Round-6 design review items: segmented control in dark, badge ring, dates, sheet rows, engine-check colours. */
import { Platform, StyleSheet, Text } from "react-native";
import { act, create, type ReactTestInstance } from "react-test-renderer";

import { SheetRow } from "../src/nativeShell/BottomSheet";
import { clock } from "../src/nativeShell/shellContext";
import { getTheme } from "../src/theme";
import { Card, SegmentedControl } from "../src/ui";
import { useCaseCardStyles } from "../src/ui/CaseCard";
import { dateOnly } from "../src/ui/interviewRows";

async function render(element: React.ReactElement) {
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(element); });
  return tree.root;
}
const flat = (node: ReactTestInstance) => StyleSheet.flatten(typeof node.props.style === "function" ? node.props.style({ pressed: false }) : node.props.style);
const radios = (root: ReactTestInstance) => root.findAll((n) => typeof n.type === "string" && n.props.accessibilityRole === "radio");
const opts = [{ value: "a", label: "A" }, { value: "b", label: "B" }];

describe("SegmentedControl dark mode (M1)", () => {
  const scheme = jest.spyOn(require("react-native"), "useColorScheme");
  afterEach(() => scheme.mockReset());

  it("uses the tint look outside a card in dark, and keeps the card tone in light", async () => {
    scheme.mockReturnValue("dark");
    const dark = getTheme("dark").ui;
    const root = await render(<SegmentedControl accessibilityLabel="x" options={opts} value="a" onChange={() => undefined} />);
    const [selected] = radios(root);
    expect(flat(selected).backgroundColor).toBe(dark.primaryTint);
    expect(flat(root.findAllByType(Text)[0]).color).toBe(dark.primary);

    scheme.mockReturnValue("light");
    const light = getTheme("light").ui;
    const lightRoot = await render(<SegmentedControl accessibilityLabel="x" options={opts} value="a" onChange={() => undefined} />);
    expect(flat(radios(lightRoot)[0]).backgroundColor).toBe(light.card);
    const inCard = await render(<Card><SegmentedControl accessibilityLabel="x" options={opts} value="a" onChange={() => undefined} /></Card>);
    expect(flat(radios(inCard)[0]).backgroundColor).toBe(light.primaryTint);
  });
});

describe("case card badges (I1)", () => {
  function ringWidth() {
    let width: unknown;
    const Probe = () => { width = useCaseCardStyles().badge.borderWidth; return null; };
    return render(<Probe />).then(() => width);
  }
  const original = Platform.OS;
  afterEach(() => { Platform.OS = original; });

  it("has no ring on the phone and keeps the 1px ring on the web", async () => {
    Platform.OS = "android";
    expect(await ringWidth()).toBe(0);
    Platform.OS = "web";
    expect(await ringWidth()).toBe(1);
  });
});

describe("dates (H1, I2)", () => {
  it("writes a date without time as '3 Nov 2026', and a bare date never slips a day", () => {
    expect(dateOnly("2026-11-03")).toMatch(/^3 Nov 2026$/);
    expect(dateOnly("2026-11-03T10:00:00Z")).toMatch(/Nov 2026/);
    // Midnight-UTC timestamps are calendar dates: the UTC day, whatever the device zone.
    expect(dateOnly("2026-11-06T00:00:00Z")).toBe(dateOnly("2026-11-06"));
    expect(dateOnly("2026-11-06T00:00:00.000Z")).toBe(dateOnly("2026-11-06"));
    expect(dateOnly("2026-11-06T00:00:00Z")).toMatch(/^6 Nov 2026$/);
    expect(dateOnly("")).toBeNull();
    expect(dateOnly("not a date")).toBe("not a date");
  });

  it("writes the Home draft time in 12 hours like the other times", () => {
    expect(clock(new Date(2026, 10, 6, 16, 53).getTime())).toMatch(/^4:53\s?pm$/i);
  });
});

describe("SheetRow (K1)", () => {
  it("is 48dp for one line with 12dp vertical padding, so two lines grow the row", async () => {
    const root = await render(<SheetRow label="One line" onPress={() => undefined} />);
    const style = flat(root.findAll((n) => n.props.accessibilityRole === "button")[0]);
    expect(style.minHeight).toBe(48);
    expect(style.paddingVertical).toBe(12);
  });
});
