import React from "react";
import { act, create } from "react-test-renderer";

import en from "../src/strings/en.json";
import hi from "../src/strings/hi.json";

jest.mock("../src/ui", () => ({
  Button: ({ label, onPress }: { label: string; onPress: () => void }) => <button data-label={label} onClick={onPress} />,
}));

import { Platform } from "react-native";
import { CertificateButton } from "../src/workspace/CertificateButton";

const workspace = (available: boolean | undefined) =>
  ({ case: { va_sid: "uuid:a b", certificate_available: available } }) as never;

function render(available: boolean | undefined) {
  let tree: ReturnType<typeof create>;
  act(() => { tree = create(<CertificateButton workspace={workspace(available)} />); });
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
    expect(render(true).toJSON()).toBeNull();
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
    expect(en.certificateButton).toBe("Certificate (PDF)");
    expect(hi.certificateButton).toBeTruthy();
  });
});
