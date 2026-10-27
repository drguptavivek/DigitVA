import { coalesceLatest } from "../src/coalesceSaves";

describe("coalesceLatest (digitva-wh4w)", () => {
  it("writes the first value, skips queued older ones, and writes the newest last", async () => {
    const written: number[] = [];
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    const save = coalesceLatest(async (value: number) => {
      if (value === 1) await gate;
      written.push(value);
    });
    const all = [save(1), save(2), save(3), save(4)];
    release();
    await Promise.all(all);
    expect(written).toEqual([1, 4]);
  });

  it("rejects only the callers whose write failed and keeps going", async () => {
    const save = coalesceLatest(async (value: number) => {
      if (value === 1) throw new Error("disk full");
    });
    await expect(save(1)).rejects.toThrow("disk full");
    await expect(save(2)).resolves.toBeUndefined();
  });
});
