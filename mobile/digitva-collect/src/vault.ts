/**
 * Per-interviewer store keys and the PIN rules (Path B, phase 2b; digitva-kfi).
 *
 * Each interviewer's SQLCipher database is keyed with its data key, a
 * passphrase that never changes for the life of the store: random hex for a
 * new store, or `hex(store secret) + ":" + PIN` for a store created before
 * digitva-kfi (kept as is, so nothing is re-encrypted). Two copies sit in
 * Keystore-backed SecureStore: one wrapped by the PIN and the 32-byte store
 * secret (the PIN unlock), and the reset copy, released only after a password
 * sign-in for this account (docs/policy/field-data-collection.md, "Wrong PINs
 * and PIN reset"). The PIN is never stored except in the optional biometric
 * entry (Keystore key usable only after a strong biometric; a new enrolment
 * invalidates it and the app falls back to the PIN). The failed-PIN counter
 * and the time of the last wrong PIN sit beside the secret because they must
 * be readable while the store is locked.
 *
 * Entries are keyed by a hash of the user id, like the database file name.
 * Nothing here logs.
 */
import { CryptoDigestAlgorithm, digestStringAsync, getRandomBytesAsync } from "expo-crypto";
import * as LocalAuthentication from "expo-local-authentication";
import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

export const PIN_MIN_LENGTH = 6;
export const PIN_MAX_LENGTH = 16;
export const WARN_AFTER_FAILURES = 3;
/** Wrong PINs in a row before the first wait (pinLockMs). */
export const FREE_PIN_ATTEMPTS = 5;
/** Wait after the 5th, 6th, 7th wrong PIN, then the last one for every later wrong PIN. */
const LOCK_MINUTES = [1, 5, 15, 60];

const SECRET_HEX = /^[0-9a-f]{64}$/;
/** A data key: random hex (new store) or the pre-digitva-kfi `secret:PIN` passphrase. Never carries a quote. */
const DATA_KEY = /^[0-9a-f]{64}(:\d{6,16})?$/;
const WRAPPED = /^([0-9a-f]{32})\.((?:[0-9a-f]{2})+)$/;
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
const failedAtKey = (hash: string) => `pin_failed_at_${hash}`;
const pinWrapKey = (hash: string) => `store_key_pin_${hash}`;
const resetCopyKey = (hash: string) => `store_key_reset_${hash}`;
const biometricFlagKey = (hash: string) => `pin_bio_on_${hash}`;
const biometricKey = (hash: string) => `pin_bio_${hash}`;
const screenLockFlagKey = (hash: string) => `pin_lock_on_${hash}`;
const screenLockKey = (hash: string) => `pin_lock_${hash}`;
const offerKey = (hash: string) => `unlock_offer_${hash}`;
const pinLengthKey = (hash: string) => `pin_len_${hash}`;
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

const toHex = (bytes: Uint8Array) => Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
const randomHex = async (n: number) => toHex(await getRandomBytesAsync(n));

/** A fresh random 32-byte secret for a new store, saved and returned as hex. */
export async function createStoreSecret(userId: string): Promise<string> {
  const hex = await randomHex(32);
  await SecureStore.setItemAsync(secretKey(await storeHash(userId)), hex, OPTIONS);
  return hex;
}

/** A random data key for a new store (64 hex characters). */
export const newDataKey = () => randomHex(32);

/** `key` when it is a well-formed data key, safe to put in `PRAGMA key`; throws otherwise. */
export function checkedDataKey(key: string): string {
  if (!DATA_KEY.test(key)) throw new Error("bad_data_key");
  return key;
}

/**
 * SHA-256 in counter mode over the store secret, a per-wrap salt and the PIN. Wrapping XORs the data key with it;
 * the fresh salt makes every wrap's stream new. No key stretching: the Keystore-held secret is the barrier
 * (threat model in docs/policy/field-data-collection.md).
 */
