// The encrypted on-device buffer for intake attachments, and its uploader.
//
// Policy: docs/policy/web-intake.md, "Attachments" (owner, 2026-10-06). A file
// the interviewer records or attaches is encrypted (AES-GCM, a non-extractable
// per-user key kept as a CryptoKey in IndexedDB) before anything is written,
// sent to the server when the network allows, and deleted from the device once
// the server confirms. An unsent file older than seven days is deleted after a
// visible warning. Nothing is ever stored in the clear.
//
// No DOM here: the storage backing, crypto, clock, fetch and timers are all
// injected, so the node tests in tooling/who-va-2022/tests exercise the real
// code (WebCrypto is built into node).

export const MAX_BYTES = 25 * 1024 * 1024;
// The server converts an AMR recording in the request, so it caps it lower.
export const AMR_MAX_BYTES = 5 * 1024 * 1024;
export const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
// A file this close to MAX_AGE_MS is warned about the day before.
export const WARN_BEFORE_MS = 24 * 60 * 60 * 1000;
const RETRY_FIRST_MS = 2000;
const RETRY_MAX_MS = 5 * 60 * 1000;
// The server refuses these for good and the file can never be accepted: it is
// dropped, with a per-file message.
const DROPPED = new Set([413, 415, 422]);
// The draft is gone (404) or no longer open (409): the file may still matter to
// the interviewer, so it is KEPT, reported, and not retried by the backoff timer.
const HELD = new Set([404, 409]);
const M4A_BRANDS = ["M4A ", "M4B ", "mp42", "mp41", "isom", "iso2", "iso5", "iso6", "dash"];

export class BufferError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "BufferError";
    this.code = code;
  }
}

const ascii = (bytes, from, to) => String.fromCharCode(...bytes.slice(from, to));

/** The accepted type of a file from its leading bytes (the server's table), or null. */
export function detectType(bytes) {
  const b = bytes;
  if (b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff) return "image/jpeg";
  if (ascii(b, 0, 8) === "\x89PNG\r\n\x1a\n") return "image/png";
  if (ascii(b, 0, 5) === "%PDF-") return "application/pdf";
  if (ascii(b, 0, 5) === "#!AMR") return "audio/amr";
  if (ascii(b, 0, 4) === "RIFF" && ascii(b, 8, 12) === "WAVE") return "audio/wav";
  if (b[0] === 0x1a && b[1] === 0x45 && b[2] === 0xdf && b[3] === 0xa3 && ascii(b, 0, 64).includes("webm")) return "audio/webm";
  if (ascii(b, 4, 8) === "ftyp" && M4A_BRANDS.includes(ascii(b, 8, 12))) return "audio/mp4";
  if (ascii(b, 0, 3) === "ID3" || (b[0] === 0xff && (b[1] & 0xe0) === 0xe0 && (b[1] & 0x06) !== 0)) return "audio/mpeg";
  return null;
}

/** An IndexedDB-backed `{get, put, del, all}` over the named object stores. */
export function createIdbBacking(indexedDB, name = "digitva-intake-attachments") {
  let opened;
  const open = () =>
    (opened ??= new Promise((resolve, reject) => {
      const request = indexedDB.open(name, 1);
      request.onupgradeneeded = () => {
        request.result.createObjectStore("keys");
        request.result.createObjectStore("files");
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    }));
  const run = async (store, mode, action) => {
    const db = await open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(store, mode);
      const request = action(tx.objectStore(store));
      tx.oncomplete = () => resolve(request?.result);
      tx.onerror = tx.onabort = () => reject(tx.error);
    });
  };
  return {
    get: (store, key) => run(store, "readonly", (s) => s.get(key)),
    put: (store, key, value) => run(store, "readwrite", (s) => s.put(value, key)),
    del: (store, key) => run(store, "readwrite", (s) => s.delete(key)),
    all: (store) => run(store, "readonly", (s) => s.getAll()),
    allKeys: (store) => run(store, "readonly", (s) => s.getAllKeys()),
  };
}

/**
 * The buffer for one signed-in user. `draftId` is the draft this page serves;
 * a file keeps the draft it was captured for, so one left over from an earlier
 * page is still sent to its own draft.
 */
