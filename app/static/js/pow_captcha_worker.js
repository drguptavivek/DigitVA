// Proof-of-work CAPTCHA solver, run in a Web Worker so it never blocks the
// login page. Brute-forces the smallest integer whose SHA-256 digest (salt
// concatenated with the integer, as a decimal string) has `difficulty`
// leading zero bits — the same check the server runs in
// app/services/pow_captcha_service.py::_meets_difficulty. Keep the two in
// sync if either changes.

function meetsDifficulty(bytes, difficulty) {
  if (difficulty <= 0) return true;
  let bitsLeft = difficulty;
  for (let i = 0; i < bytes.length && bitsLeft > 0; i++) {
    const byte = bytes[i];
    if (bitsLeft >= 8) {
      if (byte !== 0) return false;
      bitsLeft -= 8;
    } else {
      if (byte >> (8 - bitsLeft) !== 0) return false;
      bitsLeft = 0;
    }
  }
  return true;
}

self.onmessage = async (event) => {
  const { salt, difficulty } = event.data || {};
  if (!salt) return;
  const encoder = new TextEncoder();
  let number = 0;
  // A real solve completes in well under a second at the configured
  // difficulty; this cap only guards against a corrupted/mis-signed
  // challenge turning into an infinite loop in the worker.
  const HARD_STOP = 50_000_000;
  while (number < HARD_STOP) {
    const digest = await crypto.subtle.digest(
      "SHA-256",
      encoder.encode(salt + String(number))
    );
    if (meetsDifficulty(new Uint8Array(digest), difficulty)) {
      self.postMessage({ solution: String(number) });
      return;
    }
    number++;
  }
  self.postMessage({ error: "no-solution-found" });
};
