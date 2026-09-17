/**
 * Platform-neutral attachment policies, validation, and processing pipelines.
 * Browser and native adapters supply the codecs and persistence used here.
 */
import { createDraftId } from "./draft.js";
import type { ProcessedImageAttachmentReference, RetainedPdfAttachmentReference } from "./types.js";

export interface ImageAttachmentPolicy {
  acceptedMimeTypes: readonly ["image/jpeg", "image/png"];
  maxInputBytes: number;
  maxOutputBytes: number;
  maxPixels: number;
  maxInputWidthOrHeight: number;
  maxOutputWidthOrHeight: number;
  jpegQualities: readonly number[];
}

export interface PdfAttachmentPolicy {
  acceptedMimeTypes: readonly ["application/pdf"];
  maxInputBytes: number;
  maxPages: number;
  maxOutputBytes: number;
  maxPageWidthOrHeight: number;
}

export interface WhoVaAttachmentPolicy {
  image: ImageAttachmentPolicy;
  pdf: PdfAttachmentPolicy;
}

export const WHO_VA_ATTACHMENT_POLICY: WhoVaAttachmentPolicy = {
  image: {
    acceptedMimeTypes: ["image/jpeg", "image/png"],
    maxInputBytes: 10 * 1024 * 1024,
    maxOutputBytes: 2 * 1024 * 1024,
    maxPixels: 16_000_000,
    maxInputWidthOrHeight: 8_192,
    maxOutputWidthOrHeight: 2048,
    jpegQualities: [0.82, 0.72, 0.62, 0.52]
  },
  pdf: {
    acceptedMimeTypes: ["application/pdf"],
    maxInputBytes: 5 * 1024 * 1024,
    maxPages: 10,
    maxOutputBytes: 10 * 1024 * 1024,
    maxPageWidthOrHeight: 1600
  }
};

export type AttachmentProcessingErrorCode =
  | "image-input-too-large"
  | "image-type-not-allowed"
  | "image-dimensions-invalid"
  | "image-dimensions-too-large"
  | "image-decode-failed"
  | "image-output-invalid"
  | "image-output-too-large"
  | "image-processing-unavailable"
  | "attachment-storage-failed"
  | "pdf-input-too-large"
  | "pdf-type-not-allowed"
  | "pdf-render-failed"
  | "pdf-too-many-pages"
  | "pdf-output-too-large"
  | "pdf-processing-unavailable";

const ERROR_MESSAGES: Record<AttachmentProcessingErrorCode, string> = {
  "image-input-too-large": "Choose an image smaller than 10 MB.",
  "image-type-not-allowed":
    "Choose a valid JPEG or PNG image. Renamed and unsupported files are not accepted.",
  "image-dimensions-invalid": "This image has invalid dimensions and cannot be used.",
  "image-dimensions-too-large":
    "This image has too many pixels. Choose a smaller image or retake the photograph.",
  "image-decode-failed": "This file could not be decoded as a safe image.",
  "image-output-invalid": "The processed image could not be verified as a JPEG.",
  "image-output-too-large": "This image could not be reduced below 2 MB. Retake it at a lower resolution.",
  "image-processing-unavailable": "Image processing is unavailable. The original image was not saved.",
  "attachment-storage-failed": "The processed attachment could not be saved on this device.",
  "pdf-input-too-large": "Choose a PDF smaller than 5 MB.",
  "pdf-type-not-allowed": "Choose a valid PDF. Renamed and unsupported files are not accepted.",
  "pdf-render-failed": "This PDF could not be safely converted to page images and was discarded.",
  "pdf-too-many-pages": "This PDF has too many pages. Select a document with no more than 10 pages.",
  "pdf-output-too-large": "The converted PDF pages are too large and were discarded.",
  "pdf-processing-unavailable": "PDF conversion is unavailable. The original PDF was not saved."
};

export class AttachmentProcessingError extends Error {
  readonly code: AttachmentProcessingErrorCode;
  readonly userMessage: string;

  constructor(code: AttachmentProcessingErrorCode, cause?: unknown) {
    super(ERROR_MESSAGES[code], cause === undefined ? undefined : { cause });
    this.name = "AttachmentProcessingError";
    this.code = code;
    this.userMessage = ERROR_MESSAGES[code];
  }
}

