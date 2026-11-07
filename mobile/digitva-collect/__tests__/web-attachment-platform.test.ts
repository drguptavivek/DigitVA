/**
 * resolveAttachmentUri of the web attachment platform (app/static/js/intake/attachment_platform.js): a file the
 * device no longer holds is shown from the server. With the S3 store the server replies 302 to a presigned bucket
 * URL that connect-src 'self' forbids fetch() to follow, so the redirect must be handed to the element instead.
 */
import { createAttachmentPlatform } from "../../../app/static/js/intake/attachment_platform.js";

const noBuffer = { load: async () => undefined, save: jest.fn(), remove: jest.fn(), listIds: jest.fn() };
const make = (fetchImpl: jest.Mock) =>
  createAttachmentPlatform({
    WhoVa: { WHO_VA_ATTACHMENT_POLICY: { image: {} } },
    buffer: noBuffer,
    uploader: { flush: jest.fn() },
    attachmentUrl: (id: string) => `/api/v1/intake/drafts/d1/attachments/${id}`,
    fetchImpl,
  });
const ref = { id: "a1", uri: "who-va-attachment:a1" };

beforeEach(() => {
  (URL as unknown as { createObjectURL: unknown }).createObjectURL = jest.fn(() => "blob:local");
});

it("plays a recording the server redirects to its bucket from the server URL, without following the redirect", async () => {
  const fetchImpl = jest.fn(async () => ({ type: "opaqueredirect", ok: false, status: 0 }));
  await expect(make(fetchImpl).resolveAttachmentUri(ref)).resolves.toBe("/api/v1/intake/drafts/d1/attachments/a1");
  expect(fetchImpl).toHaveBeenCalledWith("/api/v1/intake/drafts/d1/attachments/a1", expect.objectContaining({ redirect: "manual" }));
});

it("turns a 200 body into a blob URL and a missing file into nothing", async () => {
  const ok = jest.fn(async () => ({ type: "basic", ok: true, blob: async () => new Blob(["x"]) }));
  await expect(make(ok).resolveAttachmentUri(ref)).resolves.toBe("blob:local");
  const missing = jest.fn(async () => ({ type: "basic", ok: false, status: 404 }));
  await expect(make(missing).resolveAttachmentUri(ref)).resolves.toBeUndefined();
});
