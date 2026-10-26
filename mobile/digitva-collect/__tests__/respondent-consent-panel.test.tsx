import React from "react";
import { act, create } from "react-test-renderer";

jest.mock("../src/i18n", () => ({ t: (key: string) => key }));
jest.mock("../src/ui", () => ({
  Button: (props: { label: string; onPress: () => void; disabled?: boolean }) => jest.requireActual("react").createElement("mock-button", props),
  useUiStyles: () => ({}),
}));

import { computeUtf8Sha256HexSync, type ProjectConsentConfig } from "../src/consent";
import { RespondentConsentPanel } from "../src/web/StationConsentPanel";

const notice = (language: string, text: string) => ({
  notice_version_id: `nv-${language}`, version: 1, language, text, text_sha256: computeUtf8Sha256HexSync(text),
  purposes: [
    { code: "record", label: "Record", required: true },
    { code: "messages", label: "Messages", required: false },
  ],
  covered_fields: ["informant_name"], allowed_modes: ["spoken", "tap"] as ("spoken" | "tap")[], witness_allowed: false,
});
const config = {
  project_id: "P", consent_required: true,
  notice_versions: [notice("en", "English notice"), notice("hi", "हिंदी सूचना")],
} as unknown as ProjectConsentConfig;

function button(tree: ReturnType<typeof create>, label: string) {
  return tree.root.findAll((node) => (node.type as unknown) === "mock-button" && (String(node.props.label).includes(label) || node.props.accessibilityLabel === label))[0];
}

function checkbox(tree: ReturnType<typeof create>, label: string) {
  return tree.root.findAll((node) => node.props.accessibilityRole === "checkbox" && String(node.props.accessibilityLabel).includes(label))[0];
}

it("shows the notice in the chosen language and records agreement only with every required purpose", async () => {
  const onDecision = jest.fn();
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<RespondentConsentPanel config={config} language="hi" clientDraftId={null} onDecision={onDecision} />); });
  expect(JSON.stringify(tree.toJSON())).toContain("हिंदी सूचना");
  expect(button(tree, "consentAgree").props.disabled).toBe(true);
  await act(async () => checkbox(tree, "Record").props.onPress());
  await act(async () => button(tree, "consentModeTap").props.onPress());
  await act(async () => button(tree, "consentAgree").props.onPress());
  expect(onDecision).toHaveBeenCalledWith(expect.objectContaining({
    client_draft_id: null, notice_version_id: "nv-hi", notice_language: "hi",
    notice_sha256: computeUtf8Sha256HexSync("हिंदी सूचना"), decision: "granted", mode: "tap", witness_present: false,
    purposes: [{ code: "messages", granted: false }, { code: "record", granted: true }],
  }));
  // Another language starts its own choices.
  await act(async () => button(tree, "en").props.onPress());
  expect(JSON.stringify(tree.toJSON())).toContain("English notice");
  expect(button(tree, "consentAgree").props.disabled).toBe(true);
  // Select all toggles all purposes on, Clear all toggles them off.
  await act(async () => button(tree, "consentSelectAll").props.onPress());
  expect(button(tree, "consentAgree").props.disabled).toBe(false);
  await act(async () => button(tree, "consentClearAll").props.onPress());
  expect(button(tree, "consentAgree").props.disabled).toBe(true);
});

it("records a refusal with every purpose refused", async () => {
  const onDecision = jest.fn();
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<RespondentConsentPanel config={config} language="en" clientDraftId="d-1" onDecision={onDecision} />); });
  await act(async () => checkbox(tree, "Messages").props.onPress());
  await act(async () => button(tree, "consentRefuse").props.onPress());
  expect(onDecision).toHaveBeenCalledWith(expect.objectContaining({
    client_draft_id: "d-1", decision: "refused", mode: "spoken",
    purposes: [{ code: "messages", granted: false }, { code: "record", granted: false }],
  }));
});

it("refuses to capture without a usable notice", async () => {
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<RespondentConsentPanel config={{ ...config, notice_versions: [] }} language="en" clientDraftId={null} onDecision={jest.fn()} />); });
  expect(tree.root.findByProps({ testID: "respondent-consent-no-notice" })).toBeDefined();
});
