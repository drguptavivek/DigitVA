/** The capture state machines with the recorder, files and dialogs faked: audio, image, PDF, playback copy, removal. Real SQLite. */
import { DatabaseSync } from "node:sqlite";

import {
  AUDIO_MAX_BYTES,
  AUDIO_MAX_MS,
  notAllowed,
  removeStored,
  resolveStored,
  startAudioRecording,
  storeImage,
  storePdf,
  type AudioEnv,
  type RecorderLike,
} from "../src/attachmentCapture";
import { draftAttachments, getAttachmentBytes } from "../src/attachmentStore";
import { migrate, type Db } from "../src/drafts";

function memoryDb(): Db {
  const db = new DatabaseSync(":memory:");
  return {
    execAsync: async (sql) => void db.exec(sql),
    runAsync: async (sql, params) => db.prepare(sql).run(...(params as never[])),
    getAllAsync: async <T,>(sql: string, params: unknown[]) => db.prepare(sql).all(...(params as never[])) as T[],
    getFirstAsync: async <T,>(sql: string, params: unknown[]) => (db.prepare(sql).get(...(params as never[])) as T | undefined) ?? null,
    closeAsync: async () => db.close(),
  };
}

const QUESTION = { name: "Id10476_audio" } as never;
const POLICY = { acceptedMimeTypes: ["image/jpeg", "image/png"], maxInputBytes: 10 * 1024 * 1024, maxOutputBytes: 2 * 1024 * 1024, maxPixels: 16_000_000, maxInputWidthOrHeight: 8192, maxOutputWidthOrHeight: 2048, jpegQualities: [0.82, 0.72] } as never;

/** A JPEG header the vendor inspector accepts: SOI, SOF0 with 40x30. */
const jpeg = (width = 40, height = 30) => new Uint8Array([0xff, 0xd8, 0xff, 0xc0, 0x00, 0x0b, 0x08, height >> 8, height & 255, width >> 8, width & 255, 1, 1, 0x11, 0, 0xff, 0xd9, 0, 0, 0]);

let db: Db;
let files: Map<string, Uint8Array>;
let removed: string[];
let ids: number;

function env(overrides: Partial<AudioEnv> = {}): AudioEnv {
  const recorder: RecorderLike = {
    uri: "file:///cache/rec.m4a",
    isRecording: false,
    prepareToRecordAsync: jest.fn(async () => undefined),
    record: jest.fn(function (this: RecorderLike) { (recorder as { isRecording: boolean }).isRecording = true; }),
    pause: jest.fn(() => { (recorder as { isRecording: boolean }).isRecording = false; }),
    stop: jest.fn(async () => { (recorder as { isRecording: boolean }).isRecording = false; }),
  };
  return {
    db, draftId: "draft-1", projectId: "P1",
    newId: () => `00000000-0000-4000-8000-${String(++ids).padStart(12, "0")}`,
    now: Date.now,
    readBytes: async (uri) => files.get(uri) ?? new Uint8Array(),
    fileSize: (uri) => files.get(uri)?.byteLength ?? 0,
    removeFile: (uri) => { if (uri) { removed.push(uri); files.delete(uri); } },
    writePlaybackCopy: (id, ext) => `file:///cache/va-media/${id}.${ext}`,
    recorder, ensureMicrophone: jest.fn(async () => undefined), setRecordingMode: jest.fn(async () => undefined),
    ...overrides,
  };
}

beforeEach(async () => {
  db = memoryDb();
  await migrate(db);
  files = new Map();
  removed = [];
  ids = 0;
  jest.useFakeTimers({ doNotFake: ["nextTick", "setImmediate"] });
});
afterEach(() => jest.useRealTimers());

