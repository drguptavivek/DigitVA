/** Petrol screen fixes: the password eye, the coding case lists as rows, and the theme string files. */
import { TextInput } from "react-native";
import { act, create, type ReactTestInstance } from "react-test-renderer";

const mockPush = jest.fn();
const mockPreference = { enabled: true };
jest.mock("expo-router", () => ({ useRouter: () => ({ push: mockPush }) }));
jest.mock("../src/icd11DorisPreference", () => ({ useIcd11DorisPreference: () => mockPreference }));

import { PasswordInput } from "../src/ui";
import { CodingCaseChips } from "../src/ui/CodingCaseChips";
import themeEn from "../src/strings/theme-en.json";
import themeHi from "../src/strings/theme-hi.json";

async function render(element: React.ReactElement) {
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(element); });
  return tree.root;
}
const hostInput = (root: ReactTestInstance) => root.findByType(TextInput);
const button = (root: ReactTestInstance, label: string) =>
  root.findAll((n) => n.props.accessibilityLabel === label && typeof n.props.onPress === "function")[0];

describe("PasswordInput", () => {
  it("masks the value until the eye is pressed, then names the button for hiding it", async () => {
    const root = await render(<PasswordInput accessibilityLabel="Password" value="secret" onChangeText={() => undefined} />);
    expect(hostInput(root).props.secureTextEntry).toBe(true);
    const show = button(root, "Show password");
    expect(show).toBeDefined();
    expect(show.props.accessibilityRole).toBe("button");
    await act(async () => show.props.onPress());
    expect(hostInput(root).props.secureTextEntry).toBe(false);
    expect(button(root, "Hide password")).toBeDefined();
    expect(button(root, "Show password")).toBeUndefined();
    await act(async () => button(root, "Hide password").props.onPress());
    expect(hostInput(root).props.secureTextEntry).toBe(true);
  });

  it("keeps autocorrect and capitalisation off while shown, and a 44pt target", async () => {
    const root = await render(<PasswordInput accessibilityLabel="Password" value="" onChangeText={() => undefined} />);
    await act(async () => button(root, "Show password").props.onPress());
    expect(hostInput(root).props).toMatchObject({ autoCorrect: false, autoCapitalize: "none", spellCheck: false });
    const style = button(root, "Hide password").props.style;
    expect(style.width).toBeGreaterThanOrEqual(44);
    expect(style.minHeight).toBeGreaterThanOrEqual(44);
  });

  it("takes its own labels (the long-PIN field) and passes typing to the parent only", async () => {
    const typed = jest.fn();
    const root = await render(<PasswordInput accessibilityLabel="PIN" showLabel="Show PIN" hideLabel="Hide PIN" value="" onChangeText={typed} />);
    expect(button(root, "Show PIN")).toBeDefined();
    act(() => hostInput(root).props.onChangeText("1234567"));
    expect(typed).toHaveBeenCalledWith("1234567");
  });
});

describe("coding case lists", () => {
  beforeEach(() => { mockPush.mockClear(); mockPreference.enabled = true; });

  it("are tappable rows in one card, not buttons, and open their list", async () => {
    const root = await render(<CodingCaseChips userId="u1" canLocal offline={false} />);
    expect(root.findAll((n) => n.props.testID === "coding-case-lists").length).toBeGreaterThan(0);
    for (const label of ["Local cases", "Online cases", "My coded cases"]) {
      const row = button(root, label);
      expect(row.props.accessibilityRole).toBe("button");
      // A row, not a filled primary button: no petrol fill of its own.
      expect(JSON.stringify(row.props.style({ pressed: false }))).not.toContain("#1f4d60");
    }
    await act(async () => button(root, "Online cases").props.onPress());
    await act(async () => button(root, "My coded cases").props.onPress());
    expect(mockPush.mock.calls.map(([to]) => to)).toEqual([
      { pathname: "/coding", params: { userId: "u1" } },
      { pathname: "/coding", params: { userId: "u1", initialHistory: "1" } },
    ]);
  });

  it("turns Online cases off while offline and Local cases off while DORIS is off", async () => {
    mockPreference.enabled = false;
    const root = await render(<CodingCaseChips userId="u1" canLocal offline />);
    expect(button(root, "Online cases").props.disabled).toBe(true);
    expect(button(root, "Local cases").props.disabled).toBe(true);
    expect(button(root, "My coded cases").props.disabled).toBe(false);
  });
});

it("has a Hindi string for every theme string", () => {
  expect(Object.keys(themeEn).length).toBeGreaterThan(0);
  expect(Object.keys(themeHi).sort()).toEqual(Object.keys(themeEn).sort());
  for (const value of Object.values(themeHi)) expect(value.trim()).not.toBe("");
});