export interface InspectedRasterImage {
  mimeType: "image/jpeg" | "image/png";
  width: number;
  height: number;
}

export interface BinaryImageSelection {
  name: string;
  bytes: Uint8Array;
}

export interface ImageEncodingOptions {
  width: number;
  height: number;
  quality: number;
  background: "#ffffff";
}

export interface DecodableImage extends BinaryImageSelection, InspectedRasterImage {}

export interface ImageTranscoder {
  encodeJpeg(image: DecodableImage, options: ImageEncodingOptions): Promise<Uint8Array>;
}

export interface ProcessedImageAttachment {
  id: string;
  name: string;
  originalName: string;
  mimeType: "image/jpeg";
  width: number;
  height: number;
  size: number;
  bytes: Uint8Array;
}

export function isProcessedImageAttachment(
  value: unknown,
  policy: ImageAttachmentPolicy = WHO_VA_ATTACHMENT_POLICY.image
): value is ProcessedImageAttachmentReference {
  if (value == null || Array.isArray(value) || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return (
    candidate.processed === true &&
    candidate.mimeType === "image/jpeg" &&
    typeof candidate.id === "string" &&
    candidate.id.length > 0 &&
    typeof candidate.uri === "string" &&
    typeof candidate.name === "string" &&
    candidate.name.toLowerCase().endsWith(".jpg") &&
    typeof candidate.originalName === "string" &&
    typeof candidate.size === "number" &&
    candidate.size > 0 &&
    candidate.size <= policy.maxOutputBytes &&
    typeof candidate.width === "number" &&
    candidate.width > 0 &&
    typeof candidate.height === "number" &&
    candidate.height > 0
  );
}

export interface ProcessImageAttachmentOptions {
  policy?: ImageAttachmentPolicy;
  createId?: () => string;
}

async function encodeInspectedImage(
  name: string,
  inspected: InspectedRasterImage,
  transcoder: ImageTranscoder,
  sourceBytes: Uint8Array,
  options: ProcessImageAttachmentOptions
): Promise<ProcessedImageAttachment> {
  const policy = options.policy ?? WHO_VA_ATTACHMENT_POLICY.image;
  validateImageDimensions(inspected, policy);
  const dimensions = targetDimensions(inspected.width, inspected.height, policy.maxOutputWidthOrHeight);
  const image: DecodableImage = { name, bytes: sourceBytes, ...inspected };
  let lastOutput: Uint8Array | undefined;

  for (const quality of policy.jpegQualities) {
    try {
      lastOutput = await transcoder.encodeJpeg(image, { ...dimensions, quality, background: "#ffffff" });
    } catch (error) {
      throw error instanceof AttachmentProcessingError
        ? error
        : new AttachmentProcessingError("image-decode-failed", error);
    }
    if (lastOutput.byteLength <= policy.maxOutputBytes) break;
  }

  if (!lastOutput || lastOutput.byteLength > policy.maxOutputBytes) {
    throw new AttachmentProcessingError("image-output-too-large");
  }

  let outputInspection: InspectedRasterImage;
  try {
    outputInspection = inspectRasterImage(lastOutput);
  } catch (error) {
    throw new AttachmentProcessingError("image-output-invalid", error);
  }
  if (outputInspection.mimeType !== "image/jpeg") throw new AttachmentProcessingError("image-output-invalid");

  const id = (options.createId ?? createDraftId)();
  return {
    id,
    name: `${id}.jpg`,
    originalName: name,
    mimeType: "image/jpeg",
    width: outputInspection.width,
    height: outputInspection.height,
    size: lastOutput.byteLength,
    bytes: lastOutput
  };
}

/** Processes an image already inspected by a trusted native or browser decoder. */
export function processInspectedImageAttachment(
  name: string,
  inspected: InspectedRasterImage,
  transcoder: ImageTranscoder,
  options: ProcessImageAttachmentOptions = {}
): Promise<ProcessedImageAttachment> {
  return encodeInspectedImage(name, inspected, transcoder, new Uint8Array(), options);
}

export type RetainedPdfAttachment = RetainedPdfAttachmentReference;

export function isRetainedPdfAttachment(
  value: unknown,
  policy: PdfAttachmentPolicy = WHO_VA_ATTACHMENT_POLICY.pdf
): value is RetainedPdfAttachment {
  if (value == null || Array.isArray(value) || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return (
    candidate.processed === false &&
    candidate.originalRetained === true &&
    candidate.serverSideValidationRequired === true &&
    candidate.mimeType === "application/pdf" &&
    typeof candidate.id === "string" &&
    candidate.id.length > 0 &&
    typeof candidate.uri === "string" &&
    typeof candidate.name === "string" &&
    candidate.name.toLowerCase().endsWith(".pdf") &&
    typeof candidate.originalName === "string" &&
    typeof candidate.size === "number" &&
    candidate.size > 0 &&
    candidate.size <= policy.maxInputBytes
  );
}

function uint16(bytes: Uint8Array, offset: number): number {
  return ((bytes[offset] ?? 0) << 8) | (bytes[offset + 1] ?? 0);
}

function inspectJpeg(bytes: Uint8Array): InspectedRasterImage | undefined {
  if (bytes[0] !== 0xff || bytes[1] !== 0xd8 || bytes[2] !== 0xff) return undefined;
  const startOfFrameMarkers = new Set([
    0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf
  ]);
  let offset = 2;
  while (offset + 8 < bytes.length) {
    if (bytes[offset] !== 0xff) {
      offset += 1;
      continue;
    }
    const marker = bytes[offset + 1];
    if (marker === undefined || marker === 0xd9 || marker === 0xda) break;
    if (marker === 0xff || marker === 0x00) {
      offset += 1;
      continue;
    }
    const segmentLength = uint16(bytes, offset + 2);
    if (segmentLength < 2 || offset + segmentLength + 2 > bytes.length) return undefined;
    if (startOfFrameMarkers.has(marker)) {
      const height = uint16(bytes, offset + 5);
      const width = uint16(bytes, offset + 7);
      return { mimeType: "image/jpeg", width, height };
    }
    offset += segmentLength + 2;
  }
  return undefined;
}

function inspectPng(bytes: Uint8Array): InspectedRasterImage | undefined {
  const signature = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
  if (bytes.length < 24 || signature.some((byte, index) => bytes[index] !== byte)) return undefined;
  if (String.fromCharCode(...bytes.slice(12, 16)) !== "IHDR") return undefined;
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  return { mimeType: "image/png", width: view.getUint32(16), height: view.getUint32(20) };
}

export function inspectRasterImage(bytes: Uint8Array, _filename?: string): InspectedRasterImage {
  const inspected = inspectPng(bytes) ?? inspectJpeg(bytes);
  if (!inspected) throw new AttachmentProcessingError("image-type-not-allowed");
  if (inspected.width <= 0 || inspected.height <= 0)
    throw new AttachmentProcessingError("image-dimensions-invalid");
  return inspected;
}

function targetDimensions(width: number, height: number, maximum: number): { width: number; height: number } {
  const scale = Math.min(1, maximum / Math.max(width, height));
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale))
  };
}

export function validateImageDimensions(image: InspectedRasterImage, policy: ImageAttachmentPolicy): void {
  if (
    image.width > policy.maxInputWidthOrHeight ||
    image.height > policy.maxInputWidthOrHeight ||
    image.width * image.height > policy.maxPixels
  )
    throw new AttachmentProcessingError("image-dimensions-too-large");
}

export async function processImageAttachment(
  selection: BinaryImageSelection,
  transcoder: ImageTranscoder,
  options: ProcessImageAttachmentOptions = {}
): Promise<ProcessedImageAttachment> {
  const policy = options.policy ?? WHO_VA_ATTACHMENT_POLICY.image;
  if (selection.bytes.byteLength > policy.maxInputBytes)
    throw new AttachmentProcessingError("image-input-too-large");

  const inspected = inspectRasterImage(selection.bytes, selection.name);
  return encodeInspectedImage(selection.name, inspected, transcoder, selection.bytes, options);
}
