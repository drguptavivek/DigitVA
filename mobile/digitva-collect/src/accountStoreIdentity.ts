import * as SecureStore from "expo-secure-store";

import { AccountStoreCollisionError } from "./authErrors";
import type { Slot } from "./auth";

const OPTIONS: SecureStore.SecureStoreOptions = {
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
};
const ACCOUNT_KEYS: Record<Slot, string> = { active: "accounts", demo: "demo.accounts" };

type StoredAccount = { user_id: string; server?: string; standalone?: boolean };

async function readSlots(): Promise<Record<Slot, StoredAccount[]>> {
  const [activeRaw, demoRaw] = await Promise.all(([
    SecureStore.getItemAsync(ACCOUNT_KEYS.active, OPTIONS),
    SecureStore.getItemAsync(ACCOUNT_KEYS.demo, OPTIONS),
  ]));
  const parse = (raw: string | null): StoredAccount[] => {
    if (raw === null) return [];
    try {
      const value: unknown = JSON.parse(raw);
      if (!Array.isArray(value) || value.some((account) =>
        typeof account !== "object" || account === null ||
        typeof account.user_id !== "string" ||
        (account.server !== undefined && typeof account.server !== "string") ||
        (account.standalone !== undefined && typeof account.standalone !== "boolean"),
      )) throw new Error();
      return value;
    } catch {
      throw new AccountStoreCollisionError();
    }
  };
  return { active: parse(activeRaw), demo: parse(demoRaw) };
}

export async function loadAccountsForSlot(slot: Slot): Promise<StoredAccount[]> {
  const slots = await readSlots();
  const accounts = slots[slot];
  const otherIds = new Set(slots[slot === "active" ? "demo" : "active"].map(({ user_id }) => user_id));
  const seen = new Set<string>();
  for (const { user_id } of accounts) {
    if (seen.has(user_id) || otherIds.has(user_id)) throw new AccountStoreCollisionError();
    seen.add(user_id);
  }
  return accounts;
}

/** Refuse token access when legacy account lists bind this store ID more than once. */
export async function assertAccountStoreIdentitySafe(userId: string): Promise<void> {
  const slots = await readSlots();
  const count = [...slots.active, ...slots.demo].filter((account) => account.user_id === userId).length;
  if (count > 1) throw new AccountStoreCollisionError();
}

/** Resolve the mode that owns an account ID without exposing either slot's credentials. */
export async function accountStoreIdentityMode(userId: string): Promise<"selected" | "other" | "missing"> {
  const [slots, selectedValue] = await Promise.all([
    readSlots(),
    SecureStore.getItemAsync("active_slot", OPTIONS),
  ]);
  const selected: Slot = selectedValue === "demo" ? "demo" : "active";
  const matches = (["active", "demo"] as const)
    .flatMap((slot) => slots[slot]
      .filter((account) => account.user_id === userId)
      .map((account) => ({ slot, account })));
  if (matches.length > 1) throw new AccountStoreCollisionError();
  if (matches.length === 0) return "missing";
  return matches[0].slot === selected ? "selected" : "other";
}

/** A bearer token is usable only when its unique account entry belongs to the selected mode. */
export async function accountStoreIdentityIsInSelectedMode(userId: string): Promise<boolean> {
  return (await accountStoreIdentityMode(userId)) === "selected";
}

/** An unlocked SQLCipher identity must belong to the currently selected mode. */
export async function assertAccountStoreModeSafe(userId: string): Promise<void> {
  if ((await accountStoreIdentityMode(userId)) !== "selected") throw new AccountStoreCollisionError();
}

/** A session may replace only the same identity in the same slot and server mode. */
export async function assertAccountIdentityCanBeStored(
  userId: string,
  slot: Slot,
  server: string | undefined,
  standalone: boolean,
  legacyServer?: string,
): Promise<void> {
  const slots = await readSlots();
  const matches = (["active", "demo"] as const)
    .flatMap((storedSlot) => slots[storedSlot]
      .filter((account) => account.user_id === userId)
      .map((account) => ({ slot: storedSlot, account })));
  if (matches.length === 0) return;
  if (matches.length !== 1) throw new AccountStoreCollisionError();
  const [{ slot: storedSlot, account }] = matches;
  const matchesLegacyDevice = server !== undefined && account.server === undefined && legacyServer === server;
  if (storedSlot !== slot || (account.server !== server && !matchesLegacyDevice) ||
    (account.standalone === true) !== standalone) {
    throw new AccountStoreCollisionError();
  }
}