async function keyStream(secretHex: string, salt: string, pin: string, length: number): Promise<number[]> {
  const out: number[] = [];
  for (let block = 0; out.length < length; block += 1) {
    const hex = await digestStringAsync(CryptoDigestAlgorithm.SHA256, `digitva-wrap:${secretHex}:${salt}:${pin}:${block}`);
    for (let i = 0; i < hex.length; i += 2) out.push(parseInt(hex.slice(i, i + 2), 16));
  }
  return out.slice(0, length);
}

/** The data key wrapped by the PIN and store secret, as `salt.hex`. Throws on a malformed key, secret or PIN. */
export async function wrapDataKey(secretHex: string, pin: string, dataKey: string): Promise<string> {
  buildPassphrase(secretHex, pin);
  checkedDataKey(dataKey);
  const salt = await randomHex(16);
  const stream = await keyStream(secretHex, salt, pin, dataKey.length);
  return `${salt}.${toHex(Uint8Array.from(dataKey, (ch, i) => ch.charCodeAt(0) ^ stream[i]))}`;
}

/** The data key inside `wrapped`, or null when the PIN is wrong (the result is not a data key) or anything is malformed. */
export async function unwrapDataKey(secretHex: string, pin: string, wrapped: string): Promise<string | null> {
  const match = WRAPPED.exec(wrapped);
  if (!match || !SECRET_HEX.test(secretHex) || !PIN_DIGITS.test(pin)) return null;
  const [, salt, body] = match;
  const stream = await keyStream(secretHex, salt, pin, body.length / 2);
  let key = "";
  for (let i = 0; i < body.length; i += 2) key += String.fromCharCode(parseInt(body.slice(i, i + 2), 16) ^ stream[i / 2]);
  return DATA_KEY.test(key) ? key : null;
}

/** The PIN-wrapped data key, or null for a store not yet moved to wrapped keys (it opens with buildPassphrase). */
export async function readPinWrap(userId: string): Promise<string | null> {
  return SecureStore.getItemAsync(pinWrapKey(await storeHash(userId)), OPTIONS);
}

export async function savePinWrap(userId: string, wrapped: string): Promise<void> {
  await SecureStore.setItemAsync(pinWrapKey(await storeHash(userId)), wrapped, OPTIONS);
}

/** The reset copy of the data key. Only interviewerDb's PIN reset (after a password sign-in) and its upkeep read it. */
export async function readResetCopy(userId: string): Promise<string | null> {
  return SecureStore.getItemAsync(resetCopyKey(await storeHash(userId)), OPTIONS);
}

export async function saveResetCopy(userId: string, dataKey: string): Promise<void> {
  await SecureStore.setItemAsync(resetCopyKey(await storeHash(userId)), checkedDataKey(dataKey), OPTIONS);
}

export async function failedAttempts(userId: string): Promise<number> {
  const raw = await SecureStore.getItemAsync(failuresKey(await storeHash(userId)), OPTIONS);
  const count = Number(raw ?? 0);
  return Number.isInteger(count) && count > 0 ? count : 0;
}

/** Count one more wrong PIN, note when, and return the new total. Called before the PIN is tried. */
export async function recordFailedAttempt(userId: string, now = Date.now()): Promise<number> {
  const hash = await storeHash(userId);
  const next = (await failedAttempts(userId)) + 1;
  await SecureStore.setItemAsync(failedAtKey(hash), String(now), OPTIONS);
  await SecureStore.setItemAsync(failuresKey(hash), String(next), OPTIONS);
  return next;
}

/** Set the counter; 0 also forgets the time of the last wrong PIN (a correct PIN or a reset ends the lockout). */
export async function setFailedAttempts(userId: string, count: number): Promise<void> {
  const hash = await storeHash(userId);
  if (count > 0) {
    await SecureStore.setItemAsync(failuresKey(hash), String(count), OPTIONS);
    return;
  }
  await SecureStore.deleteItemAsync(failuresKey(hash), OPTIONS);
  await SecureStore.deleteItemAsync(failedAtKey(hash), OPTIONS);
}

