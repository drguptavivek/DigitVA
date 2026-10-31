/**
 * Offline coding's attachment view (src/workspace/media/LocalAttachmentMedia.native.tsx): nothing is read until the
 * coder opens it; then the draft's reference is read from the encrypted store after the case's access check, shown
 * through a short-lived plain copy, and the copy is deleted when it is closed, another is opened, or the view goes.
 */
import React from "react";
import { Image } from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

let mockAudioProps: Record<string, unknown> | undefined;
jest.mock("../src/AttachmentAudioPlayer", () => ({ AttachmentAudioPlayer: (props: Record<string, unknown>) => { mockAudioProps = props; return null; } }));
const mockWriteCopy = jest.fn((id: string, ext: string, _bytes: Uint8Array) => `file:///cache/va-media/${id}.${ext}`);
const mockRemoveFile = jest.fn();
jest.mock("../src/mediaFiles", () => ({
  writePlaybackCopy: (id: string, ext: string, bytes: Uint8Array) => mockWriteCopy(id, ext, bytes),
  removeFile: (uri: string | undefined) => mockRemoveFile(uri),
}));
const mockMeta = jest.fn();
const mockBytes = jest.fn();
jest.mock("../src/attachmentStore", () => ({
  ...jest.requireActual("../src/attachmentStore"),
  getAttachmentMeta: (_db: unknown, id: string) => mockMeta(id),
  getAttachmentBytes: (_db: unknown, id: string) => mockBytes(id),
}));
jest.mock("../src/i18n", () => ({ t: (key: string) => key }));
jest.mock("../src/ui", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return {
    Button: ({ label, onPress }: { label: string; onPress: () => void }) => ReactActual.createElement("button", { accessibilityLabel: label, onPress }),
    useUiStyles: () => ({ muted: {}, error: {} }),
  };
});

import { LocalAttachmentMedia } from "../src/workspace/media/LocalAttachmentMedia.native";

const ID = "00000000-0000-4000-8000-000000000001";
const OTHER = "00000000-0000-4000-8000-000000000002";
const db = {} as never;
const meta = (kind: string, ext: string, id = ID, draftId = "draft-7") => ({ id, draft_id: draftId, kind, ext });
const allowed = async () => undefined;

async function render(element: React.ReactElement) {
  let root!: ReactTestRenderer;
  await act(async () => { root = create(element); });
  return root;
}
const press = async (root: ReactTestRenderer, label: string, index = 0) => {
  const buttons = root.root.findAll((node) => node.type === "button" && node.props.accessibilityLabel === label);
  expect(buttons.length).toBeGreaterThan(index);
  await act(async () => { buttons[index]!.props.onPress(); });
};
const text = (root: ReactTestRenderer) => JSON.stringify(root.toJSON());

beforeEach(() => {
  mockAudioProps = undefined;
  mockWriteCopy.mockClear();
  mockRemoveFile.mockClear();
  mockMeta.mockReset();
  mockBytes.mockReset().mockResolvedValue(new Uint8Array([1, 2, 3]));
});

it("reads nothing until opened, then plays a plain copy and deletes it when closed or gone", async () => {
  mockMeta.mockResolvedValue(meta("audio", "m4a"));
  const assertAllowed = jest.fn(allowed);
  const root = await render(<LocalAttachmentMedia db={db} draftId="draft-7" reference={`who-va-attachment:${ID}`} assertAllowed={assertAllowed} />);
  expect(text(root)).toContain("offlineAttachmentOpen");
  expect(assertAllowed).not.toHaveBeenCalled();
  expect(mockMeta).not.toHaveBeenCalled();
  await press(root, "offlineAttachmentOpen");
  expect(assertAllowed).toHaveBeenCalled();
  expect(mockWriteCopy).toHaveBeenCalledWith(ID, "m4a", new Uint8Array([1, 2, 3]));
  expect(mockAudioProps).toMatchObject({ uri: `file:///cache/va-media/${ID}.m4a`, accessibilityLabel: "offlineAttachedAudio" });
  await press(root, "offlineAttachmentClose");
  expect(mockRemoveFile).toHaveBeenCalledWith(`file:///cache/va-media/${ID}.m4a`);
  expect(text(root)).toContain("offlineAttachmentOpen");
  await press(root, "offlineAttachmentOpen");
  mockRemoveFile.mockClear();
  await act(async () => { root.unmount(); });
  expect(mockRemoveFile).toHaveBeenCalledWith(`file:///cache/va-media/${ID}.m4a`);
});

