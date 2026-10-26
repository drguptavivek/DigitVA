/**
 * Per-install device identity for Collect Plus offline coding (phase 1): a UUID v4 minted once, kept as JSON in
 * Keystore-backed SecureStore, and returned unchanged afterwards. It gives offline-coded cases a stable device
 * reference with no server in the loop. The plain build and the web must never mint one; production callers use
 * getOrCreatePlusDeviceIdentity, which refuses there. Unreadable stored JSON (corrupt or wrong shape) regenerates
 * rather than failing every later call.
 */
import { randomUUID } from "expo-crypto";
import { Platform } from "react-native";
import * as SecureStore from "expo-secure-store";

import { isPlusVariant } from "./appVariant";

export interface DeviceIdentity {
  uuid: string;
  created_at: string;
}

const IDENTITY_KEY = "offline_device_identity";
const OPTIONS: SecureStore.SecureStoreOptions = {
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
};

function isDeviceIdentity(value: unknown): value is DeviceIdentity {
  return (
    typeof value === "object" &&
    value !== null &&
    "uuid" in value &&
    typeof value.uuid === "string" &&
    value.uuid !== "" &&
    "created_at" in value &&
    typeof value.created_at === "string" &&
    value.created_at !== ""
  );
}

/** The stored identity, or undefined when the key is absent or unreadable (the caller mints a fresh one). */
async function readStoredIdentity(): Promise<DeviceIdentity | undefined> {
  const raw = await SecureStore.getItemAsync(IDENTITY_KEY, OPTIONS);
  if (!raw) return undefined;
  try {
    const parsed: unknown = JSON.parse(raw);
    return isDeviceIdentity(parsed) ? parsed : undefined;
  } catch {
    return undefined;
  }
}

async function mintIdentity(): Promise<DeviceIdentity> {
  const identity: DeviceIdentity = { uuid: randomUUID(), created_at: new Date().toISOString() };
  await SecureStore.setItemAsync(IDENTITY_KEY, JSON.stringify(identity), OPTIONS);
  return identity;
}

// Two callers racing on a first read must share one mint, or each keeps a different identity for the session.
let minting: Promise<DeviceIdentity> | undefined;

export async function getOrCreateDeviceIdentity(): Promise<DeviceIdentity> {
  const stored = await readStoredIdentity();
  if (stored) return stored;
  minting ??= mintIdentity().finally(() => {
    minting = undefined;
  });
  return minting;
}

/** Plus-only entry (Android Collect Plus): null on the web and on plain builds, so no identity is ever minted there. */
export async function getOrCreatePlusDeviceIdentity(
  extra?: Record<string, unknown>,
  hasEngineModule?: () => boolean,
): Promise<DeviceIdentity | null> {
  if (Platform.OS !== "android" || !isPlusVariant(extra, hasEngineModule)) return null;
  return getOrCreateDeviceIdentity();
}
