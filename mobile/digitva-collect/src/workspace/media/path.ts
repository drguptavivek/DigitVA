export type AttachmentMediaKind = "image" | "audio";

const IMAGE_EXTENSIONS = new Set(["jpg", "jpeg", "png", "gif", "webp"]);
const AUDIO_EXTENSIONS = new Set(["mp3", "m4a", "wav", "webm", "amr"]);
const DOCUMENT_EXTENSIONS = new Set(["pdf"]);

/** Return the extension only for a safe, same-origin API attachment path. */
export function attachmentMediaExtension(path: string): string | null {
  if (!path.startsWith("/api/v1/attachments/") || /[\\?#]/.test(path) || /%(?:2f|5c)/i.test(path)) return null;
  const segments = path.slice("/api/v1/attachments/".length).split("/");
  if (segments.some((segment) => !segment || /%(?![0-9a-f]{2})/i.test(segment))) return null;
  let decoded: string[];
  try {
    decoded = segments.map(decodeURIComponent);
  } catch {
    return null;
  }
  if (decoded.some((segment) => segment === "." || segment === ".."
    || /[\\/\u0000-\u001f\u007f]/.test(segment) || /%(?:2e|2f|5c)/i.test(segment))) return null;

  let filename: string;
  if (decoded.length === 1 && /^[a-f0-9]{32}\.[a-z0-9]+$/i.test(decoded[0])) {
    filename = decoded[0];
  } else if (
    decoded.length === 3 && decoded[0] === "legacy"
    && decoded[1].length > 0 && decoded[2].length > 0 && !decoded[2].includes("..")
  ) {
    filename = decoded[2];
  } else {
    return null;
  }

  const extension = filename.split(".").at(-1)?.toLowerCase() ?? "";
  return IMAGE_EXTENSIONS.has(extension) || AUDIO_EXTENSIONS.has(extension) || DOCUMENT_EXTENSIONS.has(extension)
    ? extension
    : null;
}

/** Return the supported media kind only for safe API attachment paths. */
export function attachmentMediaKind(path: string): AttachmentMediaKind | null {
  const extension = attachmentMediaExtension(path);
  if (!extension) return null;
  if (IMAGE_EXTENSIONS.has(extension)) return "image";
  return AUDIO_EXTENSIONS.has(extension) ? "audio" : null;
}

/** AMR is accepted by the API but has no reliable native browser decoder. */
export function browserAudioSupported(path: string): boolean {
  const extension = attachmentMediaExtension(path);
  return extension !== "amr" && extension !== null && AUDIO_EXTENSIONS.has(extension);
}
