/** Try the demo screen: sign-up and enrolment flow with a mocked API. */
import React from "react";
import { act, create, type ReactTestInstance } from "react-test-renderer";

const mockRouter = { replace: jest.fn(), push: jest.fn(), back: jest.fn() };
const mockReload = jest.fn(async () => undefined);
const mockSignUp = jest.fn<Promise<void>, [string, string, unknown]>();
const mockEnrol = jest.fn<Promise<{ user_id: string; name: string }>, [string, string, unknown]>();

jest.mock("react-native", () => ({ Platform: { OS: "android" }, Pressable: "pressable", Text: "text", TextInput: "textinput", View: "view" }));
jest.mock("expo-router", () => ({ useRouter: () => mockRouter }));
jest.mock("../src/AppState", () => ({ useAppState: () => ({ reload: mockReload }) }));
jest.mock("../src/i18n", () => ({ t: (key: string, vars?: Record<string, unknown>) => (vars ? `${key}:${JSON.stringify(vars)}` : key) }));
jest.mock("../src/ui", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return {
    Button: (props: { label: string }) => ReactActual.createElement("button", props),
    Screen: ({ children }: { children: React.ReactNode }) => ReactActual.createElement("screen", null, children),
    errorText: () => "generic",
    useUiStyles: () => ({ text: {}, muted: {}, error: {}, input: {}, card: {} }),
  };
});
jest.mock("../src/demo", () => {
  return {
    signUpDemoAccount: (name: string, password: string, options: unknown) => mockSignUp(name, password, options),
    enrolAndSignInDemo: (name: string, password: string, onProgress: unknown) => mockEnrol(name, password, onProgress),
    demoErrorText: (error: { code?: string }) => `error:${error.code}`,
  };
});

import { ApiError } from "../src/api";
import Demo from "../src/nativeRoutes/demo";

const GOOD = "a-long-demo-password";

async function render() {
  let tree: ReturnType<typeof create>;
  await act(async () => {
    tree = create(<Demo />);
  });
  return tree!;
}

const button = (tree: ReturnType<typeof create>, label: string): ReactTestInstance =>
  tree.root.findAll((node) => node.type === ("button" as never) && node.props.label === label)[0];
const input = (tree: ReturnType<typeof create>, label: string) =>
  tree.root.findAll((node) => node.type === ("textinput" as never) && node.props.accessibilityLabel === label)[0];
const texts = (tree: ReturnType<typeof create>) =>
  tree.root.findAllByType("text" as never).map((node) => String(node.props.children));
async function press(node: ReactTestInstance) {
  await act(async () => node.props.onPress());
}
async function type(tree: ReturnType<typeof create>, label: string, value: string) {
  await act(async () => input(tree, label).props.onChangeText(value));
}
async function fillCreate(tree: ReturnType<typeof create>, { accept = true } = {}) {
  await press(button(tree, "demoCreateAccount"));
  await type(tree, "demoUsername", "Demo.User");
  await type(tree, "password", GOOD);
  await type(tree, "demoConfirmPassword", GOOD);
  if (accept) await act(async () => tree.root.findByProps({ accessibilityRole: "checkbox" }).props.onPress());
}

beforeEach(() => {
  jest.clearAllMocks();
  mockSignUp.mockResolvedValue(undefined);
  mockEnrol.mockResolvedValue({ user_id: "u1", name: "demo.user" });
});

it("shows the policy notice and the two ways in", async () => {
  const tree = await render();
  expect(texts(tree)).toContain("demoNotice");
  expect(button(tree, "demoCreateAccount")).toBeDefined();
  expect(button(tree, "demoHaveAccount")).toBeDefined();
});

it("will not create an account until the notice is accepted", async () => {
  const tree = await render();
  await fillCreate(tree, { accept: false });
  expect(button(tree, "demoSubmitCreate").props.disabled).toBe(true);
  await act(async () => tree.root.findByProps({ accessibilityRole: "checkbox" }).props.onPress());
  expect(button(tree, "demoSubmitCreate").props.disabled).toBe(false);
});

