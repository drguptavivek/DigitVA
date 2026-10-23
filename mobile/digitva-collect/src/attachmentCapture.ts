/**
 * Capture logic for the phone's attachment controls, free of native modules so the state machines are testable:
 * the caller hands in the recorder, the file operations and the permission dialogs
 * (src/attachmentServices.native.ts). Rules: docs/policy/phone-attachments.md.
 *
 * Every captured file ends in the encrypted store (src/attachmentStore.ts) and its temporary plain file is
 * deleted at once. The reference returned to the form carries the opaque `who-va-attachment:<uuid>` uri, never
 * a file path.
 */
import {
  AttachmentProcessingError,
  WHO_VA_ATTACHMENT_POLICY,
  type AttachmentCandidate,
  type AttachmentReference,
  type ImageAttachmentPolicy,
  type ImageEncodingOptions,
  type InstrumentQuestion,
  type ProcessedImageAttachmentReference,
  type RetainedPdfAttachmentReference,
  type WhoVaPlatformServices,
} from "@drguptavivek/who-2022-va";
import { processNativeImageAttachment } from "@drguptavivek/who-2022-va/native";

import { deleteAttachment, getAttachmentBytes, getAttachmentMeta, referenceId, REFERENCE_PREFIX, saveAttachment } from "./attachmentStore";
import type { Db } from "./drafts";

/** The web recorder's limits (vendor WHO_VA_WEB_AUDIO_POLICY): 30 minutes, 25 MB. */
export const AUDIO_MAX_MS = 30 * 60 * 1000;
export const AUDIO_MAX_BYTES = 25 * 1024 * 1024;

type RecordingSession = Awaited<ReturnType<NonNullable<WhoVaPlatformServices["startAudioRecording"]>>>;

/** The subset of expo-audio's recorder this module drives. */
export interface RecorderLike {
  prepareToRecordAsync(): Promise<void>;
  record(): void;
  /** Keeps the take; `record()` carries on in the same file. */
  pause(): void;
  stop(): Promise<void>;
  readonly uri: string | null;
  readonly isRecording: boolean;
}

/** The plain-file operations (src/mediaFiles.ts) and the dialogs the capture needs. */
export interface CaptureEnv {
  db: Db;
  draftId: string;
  projectId: string | null;
  newId(): string;
  now(): number;
  readBytes(uri: string): Promise<Uint8Array>;
  fileSize(uri: string): number;
  removeFile(uri: string | null | undefined): void;
  writePlaybackCopy(id: string, ext: string, bytes: Uint8Array): string;
}

export interface AudioEnv extends CaptureEnv {
  recorder: RecorderLike;
  /** Explain, ask, and throw a NotAllowedError (after offering the settings link) when refused. */
  ensureMicrophone(): Promise<void>;
  /** Recording audio mode on, playback mode (works with the phone on silent) off; see attachmentServices.native.ts. */
  setRecordingMode(on: boolean): Promise<void>;
  /**
   * Call `onInterrupt` when the app leaves the foreground (background, a call): the take is paused, never recorded
   * in the background. Returns the unsubscribe.
   */
  watchInterruptions?(onInterrupt: () => void): () => void;
}

/** A refusal the form shows as "microphone permission denied". */
export function notAllowed(message: string): Error {
  const error = new Error(message);
  error.name = "NotAllowedError";
  return error;
}

const audioReference = (id: string, size: number, durationMs: number): AttachmentReference => ({
  id,
  uri: REFERENCE_PREFIX + id,
  name: `${id}.m4a`,
  originalName: `${id}.m4a`,
  mimeType: "audio/mp4",
  size,
  durationMs,
  processed: true,
});

/**
 * Start recording. `stop()` saves the file into the store and returns the reference; `cancel()` drops the take.
 * `pause()` / `resume()` keep one take across pauses; only recorded time counts toward AUDIO_MAX_MS. The recorder
 * stops by itself at the limit and keeps what it has, so a later `stop()` still saves it. An interruption
 * (`watchInterruptions`) pauses the take, which stays until the interviewer resumes, saves or cancels it.
 */
