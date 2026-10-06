// The intake page's encrypted attachment buffer and uploader, under `node --test`.
//
// The buffer and uploader take their storage, crypto, clock, fetch and timers as
// parameters, so the real code runs here with node's WebCrypto and an in-memory
// backing: no DOM, no IndexedDB. What these hold in place is the policy in
// docs/policy/web-intake.md "Attachments": nothing stored in the clear, a
// non-extractable key, 25 MB and the type list checked before storing, the
// seven-day sweep, delete-on-confirm and wipe-on-sign-out.
//
// Run: npm run test:web (from tooling/who-va-2022).

import assert from "node:assert/strict";
import test from "node:test";

import {
  BufferError,
  AMR_MAX_BYTES,
  MAX_AGE_MS,
  MAX_BYTES,
  WARN_BEFORE_MS,
  createBuffer,
  createUploader,
  detectType,
} from "../../../app/static/js/intake/attachment_buffer.js";

const DAY = 24 * 60 * 60 * 1000;
const bytes = (...head) => new Uint8Array([...head, ...new Array(64).fill(0)]);
const WEBM = Uint8Array.from([0x1a, 0x45, 0xdf, 0xa3, ...Buffer.from("....webm....")]);
const PNG = bytes(0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a);
const SECRET = Buffer.from("the respondent said the deceased was called Bina");

function memoryBacking() {
  const stores = { keys: new Map(), files: new Map() };
  return {
    stores,
    get: async (s, k) => stores[s].get(k),
    put: async (s, k, v) => void stores[s].set(k, v),
    del: async (s, k) => void stores[s].delete(k),
    all: async (s) => [...stores[s].values()],
    allKeys: async (s) => [...stores[s].keys()],
  };
}

function makeBuffer({ userId = "user-1", backing = memoryBacking(), clock = { t: 1_000_000_000_000 } } = {}) {
  return { backing, clock, buffer: createBuffer({ userId, draftId: "draft-1", backing, now: () => clock.t }) };
}

const pdf = (text = SECRET) => new Blob([Buffer.from("%PDF-1.4\n"), text], { type: "application/pdf" });

test("a file is encrypted at rest, the key cannot be exported, and it decrypts back", async () => {
  const { buffer, backing } = makeBuffer();
  await buffer.save("a1", pdf());

  const record = backing.stores.files.get("a1");
  assert.equal(Buffer.from(record.data).includes(SECRET), false, "plaintext found in the stored ciphertext");
  assert.equal(record.iv.length, 12);
  assert.equal(JSON.stringify(record).includes("Bina"), false);

  const key = backing.stores.keys.get("user-1");
  assert.equal(key.extractable, false);
  await assert.rejects(crypto.subtle.exportKey("raw", key));

  const back = await buffer.load("a1");
  assert.equal(back.type, "application/pdf");
  assert.deepEqual(Buffer.from(await back.arrayBuffer()), Buffer.concat([Buffer.from("%PDF-1.4\n"), SECRET]));
});

test("each save uses a fresh IV and the same per-user key", async () => {
  const { buffer, backing } = makeBuffer();
  await buffer.save("a1", pdf());
  await buffer.save("a2", pdf());
  assert.notDeepEqual(backing.stores.files.get("a1").iv, backing.stores.files.get("a2").iv);
  assert.equal(backing.stores.keys.size, 1);
});

test("another user cannot read the record, and a record moved to another id will not decrypt", async () => {
  const { buffer, backing } = makeBuffer();
  await buffer.save("a1", pdf());
  const other = createBuffer({ userId: "user-2", draftId: "d", backing });
  assert.equal(await other.load("a1"), undefined);
  assert.deepEqual(await other.entries(), []);

  backing.stores.files.set("a2", { ...backing.stores.files.get("a1"), id: "a2" });
  await assert.rejects(buffer.load("a2"));
});

