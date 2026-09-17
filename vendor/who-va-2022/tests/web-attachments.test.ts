// @vitest-environment jsdom

import { describe, expect, it, vi } from "vitest";

import { WHO_VA_ATTACHMENT_POLICY, type ImageTranscoder } from "../src/attachments.js";
import {
  cleanupOrphanedWebAttachments,
  loadWebAttachmentBlob,
  processWebImageAttachment,
  resolveWebAttachmentUri,
  storeWebPdfAttachment,
  type WebAttachmentBinaryStore,
  type WebImageFile
} from "../src/web-attachments.js";

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

function arrayBuffer(bytes: Uint8Array): ArrayBuffer {
  const copy = new Uint8Array(bytes.byteLength);
  copy.set(bytes);
  return copy.buffer;
}

function memoryStore(): WebAttachmentBinaryStore & { saved: Map<string, Blob> } {
  const saved = new Map<string, Blob>();
  return {
    saved,
    async save(id, blob) {
      saved.set(id, blob);
    },
    async load(id) {
      return saved.get(id);
    },
    async remove(id) {
      saved.delete(id);
    },
    async listIds() {
      return [...saved.keys()];
    }
  };
}

describe("web attachment processing", () => {
  it("stores only the generated JPEG and returns a durable draft reference", async () => {
    const original = png(3000, 2000);
    const file: WebImageFile = {
      name: "certificate.png",
      size: original.byteLength,
      type: "image/png",
      async arrayBuffer() {
        return arrayBuffer(original);
      }
    };
    const output = jpeg(2048, 1365);
    const transcoder: ImageTranscoder = { encodeJpeg: vi.fn().mockResolvedValue(output) };
    const store = memoryStore();

    const reference = await processWebImageAttachment(file, {
      store,
      transcoder,
      createId: () => "71abc7b2-262f-4d95-8993-4117ff764c3a"
    });

    expect(reference).toEqual({
      id: "71abc7b2-262f-4d95-8993-4117ff764c3a",
      uri: "who-va-attachment:71abc7b2-262f-4d95-8993-4117ff764c3a",
      name: "71abc7b2-262f-4d95-8993-4117ff764c3a.jpg",
      originalName: "certificate.png",
      mimeType: "image/jpeg",
      size: output.byteLength,
      width: 2048,
      height: 1365,
      processed: true
    });
    expect(store.saved.get(reference.id)?.type).toBe("image/jpeg");
    expect(new Uint8Array(await store.saved.get(reference.id)!.arrayBuffer())).toEqual(output);
  });

  it("processes a browser Blob without reading the complete original into the JS heap", async () => {
    const original = png(3000, 2000);
    const file = new File([arrayBuffer(original)], "camera.png", { type: "image/png" });
    const fullRead = vi.spyOn(file, "arrayBuffer");
    const close = vi.fn();
    vi.stubGlobal("createImageBitmap", vi.fn().mockResolvedValue({ width: 3000, height: 2000, close }));
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      fillStyle: "",
      fillRect: vi.fn(),
      drawImage: vi.fn()
    } as unknown as CanvasRenderingContext2D);
    vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation((callback) => {
      callback(new Blob([arrayBuffer(jpeg(2048, 1365))], { type: "image/jpeg" }));
    });

    const reference = await processWebImageAttachment(file, {
      store: memoryStore(),
      createId: () => "blob-direct"
    });

    expect(reference.id).toBe("blob-direct");
    expect(fullRead).not.toHaveBeenCalled();
    expect(close).toHaveBeenCalledOnce();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("rejects oversized image dimensions before browser decoding", async () => {
    const original = png(WHO_VA_ATTACHMENT_POLICY.image.maxInputWidthOrHeight + 1, 10);
    const file = new File([arrayBuffer(original)], "oversized.png", { type: "image/png" });
    const createImageBitmap = vi.fn();
    vi.stubGlobal("createImageBitmap", createImageBitmap);

    await expect(processWebImageAttachment(file, { store: memoryStore() })).rejects.toMatchObject({
      code: "image-dimensions-too-large"
    });
    expect(createImageBitmap).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("resolves a stored attachment to a temporary preview URL", async () => {
    const store = memoryStore();
    await store.save("stored-image", new Blob([arrayBuffer(jpeg(100, 100))], { type: "image/jpeg" }));
    const createObjectURL = vi.fn(() => "blob:preview-url");

    await expect(resolveWebAttachmentUri({ id: "stored-image" }, store, createObjectURL)).resolves.toBe(
      "blob:preview-url"
    );
    expect(createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    await expect(loadWebAttachmentBlob({ id: "stored-image" }, store)).resolves.toBeInstanceOf(Blob);
  });

  it("rejects an oversized selection before reading it into memory", async () => {
    const arrayBuffer = vi.fn();
    const file: WebImageFile = {
      name: "huge.jpg",
      size: WHO_VA_ATTACHMENT_POLICY.image.maxInputBytes + 1,
      type: "image/jpeg",
      arrayBuffer
    };

    await expect(
      processWebImageAttachment(file, {
        store: memoryStore(),
        transcoder: { encodeJpeg: vi.fn() }
      })
    ).rejects.toMatchObject({ code: "image-input-too-large" });
    expect(arrayBuffer).not.toHaveBeenCalled();
  });

  it("stores retained PDF originals for server-side validation", async () => {
    const original = new Uint8Array(64);
    original.set(new TextEncoder().encode("%PDF-1.7\n"));
    const file: WebImageFile = {
      name: "interview-notes.pdf",
      size: original.byteLength,
      type: "application/pdf",
      async arrayBuffer() {
        return arrayBuffer(original);
      }
    };
    const store = memoryStore();

    const reference = await storeWebPdfAttachment(file, {
      store,
      createId: () => "ad13fefc-9d37-47d7-94df-ec6c894e65dd"
    });

    expect(reference).toMatchObject({
      id: "ad13fefc-9d37-47d7-94df-ec6c894e65dd",
      uri: "who-va-attachment:ad13fefc-9d37-47d7-94df-ec6c894e65dd",
      originalName: "interview-notes.pdf",
      mimeType: "application/pdf",
      originalRetained: true,
      processed: false,
      serverSideValidationRequired: true
    });
    expect(store.saved.size).toBe(1);
    expect(Array.from(store.saved.values()).every((blob) => blob.type === "application/pdf")).toBe(true);
  });

  it("removes stored binaries that are no longer referenced by drafts", async () => {
    const store = memoryStore();
    await store.save("kept", new Blob(["kept"]));
    await store.save("kept-pdf", new Blob(["kept pdf"]));
    await store.save("orphan", new Blob(["orphan"]));
    const references = [
      {
        data: {
          imageAnswer: { id: "kept", uri: "who-va-attachment:kept" },
          documentAnswer: { id: "kept-pdf", uri: "who-va-attachment:kept-pdf" }
        }
      }
    ];

    await expect(cleanupOrphanedWebAttachments(references, store)).resolves.toBe(1);
    expect(store.saved.has("kept")).toBe(true);
    expect(store.saved.has("kept-pdf")).toBe(true);
    expect(store.saved.has("orphan")).toBe(false);
  });
});
