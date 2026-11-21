import React from "react";
import { act, create } from "react-test-renderer";

import en from "../src/strings/en.json";
import hi from "../src/strings/hi.json";

jest.mock("../src/workspace/certificatePdf", () => ({ sharePdf: jest.fn(async () => undefined) }));
jest.mock("../src/ui", () => ({
  Button: ({ label, onPress, disabled }: { label: string; onPress: () => void; disabled?: boolean }) => <button data-label={label} disabled={disabled} onClick={onPress} />,
  errorText: () => "error",
  useUiStyles: () => ({ muted: {} }),
}));

import { Platform } from "react-native";
import { ApiError } from "../src/api";
import { CertificateButton } from "../src/workspace/CertificateButton";
import { sharePdf } from "../src/workspace/certificatePdf";

const workspace = (available: boolean | undefined) =>
  ({ case: { va_sid: "uuid:a b", certificate_available: available } }) as never;

const CERT = { part1: [], part2: [], project_name: "P", underlying_cause: "TB", outcome: "not reviewed" };
const apiWith = (getCertificate: jest.Mock) => ({ getCertificate }) as never;

function render(available: boolean | undefined, api?: never) {
  let tree: ReturnType<typeof create>;
  act(() => { tree = create(<CertificateButton workspace={workspace(available)} api={api} />); });
  return tree!;
}

describe("CertificateButton", () => {
  const original = Platform.OS;
  afterEach(() => { Platform.OS = original; });

  it("shows only for a coded organization case on the web", () => {
    Platform.OS = "web";
    expect(render(true).root.findAllByType("button" as never)).toHaveLength(1);
    expect(render(false).toJSON()).toBeNull();
    expect(render(undefined).toJSON()).toBeNull();
    Platform.OS = "android";
    expect(render(true).toJSON()).toBeNull(); // no api to ask
  });

  it("native: not rendered when the case has no certificate", () => {
    Platform.OS = "android";
    expect(render(false, apiWith(jest.fn())).toJSON()).toBeNull();
    expect(render(undefined, apiWith(jest.fn())).toJSON()).toBeNull();
  });

  it("native: fetches the data, prints and shares a PDF", async () => {
    Platform.OS = "android";
    const getCertificate = jest.fn(async () => CERT);
    const tree = render(true, apiWith(getCertificate));
    await act(async () => { await tree.root.findByType("button" as never).props.onClick(); });
    expect(getCertificate).toHaveBeenCalledWith("uuid:a b");
    expect(sharePdf).toHaveBeenCalledWith(expect.stringContaining("Underlying cause of death"), expect.stringMatching(/^COD-form-/));
  });

  it("native: without a network it says to connect; a 404 says unavailable", async () => {
    Platform.OS = "android";
    const getCertificate = jest.fn().mockRejectedValueOnce(new TypeError("Network request failed")).mockRejectedValueOnce(new ApiError(404, "not_found"));
    const tree = render(true, apiWith(getCertificate));
    const press = async () => { await act(async () => { await tree.root.findByType("button" as never).props.onClick(); }); };
    await press();
    expect(JSON.stringify(tree.toJSON())).toContain(en.certificateConnect);
    await press();
    expect(JSON.stringify(tree.toJSON())).toContain(en.certificateUnavailable);
  });

  it("opens the certificate page in a new tab", () => {
    Platform.OS = "web";
    const open = jest.fn();
    (global as unknown as { window: unknown }).window = { open };
    const tree = render(true);
    act(() => { tree.root.findByType("button" as never).props.onClick(); });
    expect(open).toHaveBeenCalledWith("/coding/area/uuid%3Aa%20b/certificate", "_blank", "noopener");
  });

  it("has English and Hindi labels", () => {
    expect(en.certificateButton).toBe("COD form (PDF)");
    for (const key of ["certificateButton", "certificateConnect", "certificateUnavailable"] as const) expect(hi[key]).toBeTruthy();
  });
});
