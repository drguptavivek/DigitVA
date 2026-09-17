/**
 * Browser attachment adapters for IndexedDB persistence, image transcoding,
 * PDF rasterization, shared-policy processing, and object-URL resolution.
 */
import {
  AttachmentProcessingError,
  WHO_VA_ATTACHMENT_POLICY,
  inspectRasterImage,
  processImageAttachment,
  processInspectedImageAttachment,
  validateImageDimensions,
  type ImageAttachmentPolicy,
  type ImageTranscoder,
  type ProcessedImageAttachment,
  type RetainedPdfAttachment
} from "./attachments.js";
import { createDraftId } from "./draft.js";
import type { ProcessedImageAttachmentReference } from "./types.js";

const WEB_ATTACHMENT_DATABASE = "who-va-2022-attachments";
const WEB_ATTACHMENT_OBJECT_STORE = "binary";

export interface WebImageFile {
  name: string;
  size: number;
  type: string;
  arrayBuffer(): Promise<ArrayBuffer>;
}

export interface WebAttachmentBinaryStore {
  save(id: string, blob: Blob): Promise<void>;
  load(id: string): Promise<Blob | undefined>;
  remove(id: string): Promise<void>;
  listIds?(): Promise<string[]>;
}

export type WebStoredAttachmentReference = ProcessedImageAttachmentReference;

export interface ProcessWebImageAttachmentOptions {
  store: WebAttachmentBinaryStore;
  transcoder?: ImageTranscoder;
  policy?: ImageAttachmentPolicy;
  createId?: () => string;
}

export interface StoreWebPdfAttachmentOptions {
  store: WebAttachmentBinaryStore;
  createId?: () => string;
}

function openAttachmentDatabase(factory: IDBFactory): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = factory.open(WEB_ATTACHMENT_DATABASE, 1);
    request.addEventListener("upgradeneeded", () => {
      if (!request.result.objectStoreNames.contains(WEB_ATTACHMENT_OBJECT_STORE)) {
        request.result.createObjectStore(WEB_ATTACHMENT_OBJECT_STORE);
      }
    });
    request.addEventListener("success", () => resolve(request.result), { once: true });
    request.addEventListener(
      "error",
      () => reject(request.error ?? new Error("Unable to open attachment storage")),
      { once: true }
    );
  });
}

function transactionComplete(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.addEventListener("complete", () => resolve(), { once: true });
    transaction.addEventListener(
      "abort",
      () => reject(transaction.error ?? new Error("Attachment storage transaction was aborted")),
      { once: true }
    );
    transaction.addEventListener(
      "error",
      () => reject(transaction.error ?? new Error("Attachment storage transaction failed")),
      { once: true }
    );
  });
}

export function createIndexedDbWebAttachmentStore(
  factory: IDBFactory | undefined = globalThis.indexedDB
): WebAttachmentBinaryStore {
  let database: Promise<IDBDatabase> | undefined;
  const getDatabase = () => {
    if (!factory) return Promise.reject(new Error("IndexedDB is unavailable"));
    database ??= openAttachmentDatabase(factory);
    return database;
  };
  return {
    async save(id, blob) {
      const transaction = (await getDatabase()).transaction(WEB_ATTACHMENT_OBJECT_STORE, "readwrite");
      transaction.objectStore(WEB_ATTACHMENT_OBJECT_STORE).put(blob, id);
      await transactionComplete(transaction);
    },
    async load(id) {
      const transaction = (await getDatabase()).transaction(WEB_ATTACHMENT_OBJECT_STORE, "readonly");
      const request = transaction.objectStore(WEB_ATTACHMENT_OBJECT_STORE).get(id);
      return await new Promise<Blob | undefined>((resolve, reject) => {
        request.addEventListener(
          "success",
          () => resolve(request.result instanceof Blob ? request.result : undefined),
          { once: true }
        );
        request.addEventListener(
          "error",
          () => reject(request.error ?? new Error("Unable to load attachment")),
          { once: true }
        );
      });
    },
    async remove(id) {
      const transaction = (await getDatabase()).transaction(WEB_ATTACHMENT_OBJECT_STORE, "readwrite");
      transaction.objectStore(WEB_ATTACHMENT_OBJECT_STORE).delete(id);
      await transactionComplete(transaction);
    },
    async listIds() {
      const transaction = (await getDatabase()).transaction(WEB_ATTACHMENT_OBJECT_STORE, "readonly");
      const request = transaction.objectStore(WEB_ATTACHMENT_OBJECT_STORE).getAllKeys();
      return await new Promise<string[]>((resolve, reject) => {
        request.addEventListener(
          "success",
          () => resolve(request.result.filter((key): key is string => typeof key === "string")),
          { once: true }
        );
        request.addEventListener(
          "error",
          () => reject(request.error ?? new Error("Unable to list attachments")),
          { once: true }
        );
      });
    }
  };
}

