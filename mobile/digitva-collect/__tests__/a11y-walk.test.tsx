/**
 * Screen reader and target-size walk (docs/policy/expo-client.md "Text size, high contrast and screen readers",
 * Checking): every pressable, switch and tappable text on the rendered screens has a label (its own or its text)
 * and a role, and a target of at least 44 pt (its height or minHeight plus hitSlop). The jest window is 750 wide,
 * under the 768 phone breakpoint, so controls take their 44 pt phone height (useControlHeight).
 */
import React from "react";
import { StyleSheet, Text, View } from "react-native";
import { act, create, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";

const mockRouter = { replace: jest.fn(), push: jest.fn(), back: jest.fn() };
jest.mock("expo-router", () => ({ Redirect: () => null, useRouter: () => mockRouter, useLocalSearchParams: () => ({ userId: "a" }) }));
jest.mock("expo-constants", () => ({ __esModule: true, default: { expoConfig: { android: { package: "com.causeofdeathindia.digitvacollect" }, extra: undefined } } }));
jest.mock("expo-secure-store", () => ({
  canUseBiometricAuthentication: () => true,
  getItemAsync: jest.fn(async () => null),
  setItemAsync: jest.fn(async () => undefined),
}));
jest.mock("react-native-safe-area-context", () => ({ SafeAreaView: "SafeAreaView", useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));
// One stable state object: Settings re-reads its effects when `accounts` changes identity.
const mockAppState = {
  device: { device_id: "dev-1", server: "https://digitvav3.causeofdeathindia.com", project_id: "P", project_name: "Project" },
  accounts: [{ user_id: "a", name: "Asha" }],
  uiLocale: "en",
  chooseUiLocale: jest.fn(async () => undefined),
  lockNow: jest.fn(async () => true),
  reload: jest.fn(async () => undefined),
  unlocked: jest.fn(),
  slot: "active",
  switchSlot: jest.fn(async () => true),
};
jest.mock("../src/AppState", () => ({ useAppState: () => mockAppState }));
jest.mock("../src/vault", () => ({
  pinProblem: () => undefined,
  recordPinLength: jest.fn(),
  biometricKind: async () => "fingerprint",
  biometricEnabled: async () => false,
  screenLockEnabled: async () => false,
  screenLockAvailable: async () => true,
  turnOffBiometric: jest.fn(async () => undefined),
  turnOffScreenLock: jest.fn(async () => undefined),
}));
jest.mock("../src/errorExport", () => ({ exportErrors: async () => 0 }));
jest.mock("../src/appVariant", () => ({ isPlusVariant: () => false, isPlayDistribution: () => false }));
jest.mock("../src/interviewerDb", () => ({ ...jest.requireActual("../src/interviewerDb"), isUnlocked: () => true, openInterviewerDb: async () => ({}), createInterviewerDb: jest.fn() }));
jest.mock("../src/standalone/DataActions", () => ({ DataActions: () => null }));
jest.mock("../src/updateCheck", () => ({
  checkForUpdate: async () => ({ status: "current" }),
  checkServerCompatibility: async () => ({ status: "compatible", buildRevision: "abcdef0123456789abcdef0123456789abcdef01" }),
}));
jest.mock("../src/toast", () => ({ useToast: () => ({ show: jest.fn() }) }));
jest.mock("../src/auth", () => ({
  forgetDevice: jest.fn(async () => undefined),
  loadActiveSlot: jest.fn(async () => "active"),
  loadDevice: jest.fn(async () => null),
  deleteDemoAccount: jest.fn(),
  requestAccountDeletion: jest.fn(),
  decommissionMyDevice: jest.fn(),
  listMyDevices: async () => [],
  refreshAccessSummary: async () => ({ user: { user_id: "a", name: "Asha" }, is_admin: false, roles: ["interviewer"], demo_coding: { available: false, project_ids: [] }, projects: [] }),
  signIn: jest.fn(),
}));
jest.mock("../src/devicePermissions.native", () => ({
  readDevicePermissions: async () => ({ camera: { granted: false, canAskAgain: true }, microphone: { granted: false, canAskAgain: true } }),
  requestDevicePermission: async () => ({ granted: true, canAskAgain: true }),
}));
jest.mock("../src/reEnrolConfirm", () => ({ confirmReEnrol: jest.fn(async () => undefined), reEnrolDevice: jest.fn(async () => undefined) }));
jest.mock("../src/UnlockOffer", () => ({ biometricText: (key: string) => key, useBiometricKind: () => "fingerprint", pendingUnlockOffer: jest.fn(), UnlockOffer: () => null }));

import NativeSettings from "../src/nativeRoutes/settings";
import SignIn from "../src/nativeRoutes/sign-in";
import PinSetup from "../src/nativeRoutes/pin-setup";
import { PinBoxes } from "../src/PinBoxes";
import { ShellContext, type Shell } from "../src/nativeShell/shellContext";
import { BottomSheet, SheetRow } from "../src/nativeShell/BottomSheet";
import { Button, Card, ChoiceRow, ListRow, Notice, PasswordInput, SegmentedControl, TextLink } from "../src/ui";
import { Checkbox, MenuChoiceRow, RemovableChip } from "../src/ui/controls";
import { __setDisplayForTest } from "../src/theme";
import { HomeView, InterviewsView } from "../src/nativeRoutes/worklistParts";
import { buildInterviewItems, interviewCounts } from "../src/ui/interviewRows";
import { homeSummary } from "../src/ui/homeSummary";

const noop = () => undefined;
const draft = (id: string, extra = {}) => ({ id, project_id: "P1", site_id: "S1", org_unit_id: null, completed: 0, updated_at: "2026-10-23T13:40:00.000Z", death_id: null, unique_id: null, client_death_id: null, ...extra }) as never;
const caseRow = (id: string, name: string) => ({
  death_id: id, unique_id: `AAM01-${id}`, project_id: "P1", site_id: "S1", org_unit_id: null, unit_name: "CHC Bhoranj", state: "registered",
  source: "reported", my_draft_id: null, updated_at: "2026-10-01T00:00:00Z",
  deceased: { name, sex: "male", age_years: 68, date_of_death: "2026-09-12" }, household_address: { village_ward: "Hamirpur" },
}) as never;
const items = buildInterviewItems({ drafts: [draft("d1")], registrations: [], cases: [], onlineCases: [caseRow("c1", "Ram Lal")], submitted: [], revisions: [] });

const shell: Shell = {
  sheet: null, openSheet: jest.fn(), closeSheet: jest.fn(), userId: "a", server: "https://digitvav3.causeofdeathindia.com",
  sync: { work: { unsent: 0, attention: 0, inProgress: 0, items: [] }, lastAt: undefined, busy: false, result: undefined, offline: false },
  sendNow: jest.fn(async () => undefined), recount: jest.fn(async () => undefined), refreshNow: jest.fn(async () => undefined), header: true, tabs: true,
  titleInBar: true, screenTitle: undefined, publishTitle: jest.fn(),
};

const MIN_TARGET = 44;
const INTERACTIVE_ROLES = new Set(["button", "link", "radio", "checkbox", "switch", "tab", "menuitem", "togglebutton"]);

/** Host nodes the user can tap: Pressable/Touchable (onClick), the native switch, and Text with onPress. */
function tappables(tree: ReactTestRenderer): ReactTestInstance[] {
  return tree.root.findAll((node) => {
    if (typeof node.type !== "string") return false;
    const host: string = node.type;
    return typeof node.props.onClick === "function" || host === "RCTSwitch" || (host === "Text" && typeof node.props.onPress === "function");
  });
}

const textOf = (node: ReactTestInstance): string =>
  node.children.map((child) => (typeof child === "string" ? child : textOf(child))).join("");

const slop = (hitSlop: unknown, side: "top" | "bottom"): number =>
  typeof hitSlop === "number" ? hitSlop : ((hitSlop as Record<string, number> | undefined)?.[side] ?? 0);

/** What is wrong with one tappable node, or nothing. */
function problems(node: ReactTestInstance): string[] {
  const host = String(node.type);
  const name = node.props.accessibilityLabel || textOf(node).trim();
  const found: string[] = [];
  if (!name) found.push("no label");
  // The native switch carries its role itself on device; the rest must say what they are.
  const role = node.props.accessibilityRole ?? (host === "RCTSwitch" ? "switch" : undefined);
  if (!role || !INTERACTIVE_ROLES.has(role)) found.push(`role ${String(role)}`);
  const style = StyleSheet.flatten(node.props.style) ?? {};
  // A full-screen backdrop (a sheet's tap-to-close scrim) is as large as the screen.
  const fill = style.position === "absolute" && style.top === 0 && style.bottom === 0;
  if (host !== "RCTSwitch" && !fill) {
    const height = Math.max(Number(style.height ?? 0), Number(style.minHeight ?? 0)) + slop(node.props.hitSlop, "top") + slop(node.props.hitSlop, "bottom");
    if (height < MIN_TARGET) found.push(`target ${height}pt`);
  }
  return found.length ? [`${name || host}: ${found.join(", ")}`] : [];
}

function audit(tree: ReactTestRenderer): { count: number; offenders: string[] } {
  const nodes = tappables(tree);
  return { count: nodes.length, offenders: nodes.flatMap(problems) };
}

let mounted: ReactTestRenderer | undefined;

async function render(element: React.ReactElement): Promise<ReactTestRenderer> {
  await act(async () => {
    mounted = create(<ShellContext.Provider value={shell}>{element}</ShellContext.Provider>);
  });
  return mounted!;
}

afterEach(() => {
  act(() => mounted?.unmount());
  mounted = undefined;
});

function Gallery() {
  const [pin, setPin] = React.useState("12");
  return (
    <View>
      <Button label="Save" onPress={() => undefined} />
      <Button label="Delete" variant="destructive" onPress={() => undefined} />
      <Button label="X" size="icon" accessibilityLabel="Close" onPress={() => undefined} />
      <TextLink label="Cancel" onPress={() => undefined} />
      <Card grouped>
        <ListRow label="Profile" secondary="Asha" onPress={() => undefined} />
        <ChoiceRow label="Male" secondaryLabel="पुरुष" secondaryLanguage="hi-IN" selected onPress={() => undefined} />
        <ChoiceRow label="Fever" role="checkbox" selected={false} onPress={() => undefined} />
      </Card>
      <SegmentedControl accessibilityLabel="Sex" options={[{ value: "m", label: "Male" }, { value: "f", label: "Female" }]} value="m" onChange={() => undefined} />
      <PasswordInput accessibilityLabel="Password" value="" onChangeText={() => undefined} />
      <PinBoxes label="PIN" value={pin} onChange={setPin} autoFocus={false} />
      <Notice tone="error">Wrong PIN</Notice>
      <Checkbox label="Agree" checked={false} onChange={() => undefined} />
      <MenuChoiceRow label="English" selected onPress={() => undefined} />
      <RemovableChip label="Site A" removeLabel="Remove Site A" onRemove={() => undefined} />
      <BottomSheet visible title="Choose" onClose={() => undefined}>
        <SheetRow label="Option" onPress={() => undefined} />
      </BottomSheet>
      <Text>end</Text>
    </View>
  );
}

beforeEach(() => {
  __setDisplayForTest({ textSize: "medium", highContrast: "system", osHighContrast: false });
});

describe.each([
  ["shared controls", () => <Gallery />],
  ["Settings", () => <NativeSettings />],
  ["Sign in", () => <SignIn />],
  ["Set PIN", () => <PinSetup />],
  ["Home", () => <HomeView loaded offline={false} summary={homeSummary(items, interviewCounts(items))} unsent={2} canStart busy={false} onResume={noop} onStart={noop} onSend={noop} onViewTodo={noop} />],
  ["Interviews", () => <InterviewsView loaded offline={false} items={items} canRegister refreshing={false} busy={false} canRefresh hasMore={false} loadingMore={false} loadFailed={false} onAction={noop} onRetryDemo={noop} onRegister={noop} onRefresh={noop} onLoadMore={noop} />],
])("%s", (_name, element) => {
  it("labels every control, gives it a role and a 44pt target", async () => {
    const tree = await render(element());
    const { count, offenders } = audit(tree);
    expect(count).toBeGreaterThan(0);
    expect(offenders).toEqual([]);
  });
});

it("the walk fails a pressable with no label, no role and a small target (the check is not vacuous)", async () => {
  const { Pressable } = require("react-native");
  const tree = await render(<Pressable style={{ height: 20 }} onPress={() => undefined} />);
  expect(audit(tree).offenders).toEqual(["View: no label, role undefined, target 20pt"]);
});

it("Settings has a Display section with a labelled Text size control and High contrast switch", async () => {
  const tree = await render(<NativeSettings />);
  const switchNode = tree.root.findByProps({ testID: "high-contrast", accessibilityRole: "switch" });
  expect(switchNode.props.accessibilityRole).toBe("switch");
  expect(switchNode.props.accessibilityLabel).toBe("High contrast");
  expect(switchNode.props.value).toBe(false);
  const sizes = tree.root.findAll((node) => typeof node.type === "string" && node.props.accessibilityRole === "radio" && ["Small", "Medium", "Large"].includes(node.props.accessibilityLabel));
  expect(sizes.map((node) => [node.props.accessibilityLabel, node.props.accessibilityState.checked])).toEqual([["Small", false], ["Medium", true], ["Large", false]]);
  await act(async () => { switchNode.props.onValueChange(true); });
  expect(tree.root.findByProps({ testID: "high-contrast" }).props.value).toBe(true);
  await act(async () => { sizes[2].props.onClick(); });
  const large = tree.root.findAll((node) => typeof node.type === "string" && node.props.accessibilityLabel === "Large" && node.props.accessibilityRole === "radio")[0];
  expect(large.props.accessibilityState.checked).toBe(true);
});

it("Interviews offers Refresh as an accessibility action, the same as pulling the list", async () => {
  const onRefresh = jest.fn();
  const tree = await render(<InterviewsView loaded offline={false} items={items} canRegister refreshing={false} busy={false} canRefresh hasMore={false} loadingMore={false} loadFailed={false} onAction={noop} onRetryDemo={noop} onRegister={noop} onRefresh={onRefresh} onLoadMore={noop} />);
  const list = tree.root.findByProps({ testID: "interviews-list" });
  expect(list.props.accessibilityActions).toEqual([{ name: "refresh", label: "Refresh" }]);
  act(() => list.props.onAccessibilityAction({ nativeEvent: { actionName: "refresh" } }));
  expect(onRefresh).toHaveBeenCalledTimes(1);
});