/** How long the store refuses PINs after `failures` wrong ones in a row: 0 for the first FREE_PIN_ATTEMPTS - 1. */
export function pinLockMs(failures: number): number {
  if (failures < FREE_PIN_ATTEMPTS) return 0;
  return LOCK_MINUTES[Math.min(failures - FREE_PIN_ATTEMPTS, LOCK_MINUTES.length - 1)] * 60_000;
}

/**
 * Milliseconds until this store takes a PIN again (0 = now). Counted from the stored time of the last wrong PIN,
 * so it survives a restart. A clock set back before that time restarts the full wait from now (stored), so it is
 * never shortened that way; a clock set forward does shorten it (no restart-proof clock on the phone).
 */
export async function pinLockRemainingMs(userId: string, now = Date.now()): Promise<number> {
  const wait = pinLockMs(await failedAttempts(userId));
  if (!wait) return 0;
  const hash = await storeHash(userId);
  let at = Number(await SecureStore.getItemAsync(failedAtKey(hash), OPTIONS));
  if (!Number.isFinite(at) || at <= 0 || at > now) {
    at = now;
    await SecureStore.setItemAsync(failedAtKey(hash), String(at), OPTIONS);
  }
  return Math.max(0, at + wait - now);
}

/** What the unlock screen shows while locked: the count, the wait left, and whether a PIN reset is possible. */
export async function pinUnlockState(userId: string): Promise<{ failures: number; lockedMs: number; canReset: boolean }> {
  return {
    failures: await failedAttempts(userId),
    lockedMs: await pinLockRemainingMs(userId),
    canReset: (await readResetCopy(userId)) !== null
  };
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

/** What the labels call the biometric: Face ID or Touch ID on iOS; fingerprint elsewhere (Android wording unchanged). */
export type BiometricKind = "fingerprint" | "face" | "touch";

export async function biometricKind(): Promise<BiometricKind> {
  if (Platform.OS !== "ios") return "fingerprint";
  try {
    const types = await LocalAuthentication.supportedAuthenticationTypesAsync();
    return types.includes(LocalAuthentication.AuthenticationType.FACIAL_RECOGNITION) ? "face" : "touch";
  } catch {
    return "touch";
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

/** The length of the PIN set on this phone, or null when unknown (a phone set up before this was recorded). */
export async function storedPinLength(userId: string): Promise<number | null> {
  const n = Number(await SecureStore.getItemAsync(pinLengthKey(await storeHash(userId)), OPTIONS));
  return Number.isInteger(n) && n >= PIN_MIN_LENGTH && n <= PIN_MAX_LENGTH ? n : null;
}

export async function recordPinLength(userId: string, length: number): Promise<void> {
  await SecureStore.setItemAsync(pinLengthKey(await storeHash(userId)), String(length), OPTIONS);
}

/** Forget this interviewer's secret, key copies, counter and biometric / screen-lock PIN. Other interviewers are untouched. */
export async function forgetStoreKeys(userId: string): Promise<void> {
  const hash = await storeHash(userId);
  await SecureStore.deleteItemAsync(secretKey(hash), OPTIONS);
  await SecureStore.deleteItemAsync(pinWrapKey(hash), OPTIONS);
  await SecureStore.deleteItemAsync(resetCopyKey(hash), OPTIONS);
  await SecureStore.deleteItemAsync(failuresKey(hash), OPTIONS);
  await SecureStore.deleteItemAsync(failedAtKey(hash), OPTIONS);
  await SecureStore.deleteItemAsync(offerKey(hash), OPTIONS);
  await SecureStore.deleteItemAsync(pinLengthKey(hash), OPTIONS);
  await disableBiometric(hash);
  await turnOffScreenLock(userId);
}