describe("audio", () => {
  it("records, stops, stores the bytes in the encrypted store and deletes the plain file", async () => {
    const e = env();
    files.set("file:///cache/rec.m4a", new Uint8Array([1, 2, 3, 4]));
    const session = await startAudioRecording(e, QUESTION);
    expect(e.setRecordingMode).toHaveBeenCalledWith(true);
    jest.setSystemTime(Date.now() + 65_000);
    const reference = await session.stop();
    expect(reference).toMatchObject({ mimeType: "audio/mp4", size: 4, durationMs: 65_000, processed: true });
    expect(reference.uri).toBe(`who-va-attachment:${reference.id}`);
    expect(reference.uri).not.toContain("file:");
    expect([...(await getAttachmentBytes(db, reference.id!))!]).toEqual([1, 2, 3, 4]);
    expect(await draftAttachments(db, "draft-1")).toMatchObject([{ question: "Id10476_audio", kind: "audio", ext: "m4a", duration_ms: 65_000 }]);
    expect(removed).toEqual(["file:///cache/rec.m4a"]);
    expect(e.setRecordingMode).toHaveBeenLastCalledWith(false);
  });

  it("stops by itself at the duration limit and a later stop still saves that take once", async () => {
    const e = env();
    files.set("file:///cache/rec.m4a", new Uint8Array([9, 9]));
    const session = await startAudioRecording(e, QUESTION);
    await jest.advanceTimersByTimeAsync(AUDIO_MAX_MS + 5_000);
    expect(e.recorder.stop).toHaveBeenCalledTimes(1);
    const first = await session.stop();
    const second = await session.stop();
    expect(second).toBe(first);
    expect((first as { durationMs?: number }).durationMs).toBe(AUDIO_MAX_MS);
    expect(await draftAttachments(db, "draft-1")).toHaveLength(1);
  });

  it("pauses and resumes one take; paused time does not count toward the duration or the limit", async () => {
    const e = env();
    files.set("file:///cache/rec.m4a", new Uint8Array([1, 2, 3]));
    const session = await startAudioRecording(e, QUESTION);
    jest.setSystemTime(Date.now() + 10_000);
    session.pause!();
    expect(e.recorder.pause).toHaveBeenCalledTimes(1);
    expect(session.getState!()).toEqual({ elapsedMs: 10_000, paused: true, limitMs: AUDIO_MAX_MS });
    session.pause!(); // idempotent
    expect(e.recorder.pause).toHaveBeenCalledTimes(1);
    await jest.advanceTimersByTimeAsync(AUDIO_MAX_MS * 2); // a long pause never reaches the limit
    expect(e.recorder.stop).not.toHaveBeenCalled();
    expect(session.getState!().elapsedMs).toBe(10_000);
    session.resume!();
    expect(e.recorder.record).toHaveBeenCalledTimes(2);
    jest.setSystemTime(Date.now() + 5_000);
    expect(session.getState!()).toMatchObject({ elapsedMs: 15_000, paused: false });
    const reference = await session.stop();
    expect(reference).toMatchObject({ durationMs: 15_000, size: 3 });
    expect(e.recorder.stop).toHaveBeenCalledTimes(1);
    expect(await draftAttachments(db, "draft-1")).toHaveLength(1);
  });

  it("stops at the limit counted over several segments", async () => {
    const e = env();
    files.set("file:///cache/rec.m4a", new Uint8Array([9]));
    const session = await startAudioRecording(e, QUESTION);
    await jest.advanceTimersByTimeAsync(AUDIO_MAX_MS - 60_000);
    session.pause!();
    await jest.advanceTimersByTimeAsync(3_600_000);
    session.resume!();
    await jest.advanceTimersByTimeAsync(59_000);
    expect(e.recorder.stop).not.toHaveBeenCalled();
    await jest.advanceTimersByTimeAsync(2_000);
    expect(e.recorder.stop).toHaveBeenCalledTimes(1);
    expect(await draftAttachments(db, "draft-1")).toHaveLength(1);
    expect(((await session.stop()) as { durationMs?: number }).durationMs).toBe(AUDIO_MAX_MS);
  });

  it("saves or cancels a take that is paused (the recorder is stopped although it is not recording)", async () => {
    const e = env();
    files.set("file:///cache/rec.m4a", new Uint8Array([4]));
    const saved = await startAudioRecording(e, QUESTION);
    saved.pause!();
    await saved.stop();
    expect(e.recorder.stop).toHaveBeenCalledTimes(1);
    expect(await draftAttachments(db, "draft-1")).toHaveLength(1);

    const e2 = env();
    files.set("file:///cache/rec.m4a", new Uint8Array([4]));
    const dropped = await startAudioRecording(e2, QUESTION);
    dropped.pause!();
    await dropped.cancel();
    expect(e2.recorder.stop).toHaveBeenCalledTimes(1);
    expect(removed).toContain("file:///cache/rec.m4a");
  });

  it("an interruption pauses the take and keeps it; resume, save and the unsubscribe still work", async () => {
    let interrupt = () => {};
    const unwatch = jest.fn();
    const e = env({ watchInterruptions: (cb) => { interrupt = cb; return unwatch; } });
    files.set("file:///cache/rec.m4a", new Uint8Array([5, 5]));
    const session = await startAudioRecording(e, QUESTION);
    jest.setSystemTime(Date.now() + 4_000);
    interrupt();
    expect(e.recorder.pause).toHaveBeenCalledTimes(1);
    expect(session.getState!()).toMatchObject({ paused: true, elapsedMs: 4_000 });
    expect(e.recorder.stop).not.toHaveBeenCalled(); // nothing lost, nothing saved yet
    interrupt(); // a second event while paused does nothing
    expect(e.recorder.pause).toHaveBeenCalledTimes(1);
    session.resume!();
    jest.setSystemTime(Date.now() + 1_000);
    const reference = await session.stop();
    expect(reference).toMatchObject({ durationMs: 5_000 });
    expect(unwatch).toHaveBeenCalled();
  });

  it("an interruption the recorder cannot pause does not throw and the take is still saved by stop", async () => {
    let interrupt = () => {};
    const e = env({ watchInterruptions: (cb) => { interrupt = cb; return () => {}; } });
    files.set("file:///cache/rec.m4a", new Uint8Array([5]));
    const session = await startAudioRecording(e, QUESTION);
    (e.recorder.pause as jest.Mock).mockImplementationOnce(() => { throw new Error("already stopped"); });
    expect(() => interrupt()).not.toThrow();
    await expect(session.stop()).resolves.toMatchObject({ size: 1 });
  });

  it("refuses an empty or oversized take and still deletes the plain file", async () => {
    const e = env();
    const session = await startAudioRecording(e, QUESTION); // no bytes at the uri
    await expect(session.stop()).rejects.toThrow("audio_empty");
    expect(removed).toContain("file:///cache/rec.m4a");

    const big = env({ fileSize: () => AUDIO_MAX_BYTES + 1 });
    files.set("file:///cache/rec.m4a", new Uint8Array([1]));
    await expect((await startAudioRecording(big, QUESTION)).stop()).rejects.toThrow("audio_too_large");
    expect(await draftAttachments(db, "draft-1")).toEqual([]);
  });

  it("cancel drops the take and stores nothing; after the limit already saved it, cancel deletes that file", async () => {
    const e = env();
    files.set("file:///cache/rec.m4a", new Uint8Array([1, 2]));
    const session = await startAudioRecording(e, QUESTION);
    await session.cancel();
    expect(e.recorder.stop).toHaveBeenCalledTimes(1);
    expect(removed).toContain("file:///cache/rec.m4a");
    expect(await draftAttachments(db, "draft-1")).toEqual([]);

    const e2 = env();
    files.set("file:///cache/rec.m4a", new Uint8Array([1, 2]));
    const limited = await startAudioRecording(e2, QUESTION);
    await jest.advanceTimersByTimeAsync(AUDIO_MAX_MS + 1);
    expect(await draftAttachments(db, "draft-1")).toHaveLength(1);
    await limited.cancel();
    expect(await draftAttachments(db, "draft-1")).toEqual([]);
  });

  it("deletes the plain take when the recorder fails to stop, and when a cancel's stop fails", async () => {
    const e = env();
    files.set("file:///cache/rec.m4a", new Uint8Array([1, 2]));
    const session = await startAudioRecording(e, QUESTION);
    (e.recorder.stop as jest.Mock).mockRejectedValueOnce(new Error("boom"));
    await expect(session.stop()).rejects.toThrow("boom");
    expect(removed).toContain("file:///cache/rec.m4a");

    removed = [];
    const e2 = env();
    files.set("file:///cache/rec.m4a", new Uint8Array([1, 2]));
    const s2 = await startAudioRecording(e2, QUESTION);
    (e2.recorder.stop as jest.Mock).mockRejectedValueOnce(new Error("boom"));
    await expect(s2.cancel()).rejects.toThrow("boom");
    expect(removed).toContain("file:///cache/rec.m4a");
  });

  it("does not start recording when the microphone is refused, and leaves the recording mode off", async () => {
    const e = env({ ensureMicrophone: jest.fn(async () => { throw notAllowed("microphone_denied"); }) });
    await expect(startAudioRecording(e, QUESTION)).rejects.toMatchObject({ name: "NotAllowedError" });
    expect(e.recorder.prepareToRecordAsync).not.toHaveBeenCalled();
    expect(e.setRecordingMode).not.toHaveBeenCalled();
  });

  it("turns the recording mode off again when the recorder will not start", async () => {
    const e = env();
    (e.recorder.prepareToRecordAsync as jest.Mock).mockRejectedValue(new Error("busy"));
    await expect(startAudioRecording(e, QUESTION)).rejects.toThrow("busy");
    expect(e.setRecordingMode).toHaveBeenLastCalledWith(false);
  });
});

