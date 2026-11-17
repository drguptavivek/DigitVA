/** The phone's full-screen image viewer (src/workspace/media/ImageViewer.native.tsx) opened from inline images. */
import React from "react";
import { Image, Modal, Text } from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

const mockGetSource = jest.fn();
const mockDownload = jest.fn();
const mockRemove = jest.fn();
const mockPlayer = { play: jest.fn(), pause: jest.fn(), replace: jest.fn() };
jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));
jest.mock("expo-audio", () => ({ useAudioPlayer: () => mockPlayer, useAudioPlayerStatus: () => ({ playing: false, error: null }) }));
jest.mock("../src/auth", () => ({ getAuthenticatedAttachmentSource: (...args: unknown[]) => mockGetSource(...args) }));
jest.mock("expo-file-system", () => ({ File: { downloadFileAsync: (...args: unknown[]) => mockDownload(...args) } }));
jest.mock("../src/standalone/shareFile", () => ({ cacheFile: (name: string) => ({ uri: `file:///cache/${name}`, name }), shareAndDelete: jest.fn() }));
jest.mock("../src/mediaFiles", () => ({ removeFile: (...args: unknown[]) => mockRemove(...args) }));

import { CategoryPanel } from "../src/workspace/CategoryPanel";
import { AttachmentMedia } from "../src/workspace/media/AttachmentMedia.native";

const identity = { vaSid: "case-1", mode: "coding" as const };
const a = "/api/v1/attachments/0123456789abcdef0123456789abcdef.jpg";
const b = "/api/v1/attachments/abcdef0123456789abcdef0123456789.png";
const audio = "/api/v1/attachments/11111111111111111111111111111111.mp3";
const category = {
  code: "attachments", label: "Attachments", render_mode: "default", summary_items: [],
  subcategories: [
    { code: "n", label: "Narration", render_mode: "media_gallery", items: [{ label: "Narration image", value: a, flip: false, info: false }] },
    { code: "d", label: "Docs", render_mode: "default", items: [
      { label: "Medical document", value: b, flip: false, info: false },
      { label: "Narration audio", value: audio, flip: false, info: false },
    ] },
  ],
} as never;

const renderMedia = (path: string, renderImage?: (uri: string) => React.ReactNode) =>
  <AttachmentMedia identity={identity} attachmentPath={path} userId="u1" renderImage={renderImage} />;

async function settle() {
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
}
const byLabel = (tree: ReactTestRenderer, label: string) =>
  tree.root.find((node) => node.props.accessibilityLabel === label && typeof node.props.onPress === "function");
const press = async (tree: ReactTestRenderer, label: string) => { await act(async () => byLabel(tree, label).props.onPress()); await settle(); };
const texts = (tree: ReactTestRenderer) => tree.root.findAllByType(Text).map((node) => [node.props.children].flat().join(""));
const inlineImages = (tree: ReactTestRenderer) => tree.root.findAll((node) => typeof node.props.onPress === "function" && node.props.accessibilityLabel === "Open image full screen" && node.parent?.props.accessibilityLabel !== "Open image full screen");
const viewerImage = (tree: ReactTestRenderer) => tree.root.findByProps({ testID: "image-viewer-image" });
const rotation = (tree: ReactTestRenderer) => viewerImage(tree).props.style[1].transform[0].rotate;
// Cleared before each test, so the viewer's first shared value (scale) is entry 0.
const mockShared = (jest.requireMock("react-native-reanimated") as { __sharedValues: { value: number }[] }).__sharedValues;
const scale = () => mockShared[0].value;

let tree: ReactTestRenderer;
beforeEach(async () => {
  jest.clearAllMocks();
  mockGetSource.mockImplementation(async (_user: string, path: string) => ({ uri: `https://x.example${path}`, headers: {} }));
  mockDownload.mockResolvedValue(undefined);
  mockShared.length = 0;
  await act(async () => { tree = create(<CategoryPanel category={category} renderMedia={renderMedia} />); });
  await settle();
});
afterEach(async () => { await act(async () => tree.unmount()); });

it("opens at the tapped image and walks the page's images in order, wrapping", async () => {
  expect(tree.root.findAllByType(Modal)).toHaveLength(0);
  await act(async () => inlineImages(tree)[1].props.onPress());
  await settle();
  expect(texts(tree)).toContain("Medical document  2 / 2");
  await press(tree, "Next attachment");
  expect(texts(tree)).toContain("Narration image  1 / 2");
  await press(tree, "Previous attachment");
  expect(texts(tree)).toContain("Medical document  2 / 2");
});

it("rotates in 90 degree steps and resets on moving to another image", async () => {
  await act(async () => inlineImages(tree)[0].props.onPress());
  await settle();
  expect(rotation(tree)).toBe("0deg");
  await press(tree, "Rotate right");
  await press(tree, "Rotate right");
  expect(rotation(tree)).toBe("180deg");
  await press(tree, "Rotate left");
  expect(rotation(tree)).toBe("90deg");
  await press(tree, "Next attachment");
  expect(rotation(tree)).toBe("0deg");
});

it("zooms within 1x-5x and resets", async () => {
  await act(async () => inlineImages(tree)[0].props.onPress());
  await settle();
  expect(scale()).toBe(1);
  await press(tree, "Zoom in");
  expect(scale()).toBeCloseTo(1.5);
  for (let i = 0; i < 10; i += 1) await press(tree, "Zoom in");
  expect(scale()).toBe(5);
  await press(tree, "Reset view");
  expect(scale()).toBe(1);
  await press(tree, "Zoom out");
  expect(scale()).toBe(1);
});

it("closes from Close and from the Android back button, and deletes its cached file", async () => {
  await act(async () => inlineImages(tree)[0].props.onPress());
  await settle();
  const inline = mockDownload.mock.calls.length;
  expect(inline).toBeGreaterThan(2);
  mockRemove.mockClear();
  await act(async () => tree.root.findByType(Modal).props.onRequestClose());
  expect(tree.root.findAllByType(Modal)).toHaveLength(0);
  expect(mockRemove).toHaveBeenCalledWith(expect.stringContaining("file:///cache/attachment-img-"));
  await act(async () => inlineImages(tree)[0].props.onPress());
  await settle();
  await press(tree, "Close full screen");
  expect(tree.root.findAllByType(Modal)).toHaveLength(0);
  expect(tree.root.findAllByType(Image).length).toBeGreaterThan(0);
});

it("does not open the viewer for audio, and lists only images", async () => {
  expect(tree.root.findAllByProps({ accessibilityLabel: "Play attached audio" }).length).toBeGreaterThan(0);
  expect(inlineImages(tree)).toHaveLength(2);
});
