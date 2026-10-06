// The protected platform services the intake page hands the questionnaire.
//
// Replaces the package's `createInsecureWhoVaBrowserDefaults()` platform, whose
// attachment store is plaintext IndexedDB. Everything the form captures goes
// through the encrypted buffer (attachment_buffer.js) and is sent to the server
// by the uploader; once the server confirms, the device copy is gone and the
// form shows the file from the server. Policy: docs/policy/web-intake.md,
// "Attachments". The package is not edited: this only supplies what it asks a
// host for (see WhoVaPlatformServices in vendor/who-va-2022).

import { MAX_BYTES } from "./attachment_buffer.js";

/** One file from the browser's picker, or undefined when cancelled. */
function pickFile(accept, capture = false) {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = accept;
    if (capture) input.setAttribute("capture", "environment");
    input.addEventListener("change", () => resolve(input.files?.[0]), { once: true });
    input.addEventListener("cancel", () => resolve(undefined), { once: true });
    input.click();
  });
}

// A picked file's name can name the deceased or the respondent. The package
// keeps it as `originalName`; nothing leaves this adapter carrying it, so it is
// replaced by the id-based name the package makes (or the id itself).
export const withoutFileName = (reference) => ({ ...reference, originalName: reference.name || reference.id });

const isPdfHeader = (bytes) => bytes[0] === 0x25 && bytes[1] === 0x50 && bytes[2] === 0x44 && bytes[3] === 0x46;

/**
 * @param WhoVa    the package module (processWebImageAttachment, startWebAudioRecording,
 *                 createDraftId, WHO_VA_ATTACHMENT_POLICY)
 * @param buffer   createBuffer(...)
 * @param uploader createUploader(...)
 * @param attachmentUrl (id) -> the server URL of a file of this draft
 */
export function createAttachmentPlatform({ WhoVa, buffer, uploader, attachmentUrl, pick = pickFile, fetchImpl = globalThis.fetch }) {
  // The package's WebAttachmentBinaryStore, over the encrypted buffer. A save
  // kicks the uploader so a file captured online is sent at once.
  const store = {
    async save(id, blob) {
      await buffer.save(id, blob);
      uploader.flush().catch(() => {});
    },
    load: (id) => buffer.load(id),
    remove: (id) => buffer.remove(id),
    listIds: () => buffer.listIds(),
  };
  // The package shrinks an image to a JPEG of at most 2 MB; the input may be
  // the owner's 25 MB rather than the package's 10 MB default.
  const imagePolicy = { ...WhoVa.WHO_VA_ATTACHMENT_POLICY.image, maxInputBytes: MAX_BYTES };

  const processImage = (file) => {
    if (file.size > MAX_BYTES) throw new Error("This file is larger than 25 MB.");
    return WhoVa.processWebImageAttachment(file, { store, policy: imagePolicy }).then(withoutFileName);
  };

  // The package keeps a PDF only up to 5 MB; the owner's limit is 25 MB, so the
  // PDF is checked and kept here (the server validates it again).
  async function keepPdf(file) {
    if (file.size > MAX_BYTES) throw new Error("This file is larger than 25 MB.");
    const head = new Uint8Array(await file.slice(0, 8).arrayBuffer());
    if (!isPdfHeader(head)) throw new Error("This file is not a PDF.");
    const id = WhoVa.createDraftId();
    await store.save(id, new Blob([await file.arrayBuffer()], { type: "application/pdf" }));
    return {
      id,
      uri: `who-va-attachment:${id}`,
      name: `${id}.pdf`,
      originalName: `${id}.pdf`,
      mimeType: "application/pdf",
      size: file.size,
      originalRetained: true,
      processed: false,
      serverSideValidationRequired: true,
    };
  }

  return {
    startAudioRecording: async () => {
      const session = await WhoVa.startWebAudioRecording({ store });
      return { stop: () => session.stop().then(withoutFileName), cancel: () => session.cancel() };
    },
    captureImage: async () => {
      const file = await pick("image/jpeg,image/png", true);
      return file ? processImage(file) : undefined;
    },
    selectImage: async () => {
      const file = await pick("image/jpeg,image/png");
      return file ? processImage(file) : undefined;
    },
    selectFile: async (_question, _data, acceptedMimeTypes) => {
      const file = await pick(acceptedMimeTypes.join(","));
      if (!file) return undefined;
      const isImage = file.type === "image/jpeg" || file.type === "image/png" || /\.(?:jpe?g|png)$/i.test(file.name);
      if (isImage && acceptedMimeTypes.includes("image/jpeg")) return processImage(file);
      if (acceptedMimeTypes.includes("application/pdf")) return keepPdf(file);
      return undefined;
    },
    // On this device while unsent; from the server once confirmed (and on any
    // other device the draft is opened on).
    resolveAttachmentUri: async (attachment) => {
      if (!attachment || typeof attachment !== "object" || typeof attachment.id !== "string") return undefined;
      let blob = await buffer.load(attachment.id).catch(() => undefined);
      if (!blob) {
        const response = await fetchImpl(attachmentUrl(attachment.id), { credentials: "same-origin" }).catch(() => undefined);
        if (!response || !response.ok) return undefined;
        blob = await response.blob();
      }
      return URL.createObjectURL(blob);
    },
    releaseAttachmentUri: (uri) => {
      if (uri.startsWith("blob:")) URL.revokeObjectURL(uri);
    },
    // Removes an unsent copy. A file the server already holds stays there,
    // unlinked unless the answer still names it.
    removeAttachment: async (attachment) => {
      if (attachment && typeof attachment === "object" && typeof attachment.id === "string") await buffer.remove(attachment.id);
    },
  };
}
