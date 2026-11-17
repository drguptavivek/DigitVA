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
import { clampOffset, displayedSize, focalZoom } from "../src/workspace/media/ImageViewer.native";
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
  expect(tree.root.findAllByProps({ accessibilityLabel: "Attached audio" }).length).toBeGreaterThan(0);
  expect(inlineImages(tree)).toHaveLength(2);
});

it("focal zoom keeps the point under the fingers fixed", () => {
  const { x, y } = focalZoom(1, 0, 0, 2.5, 100, -40);
  // content point under the focal before and after: (f - t) / s
  expect((100 - x) / 2.5).toBeCloseTo(100);
  expect((-40 - y) / 2.5).toBeCloseTo(-40);
  const again = focalZoom(2, 30, -10, 4, 50, 20);
  expect((50 - again.x) / 4).toBeCloseTo((50 - 30) / 2);
  expect((20 - again.y) / 4).toBeCloseTo((20 + 10) / 2);
  expect(focalZoom(1, 0, 0, 2, 0, 0)).toEqual({ x: 0, y: 0 });
});

it("clamps the offset to the displayed image: centred when small, limited when large", () => {
  expect(clampOffset(50, 1, 300, 400)).toBeCloseTo(0);
  expect(clampOffset(50, 1.2, 300, 400)).toBeCloseTo(0);
  expect(clampOffset(500, 2, 300, 400)).toBeCloseTo(100);
  expect(clampOffset(-500, 2, 300, 400)).toBeCloseTo(-100);
  expect(clampOffset(30, 2, 300, 400)).toBe(30);
});

it("swaps the displayed width and height at 90 and 270 degrees", () => {
  // 200x100 image in a 400x800 stage: fit 2x -> 400x200, rotated 200x400.
  expect(displayedSize(200, 100, 400, 800, 0)).toEqual({ w: 400, h: 200 });
  expect(displayedSize(200, 100, 400, 800, 90)).toEqual({ w: 200, h: 400 });
  expect(displayedSize(200, 100, 400, 800, 270)).toEqual({ w: 200, h: 400 });
  expect(displayedSize(200, 100, 400, 800, 180)).toEqual({ w: 400, h: 200 });
  const rotated = displayedSize(200, 100, 400, 800, 90);
  expect(clampOffset(999, 2, rotated.h, 800)).toBeCloseTo(0);
  expect(clampOffset(999, 2, rotated.w, 400)).toBeCloseTo(0);
  expect(clampOffset(999, 4, rotated.h, 800)).toBeCloseTo(400);
});
