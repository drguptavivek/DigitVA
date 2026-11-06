import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

const mockGetSource = jest.fn();
const mockDownload = jest.fn();
const mockShare = jest.fn();
const mockRemove = jest.fn();
const mockPlayer = { play: jest.fn(), pause: jest.fn(), replace: jest.fn(), seekTo: jest.fn() };
jest.mock("expo-audio", () => ({
  useAudioPlayer: () => mockPlayer,
  useAudioPlayerStatus: () => ({ playing: false, error: null }),
}));
jest.mock("../src/auth", () => ({ getAuthenticatedAttachmentSource: (...args: unknown[]) => mockGetSource(...args) }));
jest.mock("expo-file-system", () => ({ File: { downloadFileAsync: (...args: unknown[]) => mockDownload(...args) } }));
jest.mock("../src/standalone/shareFile", () => ({
  cacheFile: (name: string) => ({ uri: `file:///cache/${name}`, name }),
  shareAndDelete: (...args: unknown[]) => mockShare(...args),
}));
jest.mock("../src/mediaFiles", () => ({ removeFile: (...args: unknown[]) => mockRemove(...args) }));

import { AttachmentMedia } from "../src/workspace/media/AttachmentMedia.native";

const identity = { vaSid: "case-1", mode: "coding" as const };
const pdfPath = "/api/v1/attachments/0123456789abcdef0123456789abcdef.pdf";
const source = { uri: `https://digitva.example${pdfPath}`, headers: { Authorization: "Bearer memory-only" } };

/** Let the open handler's awaited steps (source, download, share) settle inside act. */
async function settle() {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

beforeEach(() => {
  mockGetSource.mockReset();
  mockDownload.mockReset();
  mockShare.mockReset();
  mockRemove.mockReset();
});

it("renders an Open action for a PDF and shares the authenticated download", async () => {
  mockGetSource.mockResolvedValue(source);
  mockDownload.mockResolvedValue(undefined);
  mockShare.mockResolvedValue(undefined);
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<AttachmentMedia identity={identity} attachmentPath={pdfPath} userId="user-1" />);
  });
  expect(JSON.stringify(tree.toJSON())).not.toContain("Attachment unavailable.");

  const button = tree.root.findByProps({ accessibilityLabel: "Open attached PDF" });
  await act(async () => {
    button.props.onPress();
    await settle();
  });

  expect(mockGetSource).toHaveBeenCalledWith("user-1", pdfPath);
  const [downloadUrl, target, options] = mockDownload.mock.calls[0];
  expect(downloadUrl).toBe(source.uri);
  expect(target.name).toMatch(/^attachment-\d+-0123456789abcdef0123456789abcdef\.pdf$/);
  expect(options).toEqual({ headers: source.headers });
  expect(mockShare).toHaveBeenCalledWith(target, "application/pdf");
  await act(async () => tree.unmount());
});

it("shows the unavailable message when the PDF cannot be fetched", async () => {
  mockGetSource.mockRejectedValue(new Error("network"));
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<AttachmentMedia identity={identity} attachmentPath={pdfPath} userId="user-1" />);
  });
  const button = tree.root.findByProps({ accessibilityLabel: "Open attached PDF" });
  await act(async () => {
    button.props.onPress();
    await settle();
  });

  expect(mockShare).not.toHaveBeenCalled();
  expect(tree.root.findByProps({ accessibilityRole: "alert" }).props.children).toBe("Attachment unavailable.");
  await act(async () => tree.unmount());
});

it("lets a failed PDF download be retried on the next tap", async () => {
  mockGetSource.mockResolvedValue(source);
  mockDownload.mockRejectedValueOnce(new Error("network")).mockResolvedValue(undefined);
  mockShare.mockResolvedValue(undefined);
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<AttachmentMedia identity={identity} attachmentPath={pdfPath} userId="user-1" />);
  });
  await act(async () => {
    tree.root.findByProps({ accessibilityLabel: "Open attached PDF" }).props.onPress();
    await settle();
  });
  expect(JSON.stringify(tree.toJSON())).toContain("Attachment unavailable.");
  await act(async () => {
    tree.root.findByProps({ accessibilityLabel: "Open attached PDF" }).props.onPress();
    await settle();
  });
  expect(JSON.stringify(tree.toJSON())).not.toContain("Attachment unavailable.");
  expect(mockShare).toHaveBeenCalledTimes(1);
});
