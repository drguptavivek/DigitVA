import { describe, expect, it, vi } from "vitest";

import { WHO_VA_ATTACHMENT_POLICY } from "../src/attachments.js";
import { processNativeImageAttachment, type NativeAttachmentFileAdapter } from "../src/native-attachments.js";

function png(width: number, height: number): Uint8Array {
  const bytes = new Uint8Array(32);
  bytes.set([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  bytes.set([0x49, 0x48, 0x44, 0x52], 12);
  new DataView(bytes.buffer).setUint32(16, width);
  new DataView(bytes.buffer).setUint32(20, height);
  return bytes;
}

function jpeg(width: number, height: number): Uint8Array {
  return new Uint8Array([
    0xff,
    0xd8,
    0xff,
    0xe0,
    0x00,
    0x04,
    0x00,
    0x00,
    0xff,
    0xc0,
    0x00,
    0x0b,
    0x08,
    (height >> 8) & 0xff,
    height & 0xff,
    (width >> 8) & 0xff,
    width & 0xff,
    0x01,
    0x01,
    0x11,
    0x00,
    0xff,
    0xd9
  ]);
}

describe("native attachment processing", () => {
  it("persists only the verified JPEG produced by the native adapter", async () => {
    const original = png(3000, 2000);
    const encoded = jpeg(2048, 1365);
    const files = new Map([
      ["file:///picker/raw.png", original],
      ["file:///cache/processed.jpg", encoded]
    ]);
    const adapter: NativeAttachmentFileAdapter = {
      getSize: vi.fn(async (uri) => files.get(uri)?.byteLength ?? 0),
      read: vi.fn(async (uri) => files.get(uri) ?? new Uint8Array()),
      encodeJpeg: vi.fn(async () => "file:///cache/processed.jpg"),
      persist: vi.fn(async (_uri, name) => `file:///documents/attachments/${name}`),
      remove: vi.fn(async () => undefined)
    };

    const reference = await processNativeImageAttachment(
      {
        uri: "file:///picker/raw.png",
        name: "raw.png"
      },
      adapter,
      { createId: () => "3d602dd8-22aa-40ef-89dc-6214ff4337d7" }
    );

    expect(reference).toMatchObject({
      id: "3d602dd8-22aa-40ef-89dc-6214ff4337d7",
      uri: "file:///documents/attachments/3d602dd8-22aa-40ef-89dc-6214ff4337d7.jpg",
      name: "3d602dd8-22aa-40ef-89dc-6214ff4337d7.jpg",
      originalName: "raw.png",
      mimeType: "image/jpeg",
      processed: true
    });
    expect(adapter.persist).toHaveBeenCalledWith(
      "file:///cache/processed.jpg",
      "3d602dd8-22aa-40ef-89dc-6214ff4337d7.jpg"
    );
    expect(adapter.persist).not.toHaveBeenCalledWith("file:///picker/raw.png", expect.anything());
  });

  it("rejects an oversized native selection before reading or decoding it", async () => {
    const adapter: NativeAttachmentFileAdapter = {
      getSize: vi.fn().mockResolvedValue(WHO_VA_ATTACHMENT_POLICY.image.maxInputBytes + 1),
      read: vi.fn(),
      encodeJpeg: vi.fn(),
      persist: vi.fn(),
      remove: vi.fn()
    };

    await expect(
      processNativeImageAttachment({ uri: "file:///cache/huge.jpg", name: "huge.jpg" }, adapter)
    ).rejects.toMatchObject({ code: "image-input-too-large" });
    expect(adapter.read).not.toHaveBeenCalled();
    expect(adapter.encodeJpeg).not.toHaveBeenCalled();
  });

  it("uses native inspection without copying the original image into the JS heap", async () => {
    const encoded = jpeg(1600, 1067);
    const adapter: NativeAttachmentFileAdapter = {
      getSize: vi.fn().mockResolvedValue(4_000_000),
      inspect: vi.fn().mockResolvedValue({ mimeType: "image/png", width: 3000, height: 2000 }),
      read: vi.fn(async (uri) => (uri.includes("processed") ? encoded : new Uint8Array())),
      encodeJpeg: vi.fn().mockResolvedValue("file:///cache/processed.jpg"),
      persist: vi.fn(async (_uri, name) => `file:///documents/attachments/${name}`),
      remove: vi.fn().mockResolvedValue(undefined)
    };

    await processNativeImageAttachment({ uri: "file:///picker/raw.png", name: "raw.png" }, adapter, {
      createId: () => "native-inspected"
    });

    expect(adapter.inspect).toHaveBeenCalledWith("file:///picker/raw.png");
    expect(adapter.read).not.toHaveBeenCalledWith("file:///picker/raw.png");
    expect(adapter.read).toHaveBeenCalledWith("file:///cache/processed.jpg");
  });
});
