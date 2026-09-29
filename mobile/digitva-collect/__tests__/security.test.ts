/**
 * Phase 2b store security: the passphrase and PIN rules, the failed-PIN
 * counter (warn at 3, wipe at 5, only that interviewer), locking, PIN setup
 * over a phase-2a plaintext file, the auto-lock timers, and the wipe matrix
 * (sign-out, session_revoked, five wrong PINs wipe; other refusals keep).
 *
 * expo-sqlite is faked as a keyed file table: a file remembers the key it was
 * created with (null = plaintext) and refuses any other key on first read,
 * as SQLCipher does with SQLITE_NOTADB.
 */
import { createHash } from "node:crypto";

const mockSecure = new Map<string, string>();
jest.mock("expo-secure-store", () => ({
  WHEN_UNLOCKED_THIS_DEVICE_ONLY: 0,
  getItemAsync: jest.fn(async (key: string) => mockSecure.get(key) ?? null),
  setItemAsync: jest.fn(async (key: string, value: string) => void mockSecure.set(key, value)),
  deleteItemAsync: jest.fn(async (key: string) => void mockSecure.delete(key))
}));
jest.mock("expo-crypto", () => ({
  CryptoDigestAlgorithm: { SHA256: "SHA-256" },
  digestStringAsync: async (_alg: string, value: string) =>
    require("node:crypto").createHash("sha256").update(value).digest("hex"),
  getRandomBytesAsync: async (n: number) => new Uint8Array(require("node:crypto").randomBytes(n))
}));
const mockFiles = new Map<string, string | null>();
const mockOpenHandles = new Set<string>();
jest.mock("expo-sqlite", () => ({
  openDatabaseAsync: async (name: string) => {
    let key: string | null = null;
    const id = `${name}#${Math.random()}`;
    mockOpenHandles.add(id);
    return {
      execAsync: async (sql: string) => {
        const match = /^PRAGMA key = '([^']*)';$/.exec(sql);
        if (match) key = match[1];
      },
      runAsync: async () => undefined,
      getAllAsync: async () => [{ name: "completion" }],
      getFirstAsync: async () => {
        if (!mockFiles.has(name)) mockFiles.set(name, key);
        if (mockFiles.get(name) !== key) throw new Error("Error code 26: file is not a database");
        return { n: 0 };
      },
      closeAsync: async () => void mockOpenHandles.delete(id)
    };
  },
  deleteDatabaseAsync: async (name: string) => {
    if (!mockFiles.delete(name)) throw new Error("no such file");
  }
}));

import { classifyAuthError, loadAccounts, signOut, unlockInterviewer } from "../src/auth";
import { ApiError } from "../src/api";
import { BACKGROUND_LOCK_MS, createAutoLock, IDLE_LOCK_MS } from "../src/autoLock";
import {
  createInterviewerDb,
  isUnlocked,
  lockAll,
  openInterviewerDb,
  StoreLockedError
} from "../src/interviewerDb";
import { buildPassphrase, failedAttempts, pinProblem, storeHash } from "../src/vault";

const SERVER = "http://10.0.2.2:8051";
const A = "11111111-1111-4111-8111-111111111111";
const B = "22222222-2222-4222-8222-222222222222";
const PIN = "246810";

const hashOf = (userId: string) => createHash("sha256").update(`digitva-collect:${userId}`).digest("hex");
const fileOf = (userId: string) => `iv_${hashOf(userId)}.db`;

function seedAccounts() {
  mockSecure.set("device_secret", "dev-secret");
  mockSecure.set("device", JSON.stringify({ device_id: "d1", server: SERVER, project_id: "P", project_name: "P" }));
  mockSecure.set("accounts", JSON.stringify([{ user_id: A, name: "A" }, { user_id: B, name: "B" }]));
  for (const id of [A, B]) {
    mockSecure.set(
      `tokens.${id}`,
      JSON.stringify({ access_token: `acc-${id}`, access_expires_at: "", refresh_token: "r", refresh_expires_at: "" })
    );
  }
}