describe("images", () => {
  const encode = jest.fn();
  beforeEach(() => {
    encode.mockReset();
    encode.mockImplementation(async () => {
      files.set("file:///cache/out.jpg", jpeg(20, 15));
      return "file:///cache/out.jpg";
    });
  });

  it("re-encodes, stores the JPEG as an opaque reference, and deletes the source and the re-encoded file", async () => {
    const e = env();
    files.set("file:///cache/pick.jpg", jpeg(4000, 3000));
    const reference = await storeImage(e, { name: "imagenarr" } as never, { uri: "file:///cache/pick.jpg", name: "pick.jpg", mimeType: "image/jpeg", width: 4000, height: 3000 }, POLICY, encode);
    expect(reference).toMatchObject({ mimeType: "image/jpeg", processed: true, width: 20, height: 15 });
    expect(reference.uri).toBe(`who-va-attachment:${reference.id}`);
    expect(reference.name).toBe(`${reference.id}.jpg`);
    expect(encode.mock.calls[0]![1]).toMatchObject({ width: 2048, height: 1536 });
    expect(await draftAttachments(db, "draft-1")).toMatchObject([{ id: reference.id, question: "imagenarr", kind: "image", mime_type: "image/jpeg" }]);
    expect(removed).toEqual(expect.arrayContaining(["file:///cache/out.jpg", "file:///cache/pick.jpg"]));
  });

  it("refuses a file that is not a real image without storing anything", async () => {
    const e = env();
    files.set("file:///cache/fake.jpg", new TextEncoder().encode("<html>not an image</html> padding padding"));
    await expect(storeImage(e, { name: "imagenarr" } as never, { uri: "file:///cache/fake.jpg", name: "fake.jpg" }, POLICY, encode)).rejects.toMatchObject({ code: "image-type-not-allowed" });
    expect(await draftAttachments(db, "draft-1")).toEqual([]);
    expect(removed).toContain("file:///cache/fake.jpg");
  });

  it("refuses an image over the input size limit before decoding it", async () => {
    const e = env({ fileSize: () => 11 * 1024 * 1024 });
    files.set("file:///cache/huge.jpg", jpeg());
    await expect(storeImage(e, { name: "imagenarr" } as never, { uri: "file:///cache/huge.jpg", name: "huge.jpg" }, POLICY, encode)).rejects.toMatchObject({ code: "image-input-too-large" });
    expect(encode).not.toHaveBeenCalled();
  });
});

