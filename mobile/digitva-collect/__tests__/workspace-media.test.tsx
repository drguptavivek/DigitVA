import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

const mockGetSource = jest.fn();
const mockPlayer = { play: jest.fn(), pause: jest.fn(), replace: jest.fn(), seekTo: jest.fn() };
const mockStatus = { playing: false, error: null };
jest.mock("expo-audio", () => ({
  useAudioPlayer: () => mockPlayer,
  useAudioPlayerStatus: () => mockStatus,
}));
jest.mock("../src/auth", () => ({ getAuthenticatedAttachmentSource: (...args: unknown[]) => mockGetSource(...args) }));

import { AttachmentMedia as NativeAttachmentMedia } from "../src/workspace/media/AttachmentMedia.native";
import { AttachmentMedia as WebAttachmentMedia } from "../src/workspace/media/AttachmentMedia.web";
import { attachmentMediaKind } from "../src/workspace/media/path";

const identity = { vaSid: "case-1", mode: "view" as const };
const imagePath = "/api/v1/attachments/0123456789abcdef0123456789abcdef.jpg";
const audioPath = "/api/v1/attachments/0123456789abcdef0123456789abcdef.mp3";
const source = { uri: `https://digitva.example${imagePath}`, headers: { Authorization: "Bearer memory-only" } };

async function flush() {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

beforeEach(() => {
  mockGetSource.mockReset();
  mockPlayer.play.mockClear();
  mockPlayer.pause.mockClear();
  mockPlayer.replace.mockClear();
});

it("accepts only supported root-relative attachment paths and safely decodes filenames", () => {
  expect(attachmentMediaKind(imagePath)).toBe("image");
  expect(attachmentMediaKind("/api/v1/attachments/legacy/form_1/%E0%A4%A4%20image.png")).toBe("image");
  expect(attachmentMediaKind(audioPath)).toBe("audio");
  for (const path of [
    "//outside.invalid/api/v1/attachments/file.jpg",
    "https://outside.invalid/api/v1/attachments/file.jpg",
    "/api/v1/attachments/legacy/form/%2e%2e%2fsecret.jpg",
    "/api/v1/attachments/legacy/form/file%2Fname.jpg",
    "/api/v1/attachments/legacy/form/file.jpg?download=1",
    "/api/v1/attachments/not-an-opaque-name.jpg",
  ]) expect(attachmentMediaKind(path)).toBeNull();
});

it("passes authenticated headers to the native audio player and exposes accessible controls", async () => {
  mockGetSource.mockResolvedValue({ uri: `https://digitva.example${audioPath}`, headers: source.headers });
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<NativeAttachmentMedia identity={identity} attachmentPath={audioPath} userId="user-1" />);
    await flush();
  });

  expect(mockGetSource).toHaveBeenCalledWith("user-1", audioPath);
  expect(mockPlayer.replace).toHaveBeenCalledWith({ uri: `https://digitva.example${audioPath}`, headers: source.headers });
  const button = tree.root.findByProps({ accessibilityLabel: "Play attached audio" });
  await act(async () => button.props.onPress());
  expect(mockPlayer.play).toHaveBeenCalledTimes(1);
  await act(async () => tree.unmount());
  expect(mockPlayer.pause).toHaveBeenCalled();
  expect(mockPlayer.replace).toHaveBeenLastCalledWith(null);
});

it("ignores a native source that resolves after its workspace identity changes", async () => {
  let resolveOld!: (value: typeof source) => void;
  const newSource = { uri: "https://digitva.example/new.jpg", headers: source.headers };
  mockGetSource
    .mockReturnValueOnce(new Promise((resolve) => { resolveOld = resolve; }))
    .mockResolvedValueOnce(newSource);
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<NativeAttachmentMedia identity={identity} attachmentPath={audioPath} userId="user-1" />);
    await flush();
  });
  await act(async () => {
    tree.update(<NativeAttachmentMedia identity={{ ...identity, vaSid: "case-2" }} attachmentPath={audioPath} userId="user-1" />);
    await flush();
  });
  await act(async () => {
    resolveOld(source);
    await flush();
  });

  expect(mockPlayer.replace).toHaveBeenCalledWith(newSource);
  expect(mockPlayer.replace).not.toHaveBeenCalledWith(source);
  await act(async () => tree.unmount());
});

it("uses the browser cookie session for validated same-origin media URLs", async () => {
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<WebAttachmentMedia identity={identity} attachmentPath={imagePath} />);
    await flush();
  });
  expect(tree.root.findByType("img").props.src).toBe(imagePath);
  await act(async () => tree.unmount());
});