/** Everything that belongs to one interviewer on the device. */
function footprint(userId: string) {
  const h = hashOf(userId);
  return {
    file: mockFiles.has(fileOf(userId)),
    secret: mockSecure.has(`store_secret_${h}`),
    tokens: mockSecure.has(`tokens.${userId}`),
    biometric: mockSecure.has(`pin_bio_${h}`) || mockSecure.has(`pin_bio_on_${h}`)
  };
}

async function setUpBoth() {
  seedAccounts();
  await createInterviewerDb(A, PIN);
  await createInterviewerDb(B, "135790");
  // A biometric entry to prove the wipe removes it too.
  mockSecure.set(`pin_bio_${hashOf(A)}`, PIN);
  mockSecure.set(`pin_bio_on_${hashOf(A)}`, "1");
  mockSecure.set(`pin_bio_${hashOf(B)}`, "135790");
  mockSecure.set(`pin_bio_on_${hashOf(B)}`, "1");
  await lockAll();
}

beforeEach(async () => {
  await lockAll();
  mockSecure.clear();
  mockFiles.clear();
  globalThis.fetch = jest.fn(async () => ({ ok: true, status: 204, text: async () => "" })) as unknown as typeof fetch;
});

describe("passphrase and PIN rules", () => {
  const secret = "ab".repeat(32);

  it("joins the hex secret and the PIN", () => {
    expect(buildPassphrase(secret, "123456")).toBe(`${secret}:123456`);
  });

  it.each([
    ["short secret", "ab", "123456"],
    ["upper-case secret", "AB".repeat(32), "123456"],
    ["short PIN", secret, "12345"],
    ["quote in PIN", secret, "123456'"],
    ["letters in PIN", secret, "12345a"],
    ["over-long PIN", secret, "1".repeat(17)]
  ])("refuses a %s, so PRAGMA key never sees a quote", (_name, s, pin) => {
    expect(() => buildPassphrase(s, pin)).toThrow();
  });

  it("checks length, digits and confirmation", () => {
    expect(pinProblem("", "")).toBe("pinTooShort");
    expect(pinProblem("12345", "12345")).toBe("pinTooShort");
    expect(pinProblem("12345a", "12345a")).toBe("pinDigitsOnly");
    expect(pinProblem("1".repeat(17), "1".repeat(17))).toBe("pinDigitsOnly");
    expect(pinProblem("123456", "123457")).toBe("pinMismatch");
    expect(pinProblem("123456", "123456")).toBeUndefined();
    expect(pinProblem("1".repeat(16), "1".repeat(16))).toBeUndefined();
  });
});

describe("store setup, unlock and lock", () => {
  it("creates an encrypted store, locks it, and opens it again only with the PIN", async () => {
    seedAccounts();
    await createInterviewerDb(A, PIN);
    expect(isUnlocked(A)).toBe(true);
    expect(mockFiles.get(fileOf(A))).toMatch(/^[0-9a-f]{64}:246810$/);

    await lockAll();
    expect(isUnlocked(A)).toBe(false);
    expect(mockOpenHandles.size).toBe(0);
    await expect(openInterviewerDb(A)).rejects.toBeInstanceOf(StoreLockedError);

    expect(await unlockInterviewer(A, "000000")).toEqual({ ok: false, failures: 1, wipe: false });
    expect(await unlockInterviewer(A, PIN)).toEqual({ ok: true });
    expect(await failedAttempts(A)).toBe(0);
    await expect(openInterviewerDb(A)).resolves.toBeDefined();
  });

  it("replaces a phase-2a plaintext file at setup instead of counting it as a wrong PIN", async () => {
    seedAccounts();
    mockFiles.set(fileOf(A), null);
    await createInterviewerDb(A, PIN);
    expect(mockFiles.get(fileOf(A))).not.toBeNull();
  });

  it("never replaces an existing store's PIN", async () => {
    seedAccounts();
    await createInterviewerDb(A, PIN);
    await lockAll();
    await expect(createInterviewerDb(A, "999999")).rejects.toThrow("store_exists");
    expect(await unlockInterviewer(A, PIN)).toEqual({ ok: true });
  });

  it("refuses to unlock an interviewer who has no PIN yet", async () => {
    seedAccounts();
    await expect(unlockInterviewer(A, PIN)).rejects.toBeInstanceOf(StoreLockedError);
  });
});

