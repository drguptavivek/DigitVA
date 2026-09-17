/**
 * Browser MediaRecorder adapter that captures audio and persists it through the
 * same binary store used by other web attachments.
 */
import { createDraftId } from "./draft.js";
import type { AudioAttachmentReference } from "./types.js";
import type { WebAttachmentBinaryStore } from "./web-attachments.js";

export type WebStoredAudioReference = AudioAttachmentReference;

export interface WebAudioRecordingSession {
  stop(): Promise<WebStoredAudioReference>;
  cancel(): void;
}

export interface WebAudioRecordingPolicy {
  maxDurationMs: number;
  maxBytes: number;
}

export const WHO_VA_WEB_AUDIO_POLICY: WebAudioRecordingPolicy = {
  maxDurationMs: 30 * 60 * 1000,
  maxBytes: 25 * 1024 * 1024
};

export interface StartWebAudioRecordingOptions {
  store: WebAttachmentBinaryStore;
  mediaDevices?: Pick<MediaDevices, "getUserMedia"> | undefined;
  MediaRecorderClass?: typeof MediaRecorder | undefined;
  createId?: (() => string) | undefined;
  now?: (() => number) | undefined;
  policy?: WebAudioRecordingPolicy | undefined;
  /** Request periodic encoded chunks so the byte ceiling is enforced while recording. */
  timesliceMs?: number | undefined;
}

function preferredAudioMimeType(MediaRecorderClass: typeof MediaRecorder): string | undefined {
  const candidates = ["audio/webm;codecs=opus", "audio/mp4", "audio/webm"];
  return candidates.find((mimeType) => MediaRecorderClass.isTypeSupported?.(mimeType));
}

function extensionForMimeType(mimeType: string): string {
  if (mimeType.includes("mp4")) return "m4a";
  if (mimeType.includes("ogg")) return "ogg";
  return "webm";
}

function stopStream(stream: MediaStream): void {
  for (const track of stream.getTracks()) track.stop();
}

export async function startWebAudioRecording(
  options: StartWebAudioRecordingOptions
): Promise<WebAudioRecordingSession> {
  const mediaDevices = options.mediaDevices ?? globalThis.navigator?.mediaDevices;
  const MediaRecorderClass = options.MediaRecorderClass ?? globalThis.MediaRecorder;
  if (!mediaDevices?.getUserMedia || !MediaRecorderClass) {
    throw new Error("Audio recording is not supported by this browser.");
  }

  const stream = await mediaDevices.getUserMedia({ audio: true });
  const mimeType = preferredAudioMimeType(MediaRecorderClass);
  let recorder: MediaRecorder;
  try {
    recorder = mimeType ? new MediaRecorderClass(stream, { mimeType }) : new MediaRecorderClass(stream);
    recorder.start(options.timesliceMs ?? 1_000);
  } catch (error) {
    stopStream(stream);
    throw error;
  }

  const chunks: Blob[] = [];
  const policy = options.policy ?? WHO_VA_WEB_AUDIO_POLICY;
  const startedAt = (options.now ?? Date.now)();
  let cancelled = false;
  let sizeError: Error | undefined;
  let resolveCompletion!: (value: WebStoredAudioReference) => void;
  let rejectCompletion!: (reason: Error) => void;
  const completion = new Promise<WebStoredAudioReference>((resolve, reject) => {
    resolveCompletion = resolve;
    rejectCompletion = reject;
  });
  void completion.catch(() => undefined);
  const durationTimer = setTimeout(() => {
    if (recorder.state !== "inactive") recorder.stop();
  }, policy.maxDurationMs);
  const releaseResources = () => {
    clearTimeout(durationTimer);
    stopStream(stream);
  };
  let totalBytes = 0;
  recorder.addEventListener("dataavailable", (event) => {
    if (cancelled || event.data.size <= 0) return;
    totalBytes += event.data.size;
    if (totalBytes > policy.maxBytes) {
      sizeError = new Error("The audio recording exceeded the configured size limit and was discarded.");
      chunks.length = 0;
      if (recorder.state !== "inactive") recorder.stop();
      return;
    }
    chunks.push(event.data);
  });
  recorder.addEventListener(
    "error",
    () => {
      releaseResources();
      rejectCompletion(new Error("The browser could not complete the audio recording."));
    },
    { once: true }
  );
  recorder.addEventListener(
    "stop",
    async () => {
      releaseResources();
      if (cancelled) {
        rejectCompletion(new Error("The audio recording was cancelled."));
        return;
      }
      if (sizeError) {
        rejectCompletion(sizeError);
        return;
      }
      const recordedMimeType = recorder.mimeType || mimeType || chunks[0]?.type || "audio/webm";
      const blob = new Blob(chunks, { type: recordedMimeType });
      chunks.length = 0;
      if (blob.size === 0) {
        rejectCompletion(new Error("No audio was recorded. Check the microphone and try again."));
        return;
      }
      const id = (options.createId ?? createDraftId)();
      const name = `${id}.${extensionForMimeType(recordedMimeType)}`;
      try {
        await options.store.save(id, blob);
        resolveCompletion({
          id,
          uri: `who-va-attachment:${id}`,
          name,
          originalName: name,
          mimeType: recordedMimeType,
          size: blob.size,
          durationMs: Math.min(policy.maxDurationMs, Math.max(0, (options.now ?? Date.now)() - startedAt)),
          processed: true
        } satisfies WebStoredAudioReference);
      } catch (error) {
        rejectCompletion(
          new Error("The audio recording could not be saved on this device.", { cause: error })
        );
      }
    },
    { once: true }
  );

  return {
    stop() {
      if (recorder.state !== "inactive") recorder.stop();
      return completion;
    },
    cancel() {
      cancelled = true;
      chunks.length = 0;
      if (recorder.state !== "inactive") recorder.stop();
      else releaseResources();
    }
  };
}