test("the draft, the id and the type are bound into the ciphertext", async () => {
  const { buffer, backing } = makeBuffer();
  await buffer.save("a1", pdf());
  const record = backing.stores.files.get("a1");
  assert.equal(record.draftId, "draft-1");
  assert.equal((await buffer.load("a1")).type, "application/pdf");

  backing.stores.files.set("a1", { ...record, draftId: "another-draft" });
  await assert.rejects(buffer.load("a1"), "moved to another draft");
  backing.stores.files.set("a1", { ...record, type: "audio/webm" });
  await assert.rejects(buffer.load("a1"), "relabelled as another type");
  backing.stores.files.set("a1", record);
  assert.equal((await buffer.load("a1")).size, pdf().size);
});

test("an AMR recording over 5 MB is refused on the device, other audio is not", async () => {
  const { buffer, backing } = makeBuffer();
  const amr = (size) => new Blob([Buffer.from("#!AMR\n"), Buffer.alloc(size)]);
  await assert.rejects(buffer.save("big", amr(AMR_MAX_BYTES)), (e) => e.code === "too_large" && /5 MB/.test(e.message));
  assert.equal(backing.stores.files.size, 0);
  await buffer.save("ok", amr(1000));
  assert.equal((await buffer.load("ok")).type, "audio/amr");
});

test("25 MB, empty files and types outside the list are refused before anything is stored", async () => {
  const { buffer, backing } = makeBuffer();
  const refuse = async (blob, code) => {
    await assert.rejects(buffer.save("x", blob), (e) => e instanceof BufferError && e.code === code);
  };
  await refuse({ size: MAX_BYTES + 1, slice: () => new Blob([PNG]) }, "too_large");
  await refuse(new Blob([]), "empty");
  await refuse(new Blob([Buffer.from("MZ\x90\x00 not allowed")]), "bad_type");
  assert.equal(backing.stores.files.size, 0);
  assert.equal(backing.stores.keys.size, 0, "no key is made for a file that is refused");

  await buffer.save("ok", new Blob([PNG], { type: "text/plain" }));
  assert.equal((await buffer.load("ok")).type, "image/png", "type comes from the bytes");
});

test("detectType knows the owner's list and nothing else", () => {
  assert.equal(detectType(WEBM), "audio/webm");
  assert.equal(detectType(bytes(0xff, 0xd8, 0xff)), "image/jpeg");
  assert.equal(detectType(Buffer.from("RIFF\x00\x00\x00\x00WAVEfmt ")), "audio/wav");
  assert.equal(detectType(Buffer.from("#!AMR\n")), "audio/amr");
  assert.equal(detectType(Buffer.from("ID3\x04")), "audio/mpeg");
  assert.equal(detectType(bytes(0xff, 0xfb, 0x90)), "audio/mpeg");
  assert.equal(detectType(Buffer.from("\x00\x00\x00\x20ftypM4A \x00")), "audio/mp4");
  assert.equal(detectType(bytes(0xff, 0xf1, 0x50)), null, "AAC ADTS is not MPEG audio");
  assert.equal(detectType(Buffer.from("<svg>")), null);
});

test("the sweep names files past seven days and files within a day of it", async () => {
  const { buffer, clock } = makeBuffer();
  const start = clock.t;
  await buffer.save("old", pdf());
  clock.t = start + 3 * DAY;
  await buffer.save("mid", pdf());
  clock.t = start + 6.5 * DAY;
  await buffer.save("new", pdf());

  clock.t = start + MAX_AGE_MS - WARN_BEFORE_MS / 2; // 6.5 days in: "old" is within a day of 7
  let swept = await buffer.sweep();
  assert.deepEqual(swept.expired.map((e) => e.id), []);
  assert.deepEqual(swept.expiring.map((e) => e.id), ["old"]);

  clock.t = start + MAX_AGE_MS + 1000;
  swept = await buffer.sweep();
  assert.deepEqual(swept.expired.map((e) => e.id), ["old"]);
  assert.deepEqual(swept.expiring.map((e) => e.id), []);

  // The caller warns, then removes the expired ones.
  for (const e of swept.expired) await buffer.remove(e.id);
  assert.deepEqual((await buffer.listIds()).sort(), ["mid", "new"]);
});

