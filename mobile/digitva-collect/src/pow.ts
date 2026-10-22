/**
 * Proof-of-work solver for the demo sign-up CAPTCHA (docs/current-state/
 * authentication-and-onboarding.md section 6.7). Finds the smallest
 * non-negative integer whose decimal string, appended to the challenge salt,
 * hashes under SHA-256 to a digest with `difficulty` leading zero bits: the
 * browser worker's loop (app/static/js/pow_captcha_worker.js) and the
 * server's check (app/services/pow_captcha_service.py) to the letter. Keep
 * the three in sync.
 *
 * React Native has no Web Worker and an awaited native digest per attempt is
 * far too slow, so SHA-256 is plain synchronous JS here, run in short slices
 * that yield to the UI thread between slices (progress, cancel). Expected
 * work is 2^difficulty hashes; the server default is 14 (about 16 000), a
 * fraction of a second on a current phone and a few seconds on a low-end one.
 */

const K = new Int32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);
const H0 = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];

const W = new Int32Array(64);

/** One SHA-256 block (`block`, 64 bytes at `offset`) folded into `state`. */
function compress(state: Int32Array, block: Uint8Array, offset: number): void {
  for (let i = 0; i < 16; i++) {
    const j = offset + i * 4;
    W[i] = (block[j] << 24) | (block[j + 1] << 16) | (block[j + 2] << 8) | block[j + 3];
  }
  for (let i = 16; i < 64; i++) {
    const a = W[i - 15];
    const b = W[i - 2];
    const s0 = ((a >>> 7) | (a << 25)) ^ ((a >>> 18) | (a << 14)) ^ (a >>> 3);
    const s1 = ((b >>> 17) | (b << 15)) ^ ((b >>> 19) | (b << 13)) ^ (b >>> 10);
    W[i] = (W[i - 16] + s0 + W[i - 7] + s1) | 0;
  }
  let a = state[0], b = state[1], c = state[2], d = state[3];
  let e = state[4], f = state[5], g = state[6], h = state[7];
  for (let i = 0; i < 64; i++) {
    const S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7));
    const t1 = (h + S1 + ((e & f) ^ (~e & g)) + K[i] + W[i]) | 0;
    const S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10));
    const t2 = (S0 + ((a & b) ^ (a & c) ^ (b & c))) | 0;
    h = g; g = f; f = e; e = (d + t1) | 0; d = c; c = b; b = a; a = (t1 + t2) | 0;
  }
  state[0] += a; state[1] += b; state[2] += c; state[3] += d;
  state[4] += e; state[5] += f; state[6] += g; state[7] += h;
}

/** SHA-256 of `bytes` as eight big-endian words (exported for the tests). */
export function sha256Words(bytes: Uint8Array): Int32Array {
  const state = Int32Array.from(H0);
  const blocks = Math.ceil((bytes.length + 9) / 64);
  const padded = new Uint8Array(blocks * 64);
  padded.set(bytes);
  padded[bytes.length] = 0x80;
  const bits = bytes.length * 8;
  padded[padded.length - 4] = (bits >>> 24) & 0xff;
  padded[padded.length - 3] = (bits >>> 16) & 0xff;
  padded[padded.length - 2] = (bits >>> 8) & 0xff;
  padded[padded.length - 1] = bits & 0xff;
  for (let i = 0; i < blocks; i++) compress(state, padded, i * 64);
  return state;
}

/** Whether the digest's first `difficulty` bits are zero (the server's `_meets_difficulty`). */
export function meetsDifficulty(words: Int32Array, difficulty: number): boolean {
  let bits = difficulty;
  for (let i = 0; i < 8 && bits > 0; i++) {
    if (bits >= 32) {
      if (words[i] !== 0) return false;
      bits -= 32;
    } else {
      return words[i] >>> (32 - bits) === 0;
    }
  }
  return bits <= 0;
}

/** Attempts per slice before yielding to the UI thread. */
const SLICE = 1500;
/** The worker's own guard against a corrupt challenge looping forever. */
const HARD_STOP = 50_000_000;
/** A real challenge salt is 32 hex digits; the rule is only that it is printable ASCII. */
const SALT = /^[\x21-\x7e]{1,64}$/;

export class PowCancelled extends Error {
  constructor() {
    super("pow_cancelled");
    this.name = "PowCancelled";
  }
}

/**
 * The solution string for a challenge. `onProgress(done, expected)` runs after
 * every slice; `signal` aborts with PowCancelled; `yieldToUi` (default a
 * zero-delay timeout) is injectable for tests. Throws `pow_unsolvable` past
 * the hard stop and `pow_bad_challenge` for a salt or difficulty that cannot
 * come from the server.
 */
export async function solveChallenge(
  salt: string,
  difficulty: number,
  options: {
    onProgress?: (done: number, expected: number) => void;
    signal?: { aborted: boolean };
    yieldToUi?: () => Promise<void>;
  } = {},
): Promise<string> {
  if (typeof salt !== "string" || !SALT.test(salt) || !Number.isInteger(difficulty) || difficulty < 0 || difficulty > 32) {
    throw new Error("pow_bad_challenge");
  }
  const { onProgress, signal, yieldToUi = () => new Promise<void>((resolve) => setTimeout(resolve, 0)) } = options;
  const expected = 2 ** difficulty;
  const prefix = new Uint8Array(salt.length);
  for (let i = 0; i < salt.length; i++) prefix[i] = salt.charCodeAt(i);
  // One reusable buffer holding the salt and, after it, the decimal digits.
  const message = new Uint8Array(salt.length + 20);
  message.set(prefix);
  let number = 0;
  while (number < HARD_STOP) {
    const end = Math.min(number + SLICE, HARD_STOP);
    for (; number < end; number++) {
      let length = prefix.length;
      // Decimal digits of `number`, most significant first.
      let digits = 1;
      for (let rest = number; rest >= 10; rest = Math.floor(rest / 10)) digits++;
      for (let i = digits - 1, rest = number; i >= 0; i--, rest = Math.floor(rest / 10)) message[length + i] = 48 + (rest % 10);
      length += digits;
      if (meetsDifficulty(sha256Words(message.subarray(0, length)), difficulty)) {
        onProgress?.(number + 1, expected);
        return String(number);
      }
    }
    onProgress?.(number, expected);
    if (signal?.aborted) throw new PowCancelled();
    await yieldToUi();
    if (signal?.aborted) throw new PowCancelled();
  }
  throw new Error("pow_unsolvable");
}