describe("failed PINs", () => {
  it("counts each wrong PIN, and a right PIN resets the count", async () => {
    await setUpBoth();
    for (const n of [1, 2, 3, 4]) {
      expect(await unlockInterviewer(A, "000000")).toEqual({ ok: false, failures: n, wipe: false });
    }
    expect(await unlockInterviewer(A, PIN)).toEqual({ ok: true });
    expect(await failedAttempts(A)).toBe(0);
    expect(footprint(A)).toEqual({ file: true, secret: true, tokens: true, biometric: true });
  });

  it("wipes only that interviewer on the fifth wrong PIN in a row", async () => {
    await setUpBoth();
    await unlockInterviewer(B, "000000");
    for (let n = 1; n <= 4; n += 1) await unlockInterviewer(A, "000000");
    expect(footprint(A).file).toBe(true);

    expect(await unlockInterviewer(A, "000000")).toEqual({ ok: false, failures: 5, wipe: true });

    expect(footprint(A)).toEqual({ file: false, secret: false, tokens: false, biometric: false });
    expect(mockSecure.has(`pin_failures_${hashOf(A)}`)).toBe(false);
    expect((await loadAccounts()).map((a) => a.user_id)).toEqual([B]);
    expect(footprint(B)).toEqual({ file: true, secret: true, tokens: true, biometric: true });
    expect(await failedAttempts(B)).toBe(1);
    expect(await unlockInterviewer(B, "135790")).toEqual({ ok: true });
  });

  it("counts a malformed PIN as a wrong one", async () => {
    await setUpBoth();
    expect(await unlockInterviewer(A, "12'--")).toEqual({ ok: false, failures: 1, wipe: false });
  });
});

describe("wipe matrix", () => {
  it("sign-out wipes that interviewer only", async () => {
    await setUpBoth();
    await signOut(A);
    expect(footprint(A)).toEqual({ file: false, secret: false, tokens: false, biometric: false });
    expect(footprint(B)).toEqual({ file: true, secret: true, tokens: true, biometric: true });
  });

  it("session_revoked wipes that interviewer only", async () => {
    await setUpBoth();
    await classifyAuthError(A, new ApiError(401, "session_revoked"));
    expect(footprint(A)).toEqual({ file: false, secret: false, tokens: false, biometric: false });
    expect(footprint(B)).toEqual({ file: true, secret: true, tokens: true, biometric: true });
  });

  it.each([
    [401, "refresh_reused"],
    [409, "refresh_retry_race"],
    [401, "session_ended"],
    [401, "session_expired"]
  ])("%i %s keeps the store and its keys", async (status, code) => {
    await setUpBoth();
    await classifyAuthError(A, new ApiError(status, code));
    expect(footprint(A)).toEqual({ file: true, secret: true, tokens: false, biometric: true });
    expect(await unlockInterviewer(A, PIN)).toEqual({ ok: true });
  });
});

describe("auto-lock", () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  it("locks after 5 idle minutes, and activity restarts the wait", () => {
    const onLock = jest.fn();
    const lock = createAutoLock(onLock);
    jest.advanceTimersByTime(IDLE_LOCK_MS - 1000);
    lock.activity();
    jest.advanceTimersByTime(IDLE_LOCK_MS - 1000);
    expect(onLock).not.toHaveBeenCalled();
    jest.advanceTimersByTime(1000);
    expect(onLock).toHaveBeenCalledTimes(1);
    lock.stop();
  });

  it("locks on return after more than a minute in the background, not less", () => {
    let clock = 0;
    const onLock = jest.fn();
    const lock = createAutoLock(onLock, () => clock);
    lock.appStateChanged("background");
    clock += BACKGROUND_LOCK_MS;
    lock.appStateChanged("active");
    expect(onLock).not.toHaveBeenCalled();

    lock.appStateChanged("inactive");
    lock.appStateChanged("background"); // the first departure is what counts
    clock += BACKGROUND_LOCK_MS + 1;
    lock.appStateChanged("active");
    expect(onLock).toHaveBeenCalledTimes(1);
    lock.stop();
  });
});

it("names vault entries and the file by the same user hash", async () => {
  expect(await storeHash(A)).toBe(hashOf(A));
});
