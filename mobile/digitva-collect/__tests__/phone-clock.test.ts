/** Phone clock: Date header offset, 5 min / 4 h thresholds, offline persistence, envelope field, corrected today. */
const mockSecure = new Map<string, string>();
jest.mock("expo-secure-store", () => ({
  getItemAsync: jest.fn(async (key: string) => mockSecure.get(key) ?? null),
  setItemAsync: jest.fn(async (key: string, value: string) => void mockSecure.set(key, value)),
}));

import {
  BLOCK_SECONDS,
  clockLevel,
  clockOffsetField,
  correctedNow,
  loadPhoneClock,
  getPhoneClock,
  parseServerDate,
  recheckPhoneClock,
  recordServerDate,
  resetPhoneClock,
  smoothOffset,
} from "../src/phoneClock";

const SERVER = "Thu, 22 Oct 2026 10:00:00 GMT";
const serverMs = Date.parse(SERVER);

beforeEach(() => {
  mockSecure.clear();
  resetPhoneClock();
});

describe("measuring", () => {
  it("parses the Date header and ignores a missing or bad one", () => {
    expect(parseServerDate(SERVER)).toBe(serverMs);
    expect(parseServerDate(null)).toBeUndefined();
    expect(parseServerDate("not a date")).toBeUndefined();
    recordServerDate(null);
    recordServerDate("garbage");
    expect(getPhoneClock()).toBeUndefined();
    expect(clockOffsetField()).toEqual({});
  });

  it("is phone minus server, in whole seconds", () => {
    recordServerDate(SERVER, serverMs + 90_500);
    expect(getPhoneClock()?.offsetSeconds).toBe(91);
    resetPhoneClock();
    recordServerDate(SERVER, serverMs - 3600_000);
    expect(clockOffsetField()).toEqual({ clockOffsetSeconds: -3600 });
  });

  it("averages small changes and takes a big jump (the clock was fixed) at once", () => {
    expect(smoothOffset(undefined, 500)).toBe(500);
    expect(smoothOffset(500, 510)).toBe(505);
    expect(smoothOffset(20_000, 3)).toBe(3);
  });

  it("corrects now by the offset", () => {
    recordServerDate(SERVER, serverMs + 7200_000);
    const drift = Math.abs(Date.now() - 7200_000 - correctedNow().getTime());
    expect(drift).toBeLessThan(1000);
  });
});

describe("thresholds", () => {
  it("is ok under 5 minutes, warns up to 4 hours, blocks beyond, and never judges an unmeasured phone", () => {
    expect(clockLevel(undefined)).toBe("ok");
    expect(clockLevel(299)).toBe("ok");
    expect(clockLevel(-300)).toBe("warn");
    expect(clockLevel(BLOCK_SECONDS)).toBe("warn");
    expect(clockLevel(BLOCK_SECONDS + 1)).toBe("block");
    expect(clockLevel(-BLOCK_SECONDS - 1)).toBe("block");
  });
});

describe("offline", () => {
  it("keeps a stored block across restarts until a check passes", async () => {
    recordServerDate(SERVER, serverMs + 5 * 3600_000);
    expect(clockLevel(getPhoneClock()?.offsetSeconds)).toBe("block");
    resetPhoneClock(); // app restart
    expect(getPhoneClock()).toBeUndefined();
    await loadPhoneClock();
    expect(clockLevel(getPhoneClock()?.offsetSeconds)).toBe("block");

    // Offline re-check: the fetch fails and the block stays.
    global.fetch = jest.fn(async () => { throw new TypeError("offline"); }) as unknown as typeof fetch;
    await expect(recheckPhoneClock("https://x")).resolves.toBe(false);
    expect(clockLevel(getPhoneClock()?.offsetSeconds)).toBe("block");

    // Online and the clock fixed: the block lifts.
    const now = new Date();
    global.fetch = jest.fn(async () => ({ headers: { get: () => now.toUTCString() } })) as unknown as typeof fetch;
    await expect(recheckPhoneClock("https://x")).resolves.toBe(true);
    expect(clockLevel(getPhoneClock()?.offsetSeconds)).toBe("ok");
  });

  it("treats an unreadable stored value as never measured", async () => {
    mockSecure.set("phone_clock", "{bad");
    await loadPhoneClock();
    expect(getPhoneClock()).toBeUndefined();
  });
});
