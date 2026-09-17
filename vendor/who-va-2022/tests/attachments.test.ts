import { describe, expect, it, vi } from "vitest";

import {
  AttachmentProcessingError,
  WHO_VA_ATTACHMENT_POLICY,
  inspectRasterImage,
  processImageAttachment,
  type ImageTranscoder
} from "../src/attachments.js";

function png(width: number, height: number, size = 32): Uint8Array {
  const bytes = new Uint8Array(Math.max(size, 24));
  bytes.set([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  bytes.set([0x49, 0x48, 0x44, 0x52], 12);
  new DataView(bytes.buffer).setUint32(16, width);
  new DataView(bytes.buffer).setUint32(20, height);
  return bytes;
}

function jpeg(width: number, height: number, size = 64): Uint8Array {
  const bytes = new Uint8Array(Math.max(size, 23));
  bytes.set([
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
  return bytes;
}

describe("attachment processing", () => {
  it("detects the real raster type and dimensions without trusting the filename", () => {
    expect(inspectRasterImage(png(1200, 800), "renamed.php.jpg")).toEqual({
      mimeType: "image/png",
      width: 1200,
      height: 800
    });

    expect(() =>
      inspectRasterImage(new TextEncoder().encode("<?php echo 'bad'; ?>"), "photo.jpg")
    ).toThrowError(AttachmentProcessingError);
  });

  it("rejects excessive input bytes and pixel dimensions before invoking the transcoder", async () => {
    const transcoder: ImageTranscoder = { encodeJpeg: vi.fn() };

    await expect(
      processImageAttachment(
        {
          name: "huge.jpg",
          bytes: jpeg(100, 100, WHO_VA_ATTACHMENT_POLICY.image.maxInputBytes + 1)
        },
        transcoder
      )
    ).rejects.toMatchObject({ code: "image-input-too-large" });

    await expect(
      processImageAttachment(
        {
          name: "pixel-bomb.png",
          bytes: png(20_000, 20_000)
        },
        transcoder
      )
    ).rejects.toMatchObject({ code: "image-dimensions-too-large" });

    expect(transcoder.encodeJpeg).not.toHaveBeenCalled();
  });

  it("creates a bounded UUID-named JPEG and retries compression when necessary", async () => {
    const encodeJpeg = vi
      .fn()
      .mockResolvedValueOnce(jpeg(2048, 1365, WHO_VA_ATTACHMENT_POLICY.image.maxOutputBytes + 1))
      .mockResolvedValueOnce(jpeg(2048, 1365, 800_000));

    const processed = await processImageAttachment(
      {
        name: "death-certificate.PNG",
        bytes: png(3000, 2000)
      },
      { encodeJpeg },
      {
        createId: () => "53e80b9f-ff9b-4b52-9842-e36f38931a6c"
      }
    );

    expect(encodeJpeg).toHaveBeenNthCalledWith(1, expect.anything(), {
      width: 2048,
      height: 1365,
      quality: 0.82,
      background: "#ffffff"
    });
    expect(encodeJpeg).toHaveBeenNthCalledWith(
      2,
      expect.anything(),
      expect.objectContaining({ quality: 0.72 })
    );
    expect(processed).toMatchObject({
      id: "53e80b9f-ff9b-4b52-9842-e36f38931a6c",
      name: "53e80b9f-ff9b-4b52-9842-e36f38931a6c.jpg",
      originalName: "death-certificate.PNG",
      mimeType: "image/jpeg",
      width: 2048,
      height: 1365,
      size: 800_000
    });
    expect(processed.bytes).toHaveLength(800_000);
  });

  it("discards an image that cannot be reduced below the final byte limit", async () => {
    const oversized = jpeg(2048, 1365, WHO_VA_ATTACHMENT_POLICY.image.maxOutputBytes + 1);
    await expect(
      processImageAttachment(
        { name: "photo.jpg", bytes: jpeg(3000, 2000) },
        {
          encodeJpeg: vi.fn().mockResolvedValue(oversized)
        }
      )
    ).rejects.toMatchObject({ code: "image-output-too-large" });
  });
});
