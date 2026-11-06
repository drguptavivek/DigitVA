/** The enrol screen's Try the demo entry. */
import React from "react";
import { act, create } from "react-test-renderer";

const mockOpenUrl = jest.fn(async (_url: string) => undefined);
const mockRouter = { replace: jest.fn(), push: jest.fn(), back: jest.fn() };
const mockSwitchSlot = jest.fn(async (_slot: string) => true);

jest.mock("react-native", () => ({
  Platform: { OS: "android" }, Linking: { openURL: (url: string) => mockOpenUrl(url) },
  Pressable: "pressable", Text: "text", TextInput: "textinput", View: "view",
}));
jest.mock("expo-router", () => ({ useRouter: () => mockRouter }));
// react-native is a stub here, so the enrol screen's theme and icons are stubbed too.
jest.mock("../src/theme", () => ({ radius: {}, spacing: {}, typography: {}, useTheme: () => ({ ui: {}, typography: { caption: {}, subhead: {}, body: {}, headline: {}, title: {}, largeTitle: {} } }) }));
jest.mock("../src/Icon", () => ({ Icon: () => null, icons: {} }));
jest.mock("expo-constants", () => ({ __esModule: true, default: { deviceName: "Phone", expoConfig: { version: "1.0.0" } } }));
jest.mock("expo-camera", () => ({ CameraView: "camera", useCameraPermissions: () => [{ granted: true }, jest.fn()] }));
jest.mock("../src/AppState", () => ({ useAppState: () => ({ reload: jest.fn(), switchSlot: mockSwitchSlot }) }));
jest.mock("../src/auth", () => ({ enrolDevice: jest.fn() }));
jest.mock("../src/i18n", () => ({ t: (key: string) => key }));
jest.mock("../src/ui", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return {
    Button: (props: { label: string }) => ReactActual.createElement("button", props),
    ListRow: (props: { label: string }) => ReactActual.createElement("button", props),
    TextLink: (props: { label: string }) => ReactActual.createElement("button", props),
    PasswordInput: () => null,
    Card: ({ children }: { children: React.ReactNode }) => ReactActual.createElement("card", null, children),
    Separator: () => null,
    Screen: ({ children }: { children: React.ReactNode }) => ReactActual.createElement("screen", null, children),
    errorText: () => "generic",
    useUiStyles: () => ({ text: {}, muted: {}, error: {}, input: {}, card: {} }),
  };
});

jest.mock("../src/appVariant", () => ({ isPlusVariant: () => false }));
import Enrol from "../src/nativeRoutes/enrol";

const labels = (tree: ReturnType<typeof create>) => tree.root.findAllByType("button" as never).map((n) => n.props.label);

async function render(element: React.ReactElement) {
  let tree: ReturnType<typeof create>;
  await act(async () => {
    tree = create(element);
  });
  return tree!;
}

it("the enrol screen offers Try the demo in a release build too", async () => {
  expect((globalThis as { __DEV__?: boolean }).__DEV__).toBeDefined();
  const previous = (globalThis as { __DEV__?: boolean }).__DEV__;
  (globalThis as { __DEV__?: boolean }).__DEV__ = false;
  try {
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Enrol />);
    });
    expect(labels(tree!)).toContain("demoTryTitle");
    await act(async () => tree!.root.findAll((n) => n.props.label === "demoTryTitle")[0].props.onPress());
    // switchSlot opens /demo when the phone has no demo enrolment, or switches to the one it has.
    expect(mockSwitchSlot).toHaveBeenCalledWith("demo");
    await act(async () => tree!.root.findAll((n) => n.props.label === "welcomeScanTitle")[0].props.onPress());
    expect(labels(tree!)).toContain("cancel");
    expect(labels(tree!)).not.toContain("enrolSubmit"); // the paste box is debug only
  } finally {
    (globalThis as { __DEV__?: boolean }).__DEV__ = previous;
  }
});
