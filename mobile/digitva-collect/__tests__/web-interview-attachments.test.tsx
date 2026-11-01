/**
 * The browser interview's attachment services over the Flask page's real buffer, uploader and platform modules
 * (app/static/js/intake): only the IndexedDB backing is swapped for memory, and the app's request helper for a mock.
 */
import React from "react";
import { act, create } from "react-test-renderer";

jest.mock("../src/i18n", () => ({ t: (key: string, vars: Record<string, unknown> = {}) => `${key}${Object.keys(vars).length ? JSON.stringify(vars) : ""}` }));
const mockRequestJson = jest.fn();
jest.mock("../src/api", () => ({ ...jest.requireActual("../src/api"), requestJson: (...args: unknown[]) => mockRequestJson(...args) }));

type Backing = { get(store: string, key: string): Promise<unknown> };
const mockBuffers: Array<{ save(id: string, blob: Blob, draftId?: string): Promise<void>; entries(): Promise<unknown[]> }> = [];
jest.mock("../../../app/static/js/intake/attachment_buffer.js", () => {
  const actual = jest.requireActual("../../../app/static/js/intake/attachment_buffer.js");
  const memory = () => {
    const stores: Record<string, Map<string, unknown>> = { keys: new Map(), files: new Map() };
    return {
      get: async (store: string, key: string) => stores[store].get(key),
      put: async (store: string, key: string, value: unknown) => { stores[store].set(key, value); },
      del: async (store: string, key: string) => { stores[store].delete(key); },
      all: async (store: string) => [...stores[store].values()],
      allKeys: async (store: string) => [...stores[store].keys()],
    } satisfies Backing & Record<string, unknown>;
  };
  return {
    ...actual,
    createIdbBacking: () => memory(),
    createBuffer: (options: object) => {
      const buffer = actual.createBuffer(options);
      mockBuffers.push(buffer);
      return buffer;
    },
  };
});

import { ApiError } from "../src/api";
import { useInterviewAttachments, type InterviewAttachments, type InterviewAttachmentsOptions } from "../src/web/interviewAttachments";

const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 1, 2, 3, 4]);
const csrf = { header: "X-CSRFToken", token: "csrf" };
const web = {
  WHO_VA_ATTACHMENT_POLICY: { image: { maxInputBytes: 1 } },
  processWebImageAttachment: jest.fn(),
  startWebAudioRecording: jest.fn(),
  createDraftId: () => "generated-id",
} as unknown as InterviewAttachmentsOptions["web"];

let latest: InterviewAttachments;
function Probe(props: InterviewAttachmentsOptions) {
  latest = useInterviewAttachments(props);
  return null;
}

async function mount(overrides: Partial<InterviewAttachmentsOptions> = {}) {
  let tree!: ReturnType<typeof create>;
  await act(async () => {
    tree = create(<Probe web={web} userId="u1" draftId="draft-1" draftsEndpoint="/api/v1/intake/drafts" csrf={csrf} labelFor={() => "Narration photo"} {...overrides} />);
  });
  return tree;
}

const savedIndexedDb = (window as { indexedDB?: unknown }).indexedDB;
beforeEach(() => {
  (window as { indexedDB?: unknown }).indexedDB = {};
  window.addEventListener = jest.fn();
  window.removeEventListener = jest.fn();
  mockBuffers.length = 0;
  mockRequestJson.mockReset();
});
afterAll(() => { (window as { indexedDB?: unknown }).indexedDB = savedIndexedDb; });

it("gives the form record, photograph, pick, attach, show and remove services", async () => {
  const tree = await mount();
  expect(latest.unavailable).toBe(false);
  for (const service of ["captureImage", "selectImage", "startAudioRecording", "selectFile", "resolveAttachmentUri", "removeAttachment"] as const) {
    expect(typeof latest.platform?.[service]).toBe("function");
  }
  expect(window.addEventListener).toHaveBeenCalledWith("online", expect.any(Function));
  await act(async () => tree.unmount());
});

it("offers nothing without IndexedDB rather than storing in the clear, and nothing when turned off", async () => {
  (window as { indexedDB?: unknown }).indexedDB = undefined;
  let tree = await mount();
  expect(latest.unavailable).toBe(true);
  expect(latest.platform).toBeUndefined();
  await act(async () => tree.unmount());

  (window as { indexedDB?: unknown }).indexedDB = {};
  tree = await mount({ draftId: undefined });
  expect(latest.unavailable).toBe(false);
  expect(latest.platform).toBeUndefined();
  expect(mockBuffers).toHaveLength(0);
  await act(async () => tree.unmount());
});

