/**
 * The demo sign-up proof of work must agree with the server's check
 * (app/services/pow_captcha_service.py): the smallest n such that
 * SHA-256(salt + str(n)) has `difficulty` leading zero bits. The expected
 * solutions below were found with the server's own algorithm in Python
 * (tests/base.py `_solve_pow_captcha`).
 */
import { createHash } from "node:crypto";

import { meetsDifficulty, PowCancelled, sha256Words, solveChallenge } from "../src/pow";

const SALT_A = "a3f09c11d27e4b5586c0e1f2d3a4b5c6";
const SALT_B = "0123456789abcdef0123456789abcdef";

const serverDigest = (text: string) => createHash("sha256").update(text, "utf8").digest();
const words = (digest: Buffer) => Int32Array.from({ length: 8 }, (_, i) => digest.readInt32BE(i * 4));

/** The server's `_meets_difficulty`, on a Buffer. */
function serverMeets(digest: Buffer, difficulty: number) {
  const bits = digest.length * 8;
  return difficulty <= 0 || (BigInt(`0x${digest.toString("hex")}`) >> BigInt(bits - difficulty)) === 0n;
}

const noYield = async () => undefined;

describe("sha256Words", () => {
  it.each(["", "abc", SALT_A + "929", SALT_A + "0", "x".repeat(55), "x".repeat(56), "x".repeat(63), "x".repeat(64), "x".repeat(200)])(
    "matches the platform digest for %j-length input",
    (text) => {
      expect(Array.from(sha256Words(Buffer.from(text, "utf8")))).toEqual(Array.from(words(serverDigest(text))));
    },
  );
});

describe("solveChallenge", () => {
  it.each([
    [SALT_A, 12, "781"],
    [SALT_A, 14, "929"],
    [SALT_B, 12, "0"],
    [SALT_B, 14, "5422"],
    [SALT_A, 20, "607082"],
  ])("finds the server's solution for salt %s at difficulty %i", async (salt, difficulty, expected) => {
    const solution = await solveChallenge(salt, difficulty, { yieldToUi: noYield });
    expect(solution).toBe(expected);
    expect(serverMeets(serverDigest(salt + solution), difficulty)).toBe(true);
  });

  it("returns a solution the server's rule accepts for any salt", async () => {
    for (const salt of ["f".repeat(32), "9".repeat(32), "00ff00ff00ff00ff00ff00ff00ff00ff"]) {
      const solution = await solveChallenge(salt, 10, { yieldToUi: noYield });
      expect(serverMeets(serverDigest(salt + solution), 10)).toBe(true);
      // Smallest: no lower number qualifies.
      for (let n = 0; n < Number(solution); n++) expect(serverMeets(serverDigest(salt + n), 10)).toBe(false);
    }
  });

  it("difficulty 0 takes the first number", async () => {
    await expect(solveChallenge(SALT_A, 0, { yieldToUi: noYield })).resolves.toBe("0");
  });

  it("reports progress in slices and yields to the UI between them", async () => {
    const progress: Array<[number, number]> = [];
    const yieldToUi = jest.fn(noYield);
    await solveChallenge(SALT_A, 14, { yieldToUi, onProgress: (done, expected) => progress.push([done, expected]) });
    expect(progress.length).toBeGreaterThan(0);
    expect(progress.at(-1)).toEqual([930, 16384]);
    // 930 attempts fit in one slice, so the solution came before any yield.
    expect(yieldToUi).not.toHaveBeenCalled();
    await solveChallenge(SALT_A, 20, { yieldToUi, onProgress: (done, expected) => progress.push([done, expected]) });
    expect(yieldToUi).toHaveBeenCalled();
  });

  it("stops when cancelled", async () => {
    const signal = { aborted: false };
    await expect(
      solveChallenge(SALT_A, 24, { signal, yieldToUi: async () => void (signal.aborted = true) }),
    ).rejects.toBeInstanceOf(PowCancelled);
  });

  it.each([["", 14], ["has space", 14], ["é".repeat(8), 14], [SALT_A, -1], [SALT_A, 33], [SALT_A, 1.5]])(
    "refuses a challenge the server could not have issued (%j, %p)",
    async (salt, difficulty) => {
      await expect(solveChallenge(salt as string, difficulty as number)).rejects.toThrow("pow_bad_challenge");
    },
  );
});

describe("meetsDifficulty", () => {
  it("counts leading zero bits across words", () => {
    const w = Int32Array.from([0, 0x00ffffff, 0, 0, 0, 0, 0, 0]);
    expect(meetsDifficulty(w, 32)).toBe(true);
    expect(meetsDifficulty(w, 40)).toBe(true);
    expect(meetsDifficulty(w, 41)).toBe(false);
    expect(meetsDifficulty(Int32Array.from([0x00000001, 0, 0, 0, 0, 0, 0, 0]), 31)).toBe(true);
    expect(meetsDifficulty(Int32Array.from([0x00000001, 0, 0, 0, 0, 0, 0, 0]), 32)).toBe(false);
    expect(meetsDifficulty(Int32Array.from([-1, 0, 0, 0, 0, 0, 0, 0]), 1)).toBe(false);
  });
});
