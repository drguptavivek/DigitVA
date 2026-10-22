/** The Public demo badge and its browser links; the enrol screen's entry. */
import React from "react";
import { act, create } from "react-test-renderer";

const mockOpenUrl = jest.fn(async (_url: string) => undefined);
const mockRouter = { replace: jest.fn(), push: jest.fn(), back: jest.fn() };

jest.mock("react-native", () => ({
  Platform: { OS: "android" }, Linking: { openURL: (url: string) => mockOpenUrl(url) },
  Pressable: "pressable", Text: "text", TextInput: "textinput", View: "view",
}));
jest.mock("expo-router", () => ({ useRouter: () => mockRouter }));
jest.mock("expo-constants", () => ({ __esModule: true, default: { deviceName: "Phone", expoConfig: { version: "1.0.0" } } }));
jest.mock("expo-camera", () => ({ CameraView: "camera", useCameraPermissions: () => [{ granted: true }, jest.fn()] }));
jest.mock("../src/AppState", () => ({ useAppState: () => ({ reload: jest.fn() }) }));
jest.mock("../src/auth", () => ({ enrolDevice: jest.fn() }));
jest.mock("../src/i18n", () => ({ t: (key: string) => key }));
jest.mock("../src/ui", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return {
    Button: (props: { label: string }) => ReactActual.createElement("button", props),
    Screen: ({ children }: { children: React.ReactNode }) => ReactActual.createElement("screen", null, children),
    errorText: () => "generic",
    useUiStyles: () => ({ text: {}, muted: {}, error: {}, input: {}, card: {} }),
  };
});

import DemoPanel from "../src/DemoPanel";
import { DEMO_SERVER } from "../src/enrolment";
import Enrol from "../src/nativeRoutes/enrol";

const labels = (tree: ReturnType<typeof create>) => tree.root.findAllByType("button" as never).map((n) => n.props.label);

async function render(element: React.ReactElement) {
  let tree: ReturnType<typeof create>;
  await act(async () => {
    tree = create(element);
  });
  return tree!;
}

it("shows nothing on a phone enrolled anywhere but the demo server", async () => {
  expect((await render(<DemoPanel server="https://digitva.causeofdeathindia.com" />)).toJSON()).toBeNull();
  expect((await render(<DemoPanel server={undefined} />)).toJSON()).toBeNull();
});

it("shows the badge and opens the dashboard and My reports in the system browser", async () => {
  const tree = await render(<DemoPanel server={DEMO_SERVER} />);
  expect(tree.root.findAllByType("text" as never).map((n) => n.props.children)).toContain("demoBadge");
  const open = (label: string) => tree.root.findAll((n) => n.props.label === label)[0].props.onPress();
  await act(async () => open("demoLinkDashboard"));
  await act(async () => open("demoLinkReports"));
  expect(mockOpenUrl.mock.calls.map(([url]) => url)).toEqual([
    `${DEMO_SERVER}/public-demo/dashboard`,
    `${DEMO_SERVER}/public-demo/cases`,
  ]);
});

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
    expect(labels(tree!)).not.toContain("enrolSubmit"); // the paste box is debug only
    await act(async () => tree!.root.findAll((n) => n.props.label === "demoTryTitle")[0].props.onPress());
    expect(mockRouter.push).toHaveBeenCalledWith("/demo");
  } finally {
    (globalThis as { __DEV__?: boolean }).__DEV__ = previous;
  }
});
