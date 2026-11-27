import { clearScreenCache, readCached, screenKey, writeCached } from "../src/web/screenCache";

describe("screenCache", () => {
  beforeEach(() => clearScreenCache());

  it("keys by user and every part, never across users", () => {
    const mine = screenKey("u1", "deaths", "P1");
    writeCached(mine, { rows: 3 });
    expect(readCached(mine)).toEqual({ rows: 3 });
    expect(readCached(screenKey("u2", "deaths", "P1"))).toBeUndefined();
    expect(readCached(screenKey("u1", "deaths", "P2"))).toBeUndefined();
  });

  it("caches nothing without a user", () => {
    expect(screenKey(undefined, "deaths")).toBeUndefined();
    writeCached(undefined, 1);
    expect(readCached(undefined)).toBeUndefined();
  });

  it("clears everything on sign-out or user change", () => {
    const key = screenKey("u1", "home");
    writeCached(key, "x");
    clearScreenCache();
    expect(readCached(key)).toBeUndefined();
  });
});