export async function startAudioRecording(env: AudioEnv, question: InstrumentQuestion): Promise<RecordingSession> {
  await env.ensureMicrophone();
  await env.setRecordingMode(true);
  const { recorder } = env;
  try {
    await recorder.prepareToRecordAsync();
    recorder.record();
  } catch (error) {
    await env.setRecordingMode(false).catch(() => undefined);
    throw error;
  }
  let recordedBefore = 0; // recorded ms of the finished segments
  let segmentStart: number | undefined = env.now(); // undefined while paused
  let saved: Promise<AttachmentReference> | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let unwatch: (() => void) | undefined;

  const recordedMs = () => Math.min(AUDIO_MAX_MS, recordedBefore + (segmentStart === undefined ? 0 : env.now() - segmentStart));
  const finish = (): Promise<AttachmentReference> => {
    saved ??= (async () => {
      clearTimeout(timer);
      unwatch?.();
      const durationMs = recordedMs();
      try {
        // A paused recorder is not "recording" but still holds the take: always stop it.
        await recorder.stop();
      } catch (error) {
        env.removeFile(recorder.uri);
        throw error;
      } finally {
        await env.setRecordingMode(false).catch(() => undefined);
      }
      const uri = recorder.uri;
      if (!uri) throw new Error("audio_missing");
      try {
        const size = env.fileSize(uri);
        if (size <= 0) throw new Error("audio_empty");
        if (size > AUDIO_MAX_BYTES) throw new Error("audio_too_large");
        const bytes = await env.readBytes(uri);
        const id = env.newId();
        await saveAttachment(env.db, {
          id, draftId: env.draftId, projectId: env.projectId, question: question.name, kind: "audio",
          mimeType: "audio/mp4", ext: "m4a", durationMs, bytes,
        });
        return audioReference(id, bytes.byteLength, durationMs);
      } finally {
        env.removeFile(uri);
      }
    })();
    return saved;
  };
  const armLimit = () => {
    clearTimeout(timer);
    timer = setTimeout(() => void finish().catch(() => undefined), Math.max(0, AUDIO_MAX_MS - recordedMs()));
  };
  const pause = () => {
    if (saved || segmentStart === undefined) return;
    recorder.pause();
    recordedBefore = recordedMs();
    segmentStart = undefined;
    clearTimeout(timer);
  };
  const resume = () => {
    if (saved || segmentStart !== undefined) return;
    recorder.record();
    segmentStart = env.now();
    armLimit();
  };

  armLimit();
  unwatch = env.watchInterruptions?.(() => {
    try {
      pause();
    } catch {
      // The recorder could not pause (the OS already stopped it): the take is still in `recorder`; stop() saves it.
    }
  });
  return {
    stop: finish,
    pause,
    resume,
    getState: () => ({ elapsedMs: recordedMs(), paused: segmentStart === undefined, limitMs: AUDIO_MAX_MS }),
    async cancel() {
      clearTimeout(timer);
      unwatch?.();
      try {
        if (saved) {
          // The limit already saved the take: a cancelled take leaves nothing behind.
          const reference = await saved.catch(() => undefined);
          if (reference) await removeStored(env, reference);
        } else {
          try {
            await recorder.stop();
          } finally {
            env.removeFile(recorder.uri);
          }
        }
      } finally {
        await env.setRecordingMode(false).catch(() => undefined);
      }
    },
  };
}

const IMAGE_JPEG = "image/jpeg";

/** A candidate's dimensions when the picker reported them. */
function dimensions(selection: AttachmentCandidate): { width: number; height: number } | undefined {
  const { width, height } = selection as { width?: unknown; height?: unknown };
  return typeof width === "number" && typeof height === "number" && width > 0 && height > 0 ? { width, height } : undefined;
}

/**
 * Re-encode a picked or photographed image to the policy's JPEG (the vendor pipeline: size and pixel limits,
 * resize, quality ladder, metadata dropped by the re-encode), store it, and delete every plain file made on the way.
 */