function canvasToJpeg(canvas: HTMLCanvasElement, quality: number): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error("The browser could not encode the image"))),
      "image/jpeg",
      quality
    );
  });
}

function copiedArrayBuffer(bytes: Uint8Array): ArrayBuffer {
  const copy = new Uint8Array(bytes.byteLength);
  copy.set(bytes);
  return copy.buffer;
}

export function createBrowserImageTranscoder(): ImageTranscoder {
  return {
    async encodeJpeg(image, options) {
      if (typeof globalThis.createImageBitmap !== "function" || typeof document === "undefined") {
        throw new AttachmentProcessingError("image-decode-failed");
      }
      const source = new Blob([copiedArrayBuffer(image.bytes)], { type: image.mimeType });
      const bitmap = await globalThis.createImageBitmap(source, { imageOrientation: "from-image" });
      try {
        const canvas = document.createElement("canvas");
        canvas.width = options.width;
        canvas.height = options.height;
        const context = canvas.getContext("2d");
        if (!context) throw new Error("Canvas rendering is unavailable");
        context.fillStyle = options.background;
        context.fillRect(0, 0, canvas.width, canvas.height);
        context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
        return new Uint8Array(await (await canvasToJpeg(canvas, options.quality)).arrayBuffer());
      } finally {
        bitmap.close();
      }
    }
  };
}

async function processBrowserBlobImage(
  file: WebImageFile & Blob,
  options: ProcessWebImageAttachmentOptions
): Promise<ProcessedImageAttachment> {
  const policy = options.policy ?? WHO_VA_ATTACHMENT_POLICY.image;
  const header = new Uint8Array(await file.slice(0, Math.min(file.size, 512 * 1024)).arrayBuffer());
  const inspected = inspectRasterImage(header, file.name);
  validateImageDimensions(inspected, policy);
  let bitmap: ImageBitmap;
  try {
    bitmap = await globalThis.createImageBitmap(file, { imageOrientation: "from-image" });
  } catch (error) {
    throw new AttachmentProcessingError("image-decode-failed", error);
  }
  try {
    return await processInspectedImageAttachment(
      file.name,
      {
        mimeType: inspected.mimeType,
        width: bitmap.width,
        height: bitmap.height
      },
      {
        async encodeJpeg(_image, encodingOptions) {
          const canvas = document.createElement("canvas");
          canvas.width = encodingOptions.width;
          canvas.height = encodingOptions.height;
          const context = canvas.getContext("2d");
          if (!context) throw new Error("Canvas rendering is unavailable");
          context.fillStyle = encodingOptions.background;
          context.fillRect(0, 0, canvas.width, canvas.height);
          context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
          return new Uint8Array(await (await canvasToJpeg(canvas, encodingOptions.quality)).arrayBuffer());
        }
      },
      {
        policy,
        ...(options.createId ? { createId: options.createId } : {})
      }
    );
  } finally {
    bitmap.close();
  }
}

async function storeProcessedWebImage(
  processed: ProcessedImageAttachment,
  store: WebAttachmentBinaryStore
): Promise<WebStoredAttachmentReference> {
  try {
    await store.save(
      processed.id,
      new Blob([copiedArrayBuffer(processed.bytes)], { type: processed.mimeType })
    );
  } catch (error) {
    throw new AttachmentProcessingError("attachment-storage-failed", error);
  }
  return {
    id: processed.id,
    uri: `who-va-attachment:${processed.id}`,
    name: processed.name,
    originalName: processed.originalName,
    mimeType: processed.mimeType,
    size: processed.size,
    width: processed.width,
    height: processed.height,
    processed: true
  };
}

