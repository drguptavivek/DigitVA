import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

const mockLoad = jest.fn<Promise<{ en: string; hi: string }>, []>();
const mockSave = jest.fn<Promise<void>, [{ en: string; hi: string }]>();
jest.mock("../src/standalone/noticeSettings", () => ({
  defaultStandaloneNoticeSettings: () => ({ en: "Default English", hi: "डिफ़ॉल्ट हिंदी" }),
  loadStandaloneNoticeSettings: () => mockLoad(),
  MAX_STANDALONE_NOTICE_LENGTH: 20_000,
  saveStandaloneNoticeSettings: (notices: { en: string; hi: string }) => mockSave(notices),
  STANDALONE_NOTICE_LANGUAGES: ["en", "hi"],
  validStandaloneNoticeText: (text: string) => text.trim().length > 0 && text.length <= 20_000,
}));
jest.mock("../src/i18n", () => ({ t: (key: string) => key }));
jest.mock("../src/ui", () => {
  const R = jest.requireActual("react") as typeof React;
  return {
    Button: (props: Record<string, unknown> & { label: string }) => R.createElement("button", props, props.label),
    useUiStyles: () => ({ input: {}, text: {}, muted: {}, error: {} }),
  };
});
import StandaloneConsentNoticeSettings from "../src/standalone/StandaloneConsentNoticeSettings";

async function render(): Promise<ReactTestRenderer> {
  let tree!: ReactTestRenderer;
  await act(async () => { tree = create(<StandaloneConsentNoticeSettings />); });
  return tree;
}

beforeEach(() => {
  mockLoad.mockReset().mockResolvedValue({ en: "Saved English", hi: "सहेजी हिंदी" });
  mockSave.mockReset().mockResolvedValue(undefined);
});

it("loads both editable notices and saves asynchronously with success feedback", async () => {
  const tree = await render();
  const english = tree.root.findByProps({ testID: "standalone-consent-notice-en" });
  const hindi = tree.root.findByProps({ testID: "standalone-consent-notice-hi" });
  expect(english.props.value).toBe("Saved English");
  expect(hindi.props.value).toBe("सहेजी हिंदी");
  expect(english.props.maxLength).toBe(20_000);

  await act(async () => english.props.onChangeText("Edited English"));
  const save = tree.root.findByProps({ label: "standaloneConsentNoticeSave" });
  await act(async () => { await save.props.onPress(); });
  expect(mockSave).toHaveBeenCalledWith({ en: "Edited English", hi: "सहेजी हिंदी" });
  expect(tree.root.findAll((node) => node.props.children === "standaloneConsentNoticeSaved").length).toBeGreaterThan(0);
});

it("shows save failure and blocks saving blank notice text", async () => {
  mockSave.mockRejectedValueOnce(new Error("storage failed"));
  const tree = await render();
  const english = tree.root.findByProps({ testID: "standalone-consent-notice-en" });
  await act(async () => english.props.onChangeText("   "));
  const save = tree.root.findByProps({ label: "standaloneConsentNoticeSave" });
  expect(save.props.disabled).toBe(true);
  expect(tree.root.findAll((node) => node.props.children === "standaloneConsentNoticeInvalid").length).toBeGreaterThan(0);

  await act(async () => english.props.onChangeText("Valid updated text"));
  await act(async () => { await save.props.onPress(); });
  expect(tree.root.findAll((node) => node.props.children === "standaloneConsentNoticeSaveError").length).toBeGreaterThan(0);
});

it("fails closed when local settings cannot be read", async () => {
  mockLoad.mockRejectedValueOnce(new Error("storage unavailable"));
  const tree = await render();
  expect(tree.root.findAll((node) => node.props.children === "standaloneConsentNoticeLoadError").length).toBeGreaterThan(0);
  expect(tree.root.findAll((node) => node.props.testID === "standalone-consent-notice-en")).toHaveLength(0);
});