export function createBuffer({ userId, draftId, backing, crypto = globalThis.crypto, now = Date.now }) {
  let keyPromise;
  // The draft, the id and the type are authenticated with the bytes: a record
  // moved to another draft, id or type does not decrypt.
  const aad = (id, forDraft, type) => new TextEncoder().encode(`${userId}|${forDraft}|${id}|${type}`);

  const key = () =>
    (keyPromise ??= (async () => {
      const stored = await backing.get("keys", userId);
      if (stored) return stored;
      // extractable: false -- script can use the key but never read it out.
      const fresh = await crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
      await backing.put("keys", userId, fresh);
      return fresh;
    })());

  return {
    /** Refuses a file over 25 MB or outside the type list before anything is stored. */
    async validate(blob) {
      if (blob.size > MAX_BYTES) throw new BufferError("too_large", "This file is larger than 25 MB.");
      if (blob.size === 0) throw new BufferError("empty", "This file is empty.");
      const head = new Uint8Array(await blob.slice(0, 64).arrayBuffer());
      const type = detectType(head);
      if (!type) throw new BufferError("bad_type", "Only audio, JPEG or PNG images, and PDF files can be attached.");
      if (type === "audio/amr" && blob.size > AMR_MAX_BYTES) throw new BufferError("too_large", "An AMR recording may be at most 5 MB.");
      return type;
    },

    async save(id, blob, forDraft = draftId) {
      const type = await this.validate(blob);
      const iv = crypto.getRandomValues(new Uint8Array(12));
      const data = await crypto.subtle.encrypt({ name: "AES-GCM", iv, additionalData: aad(id, forDraft, type) }, await key(), await blob.arrayBuffer());
      await backing.put("files", id, { id, userId, draftId: forDraft, iv, data, type, size: blob.size, createdAt: now() });
    },

    async load(id) {
      const record = await backing.get("files", id);
      if (!record || record.userId !== userId) return undefined;
      const plain = await crypto.subtle.decrypt(
        { name: "AES-GCM", iv: record.iv, additionalData: aad(id, record.draftId, record.type) }, await key(), record.data);
      return new Blob([plain], { type: record.type });
    },

    async remove(id) {
      await backing.del("files", id);
    },

    /** Metadata of this user's held files; never the bytes. */
    async entries() {
      const records = await backing.all("files");
      return records
        .filter((r) => r.userId === userId)
        .map(({ id, draftId: d, type, size, createdAt }) => ({ id, draftId: d, type, size, createdAt }));
    },

    async listIds() {
      return (await this.entries()).map((e) => e.id);
    },

    /** `{expired, expiring}`: files past seven days, and files that will be within a day. */
    async sweep() {
      const t = now();
      const entries = await this.entries();
      return {
        expired: entries.filter((e) => t - e.createdAt > MAX_AGE_MS),
        expiring: entries.filter((e) => t - e.createdAt <= MAX_AGE_MS && t - e.createdAt > MAX_AGE_MS - WARN_BEFORE_MS),
      };
    },

    /** Everything, every user's, and every key: what sign-out does. */
    async wipe() {
      for (const record of await backing.all("files")) await backing.del("files", record.id);
      for (const k of await backing.allKeys("keys")) await backing.del("keys", k);
      keyPromise = undefined;
    },

    /** What another user left in this browser: files and their keys, before anything else. */
    async wipeOthers() {
      for (const record of await backing.all("files")) if (record.userId !== userId) await backing.del("files", record.id);
      for (const k of await backing.allKeys("keys")) if (k !== userId) await backing.del("keys", k);
    },
  };
}

/**
 * Sends held files to `PUT <apiBase(draftId)>/attachments/<id>` and deletes each
 * once the server answers 200/201. A transient failure (network, 5xx, 429,
 * a stale CSRF token or session) retries with backoff, 2 s doubling to 5 min. A
 * 413, 415 or 422 can never succeed: the file is removed and reported. A 404 or
 * 409 (the draft is gone or closed) KEEPS the file, reports it and does not
 * retry: the interviewer decides, or the seven-day sweep removes it.
 */
export function createUploader({
  buffer,
  apiBase,
  csrf,
  fetchImpl = globalThis.fetch,
  isOnline = () => globalThis.navigator?.onLine !== false,
  setTimer = setTimeout,
  clearTimer = clearTimeout,
  onEvent = () => {},
}) {
  let inFlight;
  let dirty = false;
  let timer;
  let failures = 0;

  const hex = (buf) => [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");

  async function sendOne(entry) {
    const blob = await buffer.load(entry.id);
    if (!blob) {
      await buffer.remove(entry.id); // unreadable (another key): nothing can send it
      return "gone";
    }
    let response;
    try {
      // The checksum lets the server refuse a body changed in transit and tell
      // a retry of this file from another file under the same id.
      const sha = hex(await crypto.subtle.digest("SHA-256", await blob.arrayBuffer()));
      response = await fetchImpl(`${apiBase(entry.draftId)}/attachments/${encodeURIComponent(entry.id)}`, {
        method: "PUT",
        headers: { "X-CSRFToken": csrf(), "Content-Type": "application/octet-stream", "X-Content-SHA256": sha },
        credentials: "same-origin",
        body: blob,
      });
    } catch (error) {
      return "retry";
    }
    const detail = { id: entry.id, draftId: entry.draftId, fileType: entry.type, createdAt: entry.createdAt };
    if (response.status === 200 || response.status === 201) {
      await buffer.remove(entry.id);
      onEvent({ type: "confirmed", ...detail });
      return "sent";
    }
    if (DROPPED.has(response.status)) {
      const body = await response.json().catch(() => ({}));
      await buffer.remove(entry.id);
      onEvent({ type: "rejected", ...detail, status: response.status, code: body.code, message: body.error });
      return "rejected";
    }
    if (HELD.has(response.status)) {
      const body = await response.json().catch(() => ({}));
      onEvent({ type: "held", ...detail, status: response.status, code: body.code, message: body.error });
      return "held";
    }
    return "retry";
  }

  async function pass() {
    let retry = false;
    for (const entry of await buffer.entries()) {
      if (!isOnline()) {
        retry = true;
        break;
      }
      if ((await sendOne(entry)) === "retry") retry = true;
    }
    if (!retry) {
      failures = 0;
      return;
    }
    failures += 1;
    if (timer === undefined) {
      const delay = Math.min(RETRY_FIRST_MS * 2 ** (failures - 1), RETRY_MAX_MS);
      timer = setTimer(() => {
        timer = undefined;
        flush().catch(() => {});
      }, delay);
    }
  }

  function flush() {
    if (inFlight) {
      dirty = true;
      return inFlight;
    }
    inFlight = (async () => {
      do {
        dirty = false;
        await pass();
      } while (dirty);
    })().finally(() => {
      inFlight = undefined;
    });
    return inFlight;
  }

  return {
    flush,
    /** Held, unsent files of *draftId* after a send attempt. */
    async pending(draftId) {
      return (await buffer.entries()).filter((e) => e.draftId === draftId).length;
    },
    stop() {
      if (timer !== undefined) clearTimer(timer);
      timer = undefined;
    },
  };
}