test("sign-out wipes every file and key; a different user's leftovers go first", async () => {
  const { buffer, backing } = makeBuffer();
  await buffer.save("mine", pdf());
  const other = createBuffer({ userId: "user-2", draftId: "d", backing });
  await other.save("theirs", pdf());
  assert.equal(backing.stores.keys.size, 2);

  await buffer.wipeOthers();
  assert.deepEqual([...backing.stores.files.keys()], ["mine"]);
  assert.deepEqual([...backing.stores.keys.keys()], ["user-1"]);

  await buffer.wipe();
  assert.equal(backing.stores.files.size, 0);
  assert.equal(backing.stores.keys.size, 0);
  // A new key is made on next use; the old files are unreadable by design.
  await buffer.save("again", pdf());
  assert.equal(backing.stores.keys.size, 1);
});

function uploaderFor(buffer, responses, extra = {}) {
  const calls = [];
  const timers = [];
  const events = [];
  const uploader = createUploader({
    buffer,
    apiBase: (d) => `/api/v1/intake/drafts/${d}`,
    csrf: () => "tok",
    fetchImpl: async (url, init) => {
      calls.push({ url, init });
      const next = responses.shift();
      if (next instanceof Error) throw next;
      return { status: next, json: async () => ({ code: "x", error: "refused" }) };
    },
    setTimer: (fn, ms) => (timers.push({ fn, ms }), timers.length),
    clearTimer: () => {},
    onEvent: (e) => events.push(e),
    ...extra,
  });
  return { uploader, calls, timers, events };
}

test("the server's confirmation deletes the device copy; the request is the contract", async () => {
  const { buffer } = makeBuffer();
  await buffer.save("a1", pdf());
  const { uploader, calls, events } = uploaderFor(buffer, [201]);
  await uploader.flush();

  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "/api/v1/intake/drafts/draft-1/attachments/a1");
  assert.equal(calls[0].init.method, "PUT");
  assert.equal(calls[0].init.headers["X-CSRFToken"], "tok");
  assert.equal(calls[0].init.headers["Content-Type"], "application/octet-stream");
  assert.equal(calls[0].init.body.size, pdf().size);
  assert.deepEqual(await buffer.listIds(), []);
  assert.deepEqual(events.map((e) => e.type), ["confirmed"]);
});

test("a server failure or a lost network keeps the file and retries with doubling backoff", async () => {
  const { buffer } = makeBuffer();
  await buffer.save("a1", pdf());
  const { uploader, timers } = uploaderFor(buffer, [503, new TypeError("network"), 200]);

  await uploader.flush();
  assert.deepEqual(await buffer.listIds(), ["a1"]);
  assert.equal(timers.length, 1);
  assert.equal(timers[0].ms, 2000);

  // The timer's callback is the retry; let it run to completion.
  const until = async (done) => {
    for (let i = 0; i < 200 && !(await done()); i += 1) await new Promise((resolve) => setTimeout(resolve, 5));
  };
  timers.shift().fn();
  await until(() => timers.length === 1);
  assert.deepEqual(await buffer.listIds(), ["a1"]);
  assert.equal(timers[0].ms, 4000);

  timers.shift().fn();
  await until(async () => (await buffer.listIds()).length === 0);
  assert.deepEqual(await buffer.listIds(), [], "sent on the third try");
});

test("a 413, 415 or 422 can never succeed: the file is removed and reported per file", async () => {
  for (const status of [413, 415, 422]) {
    const { buffer } = makeBuffer();
    await buffer.save("a1", pdf());
    const { uploader, events, timers } = uploaderFor(buffer, [status]);
    await uploader.flush();
    assert.deepEqual(await buffer.listIds(), [], String(status));
    assert.equal(timers.length, 0);
    assert.equal(events[0].type, "rejected");
    assert.equal(events[0].status, status);
    assert.equal(events[0].id, "a1");
  }
});

test("a 404 or 409 (draft gone or closed) KEEPS the encrypted copy, reports it and does not retry", async () => {
  for (const status of [404, 409]) {
    const { buffer } = makeBuffer();
    await buffer.save("a1", pdf());
    const { uploader, events, timers } = uploaderFor(buffer, [status]);
    await uploader.flush();
    assert.deepEqual(await buffer.listIds(), ["a1"], `${status} must not delete the file`);
    assert.equal(timers.length, 0, "no backoff timer");
    assert.equal(events[0].type, "held");
    assert.equal(events[0].status, status);
    assert.equal(events[0].fileType, "application/pdf");
    assert.equal((await buffer.load("a1")).size, pdf().size, "still decryptable");
  }
});

