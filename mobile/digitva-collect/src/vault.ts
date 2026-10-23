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
import * as LocalAuthentication from "expo-local-authentication";
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
const screenLockFlagKey = (hash: string) => `pin_lock_on_${hash}`;
const screenLockKey = (hash: string) => `pin_lock_${hash}`;
const offerKey = (hash: string) => `unlock_offer_${hash}`;
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

/** Turn fingerprint unlock off (Settings); the PIN keeps working. */
export async function turnOffBiometric(userId: string): Promise<void> {
  await disableBiometric(await storeHash(userId));
}

/**
 * Phone screen lock unlock (docs/policy/mobile-sign-in.md section 9): the phone's own lock (biometric, pattern,
 * PIN or password as the phone allows) gates the release of the PIN, which sits in Keystore-backed SecureStore
 * without per-use authentication. Weaker than the biometric entry above, whose key is bound to the biometric.
 */
export async function screenLockAvailable(): Promise<boolean> {
  try {
    return (await LocalAuthentication.getEnrolledLevelAsync()) !== LocalAuthentication.SecurityLevel.NONE;
  } catch {
    return false;
  }
}

export async function screenLockEnabled(userId: string): Promise<boolean> {
  return (await SecureStore.getItemAsync(screenLockFlagKey(await storeHash(userId)), OPTIONS)) === "1";
}

async function promptScreenLock(prompt: string): Promise<boolean> {
  const result = await LocalAuthentication.authenticateAsync({ promptMessage: prompt, disableDeviceFallback: false });
  return result.success;
}

/** Ask the phone's lock once, then keep `pin` behind it. Throws when the prompt fails or is cancelled. */
export async function enableScreenLock(userId: string, pin: string, prompt: string): Promise<void> {
  if (!(await promptScreenLock(prompt))) throw new Error("screen_lock_refused");
  const hash = await storeHash(userId);
  await SecureStore.setItemAsync(screenLockKey(hash), pin, OPTIONS);
  await SecureStore.setItemAsync(screenLockFlagKey(hash), "1", OPTIONS);
}

/**
 * The PIN released by the phone's lock prompt, or null when this option is off. Throws when the prompt is
 * cancelled or fails; that is not a failed PIN. The option drops itself when the phone no longer has a screen lock.
 */
export async function readScreenLockPin(userId: string, prompt: string): Promise<string | null> {
  if (!(await screenLockEnabled(userId))) return null;
  if (!(await screenLockAvailable())) {
    await turnOffScreenLock(userId);
    return null;
  }
  if (!(await promptScreenLock(prompt))) throw new Error("screen_lock_refused");
  return SecureStore.getItemAsync(screenLockKey(await storeHash(userId)), OPTIONS);
}

export async function turnOffScreenLock(userId: string): Promise<void> {
  const hash = await storeHash(userId);
  await SecureStore.deleteItemAsync(screenLockFlagKey(hash), OPTIONS);
  await SecureStore.deleteItemAsync(screenLockKey(hash), OPTIONS);
}

/** How many times the unlock-options offer has been shown to this interviewer. */
export async function unlockOfferCount(userId: string): Promise<number> {
  const count = Number(await SecureStore.getItemAsync(offerKey(await storeHash(userId)), OPTIONS));
  return Number.isInteger(count) && count > 0 ? count : 0;
}

export async function noteUnlockOffer(userId: string): Promise<void> {
  await SecureStore.setItemAsync(offerKey(await storeHash(userId)), String((await unlockOfferCount(userId)) + 1), OPTIONS);
}

/** First offer after PIN setup, one more on a later PIN unlock, then never. */
export const UNLOCK_OFFER_MAX = 2;

/** Forget this interviewer's secret, counter and biometric / screen-lock PIN. Other interviewers are untouched. */
export async function forgetStoreKeys(userId: string): Promise<void> {
  const hash = await storeHash(userId);
  await SecureStore.deleteItemAsync(secretKey(hash), OPTIONS);
  await SecureStore.deleteItemAsync(failuresKey(hash), OPTIONS);
  await SecureStore.deleteItemAsync(offerKey(hash), OPTIONS);
  await disableBiometric(hash);
  await turnOffScreenLock(userId);
}