export async function processWebImageAttachment(
  file: WebImageFile,
  options: ProcessWebImageAttachmentOptions
): Promise<WebStoredAttachmentReference> {
  const policy = options.policy ?? WHO_VA_ATTACHMENT_POLICY.image;
  if (file.size > policy.maxInputBytes) throw new AttachmentProcessingError("image-input-too-large");
  const canProcessBlobDirectly =
    !options.transcoder &&
    file instanceof Blob &&
    typeof globalThis.createImageBitmap === "function" &&
    typeof document !== "undefined";
  const processed = canProcessBlobDirectly
    ? await processBrowserBlobImage(file, options)
    : await processImageAttachment(
        {
          name: file.name,
          bytes: new Uint8Array(await file.arrayBuffer())
        },
        options.transcoder ?? createBrowserImageTranscoder(),
        {
          policy,
          ...(options.createId ? { createId: options.createId } : {})
        }
      );
  return storeProcessedWebImage(processed, options.store);
}

export async function storeWebPdfAttachment(
  file: WebImageFile,
  options: StoreWebPdfAttachmentOptions
): Promise<RetainedPdfAttachment> {
  const policy = WHO_VA_ATTACHMENT_POLICY.pdf;
  if (file.size > policy.maxInputBytes) throw new AttachmentProcessingError("pdf-input-too-large");
  const bytes = new Uint8Array(await file.arrayBuffer());
  const header = bytes.slice(0, 8);
  const hasPdfHeader = header[0] === 0x25 && header[1] === 0x50 && header[2] === 0x44 && header[3] === 0x46;
  if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
    throw new AttachmentProcessingError("pdf-type-not-allowed");
  }
  if (!hasPdfHeader) throw new AttachmentProcessingError("pdf-type-not-allowed");
  const id = (options.createId ?? createDraftId)();
  try {
    await options.store.save(id, new Blob([copiedArrayBuffer(bytes)], { type: "application/pdf" }));
  } catch (error) {
    throw new AttachmentProcessingError("attachment-storage-failed", error);
  }
  return {
    id,
    uri: `who-va-attachment:${id}`,
    name: `${id}.pdf`,
    originalName: file.name,
    mimeType: "application/pdf",
    size: file.size,
    originalRetained: true,
    processed: false,
    serverSideValidationRequired: true
  };
}

export async function resolveWebAttachmentUri(
  reference: { id: string },
  store: WebAttachmentBinaryStore,
  createObjectURL: (blob: Blob) => string = URL.createObjectURL
): Promise<string | undefined> {
  const blob = await store.load(reference.id);
  return blob ? createObjectURL(blob) : undefined;
}

/** Returns a Blob suitable for streaming in multipart/fetch uploads without base64 conversion. */
export function loadWebAttachmentBlob(
  reference: { id: string },
  store: WebAttachmentBinaryStore
): Promise<Blob | undefined> {
  return store.load(reference.id);
}

function collectReferenceIds(value: unknown, output: Set<string>, seen: WeakSet<object>): void {
  if (value == null || typeof value !== "object") return;
  if (seen.has(value)) return;
  seen.add(value);
  if (Array.isArray(value)) {
    for (const item of value) collectReferenceIds(item, output, seen);
    return;
  }
  const candidate = value as Record<string, unknown>;
  if (
    typeof candidate.id === "string" &&
    typeof candidate.uri === "string" &&
    candidate.uri.startsWith("who-va-attachment:")
  )
    output.add(candidate.id);
  for (const nested of Object.values(candidate)) collectReferenceIds(nested, output, seen);
}

/** Deletes stored binaries that are not referenced by any supplied draft/answer attachment. */
export async function cleanupOrphanedWebAttachments(
  references: Iterable<unknown>,
  store: WebAttachmentBinaryStore
): Promise<number> {
  if (!store.listIds) return 0;
  const retained = new Set<string>();
  const seen = new WeakSet<object>();
  for (const reference of references) collectReferenceIds(reference, retained, seen);
  const stored = await store.listIds();
  const orphaned = stored.filter((id) => !retained.has(id));
  await Promise.all(orphaned.map((id) => store.remove(id)));
  return orphaned.length;
}