test("the upload carries the SHA-256 of the file", async () => {
  const { buffer } = makeBuffer();
  await buffer.save("a1", pdf());
  const { uploader, calls } = uploaderFor(buffer, [201]);
  await uploader.flush();
  const expected = Buffer.from(await crypto.subtle.digest("SHA-256", await pdf().arrayBuffer())).toString("hex");
  assert.equal(calls[0].init.headers["X-Content-SHA256"], expected);
});

test("nothing is sent while offline, and the file waits", async () => {
  const { buffer } = makeBuffer();
  await buffer.save("a1", pdf());
  const { uploader, calls, timers } = uploaderFor(buffer, [], { isOnline: () => false });
  await uploader.flush();
  assert.equal(calls.length, 0);
  assert.deepEqual(await buffer.listIds(), ["a1"]);
  assert.equal(timers.length, 1);
  assert.equal(await uploader.pending("draft-1"), 1);
  assert.equal(await uploader.pending("other-draft"), 0);
});

test("a file saved while a send is running is picked up by the same flush", async () => {
  const { buffer } = makeBuffer();
  await buffer.save("a1", pdf());
  const responses = [200, 200];
  let release;
  const gate = new Promise((r) => (release = r));
  const calls = [];
  const uploader = createUploader({
    buffer,
    apiBase: (d) => `/d/${d}`,
    csrf: () => "t",
    fetchImpl: async (url) => {
      calls.push(url);
      if (calls.length === 1) await gate;
      return { status: responses.shift(), json: async () => ({}) };
    },
    setTimer: () => 0,
    clearTimer: () => {},
  });
  const running = uploader.flush();
  await buffer.save("a2", pdf());
  const second = uploader.flush();
  release();
  await Promise.all([running, second]);
  assert.deepEqual(calls, ["/d/draft-1/attachments/a1", "/d/draft-1/attachments/a2"]);
  assert.deepEqual(await buffer.listIds(), []);
});

test("nothing the platform adapter returns carries the picked file's name", async () => {
  const { createAttachmentPlatform } = await import("../../../app/static/js/intake/attachment_platform.js");
  const { buffer } = makeBuffer();
  const WhoVa = {
    WHO_VA_ATTACHMENT_POLICY: { image: { acceptedMimeTypes: ["image/jpeg"], maxInputBytes: 1 } },
    createDraftId: () => "pdf-id",
    processWebImageAttachment: async (file) => ({ id: "img-id", uri: "who-va-attachment:img-id", name: "img-id.jpg", originalName: file.name, mimeType: "image/jpeg" }),
    startWebAudioRecording: async () => ({
      stop: async () => ({ id: "aud-id", name: "aud-id.webm", originalName: "ramesh_voice.webm" }),
      cancel() {},
    }),
  };
  const file = (name, bytes) => Object.assign(new Blob([bytes]), { name });
  let picked;
  const platform = createAttachmentPlatform({
    WhoVa, buffer, uploader: { flush: async () => {} }, attachmentUrl: (id) => id, pick: async () => picked,
  });

  picked = file("ramesh_kumar_death_cert.pdf", Buffer.from("%PDF-1.4 x"));
  const pdfRef = await platform.selectFile({}, {}, ["application/pdf"]);
  assert.equal(pdfRef.originalName, "pdf-id.pdf");
  assert.equal(JSON.stringify(pdfRef).includes("ramesh"), false);

  picked = file("ramesh_photo.jpg", Buffer.from("jpg"));
  const imageRef = await platform.selectImage();
  assert.equal(imageRef.originalName, "img-id.jpg");

  const session = await platform.startAudioRecording();
  const audioRef = await session.stop();
  assert.equal(JSON.stringify(audioRef).includes("ramesh"), false);
  assert.equal(audioRef.originalName, "aud-id.webm");
});