export async function storeImage(
  env: CaptureEnv,
  question: InstrumentQuestion,
  selection: AttachmentCandidate,
  policy: ImageAttachmentPolicy,
  encodeJpeg: (uri: string, options: ImageEncodingOptions) => Promise<string>,
): Promise<ProcessedImageAttachmentReference> {
  const source = selection.uri;
  const dims = dimensions(selection);
  const mimeType = (selection as { mimeType?: unknown }).mimeType === "image/png" ? "image/png" : IMAGE_JPEG;
  try {
    const processed = await processNativeImageAttachment(
      { uri: source, name: typeof selection.name === "string" ? selection.name : "image.jpg" },
      {
        async getSize(uri) {
          return env.fileSize(uri);
        },
        read: (uri) => env.readBytes(uri),
        ...(dims ? { inspect: async () => ({ mimeType, ...dims }) } : {}),
        encodeJpeg: (uri, options) => encodeJpeg(uri, options),
        // The persisted "uri" is the opaque reference: the bytes go into the encrypted store, never a file.
        async persist(temporaryUri, name) {
          const id = name.replace(/\.jpg$/i, "");
          const bytes = await env.readBytes(temporaryUri);
          await saveAttachment(env.db, {
            id, draftId: env.draftId, projectId: env.projectId, question: question.name, kind: "image",
            mimeType: IMAGE_JPEG, ext: "jpg", bytes,
          });
          return REFERENCE_PREFIX + id;
        },
        async remove(uri) {
          env.removeFile(uri);
        },
      },
      { policy, createId: env.newId },
    );
    return processed;
  } finally {
    env.removeFile(source);
  }
}

const PDF_MAGIC = [0x25, 0x50, 0x44, 0x46, 0x2d]; // %PDF-

/** Keep a picked PDF as it is (5 MB, real PDF header) in the store; the server validates it further. */
export async function storePdf(
  env: CaptureEnv,
  question: InstrumentQuestion,
  selection: { uri: string; name?: string },
): Promise<RetainedPdfAttachmentReference> {
  try {
    const limit = WHO_VA_ATTACHMENT_POLICY.pdf.maxInputBytes;
    if (env.fileSize(selection.uri) > limit) throw new AttachmentProcessingError("pdf-input-too-large");
    const bytes = await env.readBytes(selection.uri);
    if (bytes.byteLength === 0 || bytes.byteLength > limit) throw new AttachmentProcessingError("pdf-input-too-large");
    if (!PDF_MAGIC.every((byte, index) => bytes[index] === byte)) throw new AttachmentProcessingError("pdf-type-not-allowed");
    const id = env.newId();
    try {
      await saveAttachment(env.db, {
        id, draftId: env.draftId, projectId: env.projectId, question: question.name, kind: "document",
        mimeType: "application/pdf", ext: "pdf", bytes,
      });
    } catch (error) {
      throw new AttachmentProcessingError("attachment-storage-failed", error);
    }
    return {
      id,
      uri: REFERENCE_PREFIX + id,
      name: `${id}.pdf`,
      originalName: selection.name ?? `${id}.pdf`,
      mimeType: "application/pdf",
      size: bytes.byteLength,
      originalRetained: true,
      processed: false,
      serverSideValidationRequired: true,
    };
  } finally {
    env.removeFile(selection.uri);
  }
}

/** A plain, short-lived copy of a stored file for the player or the image view; undefined when it is gone. */
export async function resolveStored(env: CaptureEnv, reference: AttachmentReference): Promise<string | undefined> {
  const id = referenceId(reference);
  if (!id) return undefined;
  const meta = await getAttachmentMeta(env.db, id);
  const bytes = meta ? await getAttachmentBytes(env.db, id) : null;
  return meta && bytes ? env.writePlaybackCopy(id, meta.ext, bytes) : undefined;
}

/** Delete a stored file when the form drops it (replaced, removed). A reference to a file this phone never held is left. */
export async function removeStored(env: CaptureEnv, reference: AttachmentReference): Promise<void> {
  const id = referenceId(reference);
  if (id) await deleteAttachment(env.db, id);
}