it("sends a buffered file through the app's request helper and reports nothing waiting once the server confirms", async () => {
  mockRequestJson.mockResolvedValue({ status: 201, body: { created: true } });
  const tree = await mount();
  await act(async () => { await mockBuffers[0].save("6f1c2d6e-0000-4000-8000-000000000001", new Blob([PNG])); });
  let waiting = -1;
  await act(async () => { waiting = await latest.send(); });
  expect(waiting).toBe(0);
  expect(mockRequestJson).toHaveBeenCalledWith("", "/api/v1/intake/drafts/draft-1/attachments/6f1c2d6e-0000-4000-8000-000000000001", expect.objectContaining({
    method: "PUT", csrf, rawBody: expect.objectContaining({ sha256: expect.stringMatching(/^[0-9a-f]{64}$/) }),
  }));
  expect(await mockBuffers[0].entries()).toEqual([]);
  await act(async () => tree.unmount());
});

it("keeps a file when a 200 reply is not the server's JSON (captive portal), and sends the exact bytes and digest", async () => {
  mockRequestJson.mockRejectedValueOnce(new ApiError(200, "malformed_response"));
  const tree = await mount();
  const id = "6f1c2d6e-0000-4000-8000-000000000009";
  await act(async () => { await mockBuffers[0].save(id, new Blob([PNG])); });
  let waiting = -1;
  await act(async () => { waiting = await latest.send(); });
  expect(waiting).toBe(1);
  expect((await mockBuffers[0].entries()).map((entry) => (entry as { id: string }).id)).toEqual([id]);

  mockRequestJson.mockResolvedValue({ status: 201, body: { created: true } });
  await act(async () => { waiting = await latest.send(); });
  expect(waiting).toBe(0);
  const { rawBody } = mockRequestJson.mock.calls.at(-1)[2];
  const expected = Buffer.from(await crypto.subtle.digest("SHA-256", new Uint8Array(PNG))).toString("hex");
  expect(Array.from(rawBody.bytes)).toEqual(Array.from(new Uint8Array(PNG)));
  expect(rawBody.sha256).toBe(expected);
  await act(async () => tree.unmount());
});

it("keeps and lists a file the closed draft refused, and counts it as waiting before a submit", async () => {
  mockRequestJson.mockRejectedValue(new ApiError(409, "draft_not_editable", undefined, undefined, { error: "closed" }));
  const tree = await mount();
  await act(async () => { await mockBuffers[0].save("6f1c2d6e-0000-4000-8000-000000000002", new Blob([PNG])); });
  let waiting = -1;
  await act(async () => { waiting = await latest.send(); });
  expect(waiting).toBe(1);
  expect(latest.held).toEqual([{ id: "6f1c2d6e-0000-4000-8000-000000000002", text: 'webAttachmentHeldClosed{"file":"Narration photo"}' }]);
  expect(latest.status).toBe('webAttachmentsWaiting{"count":1}');
  await act(async () => { await latest.deleteHeld("6f1c2d6e-0000-4000-8000-000000000002"); });
  expect(latest.held).toEqual([]);
  expect(latest.status).toBe("");
  await act(async () => tree.unmount());
});

it("drops a file the server refuses for good and says so", async () => {
  mockRequestJson.mockRejectedValue(new ApiError(415, "unsupported_media_type", undefined, undefined, { error: "no" }));
  const tree = await mount();
  await act(async () => { await mockBuffers[0].save("6f1c2d6e-0000-4000-8000-000000000003", new Blob([PNG])); });
  let waiting = -1;
  await act(async () => { waiting = await latest.send(); });
  expect(waiting).toBe(0);
  expect(latest.notices).toEqual(['webAttachmentRejected{"file":"Narration photo"}']);
  await act(async () => tree.unmount());
});

it("retries a network failure instead of dropping the file", async () => {
  mockRequestJson.mockRejectedValue(new TypeError("Failed to fetch"));
  const tree = await mount();
  await act(async () => { await mockBuffers[0].save("6f1c2d6e-0000-4000-8000-000000000004", new Blob([PNG])); });
  let waiting = -1;
  await act(async () => { waiting = await latest.send(); });
  expect(waiting).toBe(1);
  expect(latest.held).toEqual([]);
  expect(latest.notices).toEqual([]);
  await act(async () => tree.unmount());
});