it("signs up, enrols, signs in and goes to unlock", async () => {
  const tree = await render();
  await fillCreate(tree);
  await press(button(tree, "demoSubmitCreate"));
  expect(mockSignUp).toHaveBeenCalledWith("demo.user", GOOD, expect.anything());
  expect(mockEnrol).toHaveBeenCalledWith("demo.user", GOOD, expect.any(Function));
  expect(mockReload).toHaveBeenCalled();
  expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/unlock", params: { userId: "u1", refresh: "1" } });
});

it("checks the fields before any request", async () => {
  const tree = await render();
  await fillCreate(tree);
  await type(tree, "demoConfirmPassword", "different-password-1");
  await press(button(tree, "demoSubmitCreate"));
  expect(texts(tree)).toContain("demoErrPasswordMatch");
  expect(mockSignUp).not.toHaveBeenCalled();
  await type(tree, "demoUsername", "admin");
  await type(tree, "demoConfirmPassword", GOOD);
  await press(button(tree, "demoTryAgain"));
  expect(texts(tree)).toContain("demoErrUsernameReserved");
  expect(mockSignUp).not.toHaveBeenCalled();
});

it("after a failed security check the user presses Try again, which asks for a new challenge once per press", async () => {
  mockSignUp.mockRejectedValueOnce(new ApiError(400, "captcha_failed"));
  const tree = await render();
  await fillCreate(tree);
  await press(button(tree, "demoSubmitCreate"));
  expect(texts(tree)).toContain("error:captcha_failed");
  expect(mockSignUp).toHaveBeenCalledTimes(1);
  expect(mockEnrol).not.toHaveBeenCalled();
  await press(button(tree, "demoTryAgain"));
  expect(mockSignUp).toHaveBeenCalledTimes(2);
  expect(mockEnrol).toHaveBeenCalledTimes(1);
});

it("does not sign the same account up twice when a later step failed", async () => {
  mockEnrol.mockRejectedValueOnce(new TypeError("Network request failed"));
  const tree = await render();
  await fillCreate(tree);
  await press(button(tree, "demoSubmitCreate"));
  await press(button(tree, "demoTryAgain"));
  expect(mockSignUp).toHaveBeenCalledTimes(1);
  expect(mockEnrol).toHaveBeenCalledTimes(2);
  expect(mockRouter.replace).toHaveBeenCalledTimes(1);
});

it.each([
  ["demo_limit", 429],
  ["cap_reached", 503],
])("shows %s and never runs a second attempt by itself", async (code, status) => {
  mockSignUp.mockRejectedValue(new ApiError(status, code));
  const tree = await render();
  await fillCreate(tree);
  await press(button(tree, "demoSubmitCreate"));
  expect(texts(tree)).toContain(`error:${code}`);
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 50));
  });
  expect(mockSignUp).toHaveBeenCalledTimes(1);
  expect(mockRouter.replace).not.toHaveBeenCalled();
});

it("treats a device limit as final: the submit button stays off", async () => {
  mockEnrol.mockRejectedValue(new ApiError(429, "demo_limit"));
  const tree = await render();
  await press(button(tree, "demoHaveAccount"));
  await type(tree, "demoUsername", "demo.user");
  await type(tree, "password", GOOD);
  await press(button(tree, "demoSubmitExisting"));
  expect(texts(tree)).toContain("error:demo_limit");
  expect(button(tree, "demoTryAgain").props.disabled).toBe(true);
  expect(mockSignUp).not.toHaveBeenCalled();
});

it("an existing account only enrols and signs in", async () => {
  const tree = await render();
  await press(button(tree, "demoHaveAccount"));
  await type(tree, "demoUsername", " Demo.User ");
  await type(tree, "password", GOOD);
  await press(button(tree, "demoSubmitExisting"));
  expect(mockSignUp).not.toHaveBeenCalled();
  expect(mockEnrol).toHaveBeenCalledWith("demo.user", GOOD, expect.any(Function));
  expect(mockRouter.replace).toHaveBeenCalled();
});