describe("documents", () => {
  const pdf = (extra = 10) => new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d, ...new Array(extra).fill(0x20)]);

  it("keeps a real PDF as it is and refuses a renamed or oversized one", async () => {
    const e = env();
    files.set("file:///cache/c.pdf", pdf());
    const reference = await storePdf(e, { name: "custom_medical_certificate_upload" } as never, { uri: "file:///cache/c.pdf", name: "certificate.pdf" });
    expect(reference).toMatchObject({ mimeType: "application/pdf", originalRetained: true, processed: false, originalName: "certificate.pdf" });
    expect(await draftAttachments(db, "draft-1")).toMatchObject([{ kind: "document", ext: "pdf" }]);
    expect(removed).toContain("file:///cache/c.pdf");

    files.set("file:///cache/x.pdf", new TextEncoder().encode("MZ executable renamed.pdf"));
    await expect(storePdf(e, { name: "q" } as never, { uri: "file:///cache/x.pdf" })).rejects.toMatchObject({ code: "pdf-type-not-allowed" });
    const big = env({ fileSize: () => 6 * 1024 * 1024 });
    files.set("file:///cache/y.pdf", pdf());
    await expect(storePdf(big, { name: "q" } as never, { uri: "file:///cache/y.pdf" })).rejects.toMatchObject({ code: "pdf-input-too-large" });
    expect(await draftAttachments(db, "draft-1")).toHaveLength(1);
  });
});

describe("playback copy and removal", () => {
  it("makes a copy only for a file the phone holds, and removes the stored file on request", async () => {
    const e = env();
    files.set("file:///cache/rec.m4a", new Uint8Array([5, 6]));
    const reference = await (await startAudioRecording(e, QUESTION)).stop();
    expect(await resolveStored(e, reference)).toBe(`file:///cache/va-media/${reference.id}.m4a`);
    expect(await resolveStored(e, { uri: "who-va-attachment:99999999-9999-4999-8999-999999999999" })).toBeUndefined();
    expect(await resolveStored(e, { uri: "file:///elsewhere.m4a" })).toBeUndefined();
    await removeStored(e, reference);
    expect(await draftAttachments(db, "draft-1")).toEqual([]);
    expect(await resolveStored(e, reference)).toBeUndefined();
  });
});
