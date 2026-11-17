import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

const mockGetSource = jest.fn();
const mockPlayer = { play: jest.fn(), pause: jest.fn(), replace: jest.fn(), seekTo: jest.fn() };
const mockStatus: Record<string, unknown> = { playing: false, error: null, currentTime: 0, duration: 0, didJustFinish: false };
const mockUseAudioPlayer = jest.fn((_source?: unknown) => mockPlayer);
jest.mock("expo-audio", () => ({
  useAudioPlayer: (source: unknown) => mockUseAudioPlayer(source),
  useAudioPlayerStatus: () => mockStatus,
}));
const mockDownload = jest.fn();
const mockRemove = jest.fn();
jest.mock("expo-file-system", () => ({ File: { downloadFileAsync: (...args: unknown[]) => mockDownload(...args) } }));
jest.mock("../src/standalone/shareFile", () => ({
  cacheFile: (name: string) => ({ uri: `file:///cache/${name}`, name }),
  shareAndDelete: jest.fn(),
}));
jest.mock("../src/mediaFiles", () => ({ removeFile: (...args: unknown[]) => mockRemove(...args) }));
jest.mock("../src/auth", () => ({ getAuthenticatedAttachmentSource: (...args: unknown[]) => mockGetSource(...args) }));

import { AttachmentMedia as NativeAttachmentMedia } from "../src/workspace/media/AttachmentMedia.native";
import { AttachmentMedia as WebAttachmentMedia } from "../src/workspace/media/AttachmentMedia.web";
import { AttachmentTrainingContext } from "../src/workspace/media/attachmentScope";
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
  mockDownload.mockReset();
  mockRemove.mockReset();
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

  expect(mockGetSource).toHaveBeenCalledWith("user-1", audioPath, undefined);
  // The shared player gets the bearer source; nothing ever calls replace (expo-audio rejects null on a device).
  expect(mockUseAudioPlayer).toHaveBeenLastCalledWith({ uri: `https://digitva.example${audioPath}`, headers: source.headers });
  expect(tree.root.findByProps({ accessibilityLabel: "Attached audio" })).toBeDefined();
  const play = tree.root.findAll((node) => node.props.accessibilityLabel === "Play" && typeof node.props.onPress === "function")[0];
  await act(async () => play.props.onPress());
  expect(mockPlayer.play).toHaveBeenCalledTimes(1);
  await act(async () => tree.unmount());
  expect(mockPlayer.replace).not.toHaveBeenCalled();
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

  expect(mockUseAudioPlayer).toHaveBeenLastCalledWith(newSource);
  expect(mockUseAudioPlayer).not.toHaveBeenCalledWith(source);
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

it("asks for training=1 on a training case's media, and not otherwise", async () => {
  mockGetSource.mockResolvedValue({ uri: `https://digitva.example${audioPath}`, headers: source.headers });
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<NativeAttachmentMedia identity={identity} attachmentPath={audioPath} userId="user-1" training />);
    await flush();
  });
  expect(mockGetSource).toHaveBeenCalledWith("user-1", audioPath, true);
  await act(async () => tree.unmount());

  for (const [training, expected] of [[true, `${imagePath}?training=1`], [false, imagePath]] as const) {
    await act(async () => {
      tree = create(
        <AttachmentTrainingContext.Provider value={training}>
          <WebAttachmentMedia identity={identity} attachmentPath={imagePath} />
        </AttachmentTrainingContext.Provider>,
      );
      await flush();
    });
    expect(tree.root.findByType("img").props.src).toBe(expected);
    await act(async () => tree.unmount());
  }
});

it("downloads an image with the bearer headers and renders it from a header-less cache file", async () => {
  mockGetSource.mockResolvedValue(source);
  mockDownload.mockResolvedValue(undefined);
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<NativeAttachmentMedia identity={identity} attachmentPath={imagePath} userId="user-1" />);
    await flush();
  });
  expect(mockDownload).toHaveBeenCalledWith(source.uri, expect.objectContaining({ uri: expect.stringMatching(/^file:\/\/\/cache\/attachment-img-.*\.jpg$/) }), { headers: source.headers });
  const image = tree.root.findByProps({ accessibilityLabel: "Attached image" });
  expect(image.props.source.uri).toMatch(/^file:\/\/\/cache\//);
  expect(image.props.source.headers).toBeUndefined();
  expect(mockRemove).not.toHaveBeenCalled();
  const cached = image.props.source.uri;
  await act(async () => tree.unmount());
  expect(mockRemove).toHaveBeenCalledWith(cached);
});

it("deletes and does not show an image that finishes downloading after the identity changed", async () => {
  let finishOld!: () => void;
  mockGetSource.mockResolvedValue(source);
  mockDownload
    .mockReturnValueOnce(new Promise<void>((resolve) => { finishOld = resolve; }))
    .mockResolvedValueOnce(undefined);
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<NativeAttachmentMedia identity={identity} attachmentPath={imagePath} userId="user-1" />);
    await flush();
  });
  const oldUri = mockDownload.mock.calls[0][1].uri;
  await act(async () => {
    tree.update(<NativeAttachmentMedia identity={{ ...identity, vaSid: "case-2" }} attachmentPath={imagePath} userId="user-1" />);
    await flush();
  });
  mockRemove.mockClear();
  await act(async () => {
    finishOld();
    await flush();
  });
  expect(mockRemove).toHaveBeenCalledWith(oldUri);
  const shown = tree.root.findByProps({ accessibilityLabel: "Attached image" }).props.source.uri;
  expect(shown).not.toBe(oldUri);
  await act(async () => tree.unmount());
});

it("seeks where the track is tapped and shows elapsed / total time", async () => {
  mockGetSource.mockResolvedValue({ uri: `https://digitva.example${audioPath}`, headers: source.headers });
  Object.assign(mockStatus, { currentTime: 30, duration: 120 });
  mockPlayer.seekTo.mockClear();
  let tree!: ReactTestRenderer;
  try {
    await act(async () => {
      tree = create(<NativeAttachmentMedia identity={identity} attachmentPath={audioPath} userId="user-1" />);
      await flush();
    });
    const track = tree.root.findByProps({ accessibilityRole: "adjustable" });
    expect(track.props.accessibilityValue).toEqual({ min: 0, max: 120, now: 30 });
    await act(async () => track.props.onLayout({ nativeEvent: { layout: { width: 200 } } }));
    await act(async () => tree.root.findByProps({ accessibilityRole: "adjustable" }).props.onPress({ nativeEvent: { locationX: 150 } }));
    expect(mockPlayer.seekTo).toHaveBeenCalledWith(90);
    const texts = tree.root.findAll((node) => typeof node.props.children !== "undefined").flatMap((node) => [node.props.children].flat()).filter((c) => typeof c === "string");
    expect(texts.join(" ")).toContain("00:30");
    await act(async () => tree.unmount());
  } finally {
    Object.assign(mockStatus, { currentTime: 0, duration: 0 });
  }
});
