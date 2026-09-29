/**
 * Per-interviewer store keys and the PIN rules (Path B, phase 2b).
 *
 * Each interviewer's SQLCipher database is keyed with
 * `hex(store secret) + ":" + PIN`; SQLCipher's PBKDF2 derives the key. The
 * 32-byte store secret lives in Keystore-backed SecureStore, so a copy of the
 * app's files alone cannot be brute-forced, and the PIN is never stored
 * except in the optional biometric entry (Keystore key usable only after a
 * strong biometric; a new enrolment invalidates it and the app falls back to
 * the PIN). The failed-PIN counter sits beside the secret because it must be
 * readable while the store is locked.
 *
 * Entries are keyed by a hash of the user id, like the database file name.
 * Nothing here logs.
 */
import { CryptoDigestAlgorithm, digestStringAsync, getRandomBytesAsync } from "expo-crypto";
import * as SecureStore from "expo-secure-store";

export const PIN_MIN_LENGTH = 6;
const PIN_MAX_LENGTH = 16;
export const WARN_AFTER_FAILURES = 3;
export const WIPE_AFTER_FAILURES = 5;

const SECRET_HEX = /^[0-9a-f]{64}$/;
const PIN_DIGITS = /^\d+$/;

const OPTIONS: SecureStore.SecureStoreOptions = {
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY
};

export type PinProblem = "pinTooShort" | "pinDigitsOnly" | "pinMismatch";

/** Why `pin` (with its confirmation) cannot be the PIN, or undefined. */
export function pinProblem(pin: string, confirm: string): PinProblem | undefined {
  if (pin.length < PIN_MIN_LENGTH) return "pinTooShort";
  if (!PIN_DIGITS.test(pin) || pin.length > PIN_MAX_LENGTH) return "pinDigitsOnly";
  if (pin !== confirm) return "pinMismatch";
  return undefined;
}

/**
 * The SQLCipher passphrase. `PRAGMA key` cannot take a bound parameter, so
 * both parts are checked against strict patterns here and the result can
 * never carry a quote. Throws on anything else.
 */
export function buildPassphrase(secretHex: string, pin: string): string {
  if (!SECRET_HEX.test(secretHex)) throw new Error("bad_store_secret");
  if (!PIN_DIGITS.test(pin) || pin.length < PIN_MIN_LENGTH || pin.length > PIN_MAX_LENGTH) {
    throw new Error("bad_pin");
  }
  return `${secretHex}:${pin}`;
}

/** Hash of the user id: names the database file and this interviewer's vault entries. */
export function storeHash(userId: string): Promise<string> {
  return digestStringAsync(CryptoDigestAlgorithm.SHA256, `digitva-collect:${userId}`);
}

const secretKey = (hash: string) => `store_secret_${hash}`;
const failuresKey = (hash: string) => `pin_failures_${hash}`;
const biometricFlagKey = (hash: string) => `pin_bio_on_${hash}`;
const biometricKey = (hash: string) => `pin_bio_${hash}`;
/** Its own Keystore alias: an authentication-bound key cannot share the default one. */
const biometricOptions = (hash: string, prompt?: string): SecureStore.SecureStoreOptions => ({
  ...OPTIONS,
  keychainService: `bio_${hash}`,
  requireAuthentication: true,
  ...(prompt ? { authenticationPrompt: prompt } : {})
});

export async function readStoreSecret(userId: string): Promise<string | null> {
  return SecureStore.getItemAsync(secretKey(await storeHash(userId)), OPTIONS);
}

/** A fresh random 32-byte secret for a new store, saved and returned as hex. */
export async function createStoreSecret(userId: string): Promise<string> {
  const bytes = await getRandomBytesAsync(32);
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  await SecureStore.setItemAsync(secretKey(await storeHash(userId)), hex, OPTIONS);
  return hex;
}

export async function failedAttempts(userId: string): Promise<number> {
  const raw = await SecureStore.getItemAsync(failuresKey(await storeHash(userId)), OPTIONS);
  const count = Number(raw ?? 0);
  return Number.isInteger(count) && count > 0 ? count : 0;
}

/** Count one more wrong PIN and return the new total. Called before the PIN is tried. */
export async function recordFailedAttempt(userId: string): Promise<number> {
  const next = (await failedAttempts(userId)) + 1;
  await SecureStore.setItemAsync(failuresKey(await storeHash(userId)), String(next), OPTIONS);
  return next;
}

export async function setFailedAttempts(userId: string, count: number): Promise<void> {
  const key = failuresKey(await storeHash(userId));
  if (count <= 0) await SecureStore.deleteItemAsync(key, OPTIONS);
  else await SecureStore.setItemAsync(key, String(count), OPTIONS);
}

export async function biometricEnabled(userId: string): Promise<boolean> {
  return (await SecureStore.getItemAsync(biometricFlagKey(await storeHash(userId)), OPTIONS)) === "1";
}

/** Keep the PIN behind a strong biometric. Android prompts for the biometric on this write too. */
export async function enableBiometric(userId: string, pin: string, prompt: string): Promise<void> {
  const hash = await storeHash(userId);
  await SecureStore.setItemAsync(biometricKey(hash), pin, biometricOptions(hash, prompt));
  await SecureStore.setItemAsync(biometricFlagKey(hash), "1", OPTIONS);
}

/**
 * The PIN released by a biometric prompt, or null when biometric unlock is
 * off or the Keystore key was invalidated (new enrolment): then the entry is
 * dropped and the interviewer uses the PIN. Throws when the prompt is
 * cancelled; that is not a failed PIN.
 */
export async function readBiometricPin(userId: string, prompt: string): Promise<string | null> {
  const hash = await storeHash(userId);
  if (!(await biometricEnabled(userId))) return null;
  const pin = await SecureStore.getItemAsync(biometricKey(hash), biometricOptions(hash, prompt));
  if (pin === null) await disableBiometric(hash);
  return pin;
}

async function disableBiometric(hash: string): Promise<void> {
  await SecureStore.deleteItemAsync(biometricFlagKey(hash), OPTIONS);
  try {
    await SecureStore.deleteItemAsync(biometricKey(hash), biometricOptions(hash));
  } catch {
    // Already gone with its invalidated key.
  }
}

/** Forget this interviewer's secret, counter and biometric PIN. Other interviewers are untouched. */
export async function forgetStoreKeys(userId: string): Promise<void> {
  const hash = await storeHash(userId);
  await SecureStore.deleteItemAsync(secretKey(hash), OPTIONS);
  await SecureStore.deleteItemAsync(failuresKey(hash), OPTIONS);
  await disableBiometric(hash);
}