it("keeps one attachment open: opening another removes the first copy", async () => {
  mockMeta.mockImplementation(async (id: string) => meta(id === ID ? "audio" : "image", id === ID ? "m4a" : "jpg", id));
  const root = await render(<>
    <LocalAttachmentMedia db={db} draftId="draft-7" reference={`who-va-attachment:${ID}`} assertAllowed={allowed} />
    <LocalAttachmentMedia db={db} draftId="draft-7" reference={{ uri: `who-va-attachment:${OTHER}` }} assertAllowed={allowed} />
  </>);
  await press(root, "offlineAttachmentOpen", 0);
  expect(mockWriteCopy).toHaveBeenCalledTimes(1);
  await press(root, "offlineAttachmentOpen", 0); // the second view's button: the first now shows Close
  expect(mockRemoveFile).toHaveBeenCalledWith(`file:///cache/va-media/${ID}.m4a`);
  expect(root.root.findByType(Image).props.source).toEqual({ uri: `file:///cache/va-media/${OTHER}.jpg` });
  expect(root.root.findAll((node) => node.type === "button" && node.props.accessibilityLabel === "offlineAttachmentClose")).toHaveLength(1);
});

it("reads nothing when the case's access check fails, and says the attachment is unavailable", async () => {
  mockMeta.mockResolvedValue(meta("audio", "m4a"));
  const root = await render(<LocalAttachmentMedia db={db} draftId="draft-7" reference={`who-va-attachment:${ID}`} assertAllowed={async () => { throw new Error("offline_case_access_revoked"); }} />);
  await press(root, "offlineAttachmentOpen");
  expect(mockMeta).not.toHaveBeenCalled();
  expect(mockWriteCopy).not.toHaveBeenCalled();
  expect(text(root)).toContain("offlineAttachmentUnavailable");
});

it("shows no file stored for another draft", async () => {
  mockMeta.mockResolvedValue(meta("audio", "m4a", ID, "draft-8"));
  const root = await render(<LocalAttachmentMedia db={db} draftId="draft-7" reference={`who-va-attachment:${ID}`} assertAllowed={allowed} />);
  await press(root, "offlineAttachmentOpen");
  expect(mockMeta).toHaveBeenCalledWith(ID);
  expect(mockBytes).not.toHaveBeenCalled();
  expect(mockWriteCopy).not.toHaveBeenCalled();
  expect(text(root)).toContain("offlineAttachmentUnavailable");
});

it("says a file that is no longer stored is unavailable, and never copies a document", async () => {
  mockMeta.mockResolvedValue(null);
  const missing = await render(<LocalAttachmentMedia db={db} draftId="draft-7" reference={`who-va-attachment:${ID}`} assertAllowed={allowed} />);
  await press(missing, "offlineAttachmentOpen");
  expect(text(missing)).toContain("offlineAttachmentUnavailable");
  mockMeta.mockResolvedValue(meta("document", "pdf"));
  const document = await render(<LocalAttachmentMedia db={db} draftId="draft-7" reference={`who-va-attachment:${ID}`} assertAllowed={allowed} />);
  await press(document, "offlineAttachmentOpen");
  expect(text(document)).toContain("offlineAttachmentDocument");
  expect(mockBytes).not.toHaveBeenCalled();
  expect(mockWriteCopy).not.toHaveBeenCalled();
});
