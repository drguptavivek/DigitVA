/** Kept apart from auth.ts (native SecureStore) so screens can import it. */
import type { Account, Device } from "./auth";

/** The account was signed in on another server than this slot's device uses now (the phone was re-enrolled elsewhere). */
export function accountServerChanged(account: Pick<Account, "server">, device: Pick<Device, "server"> | undefined): boolean {
  return Boolean(device && account.server !== undefined && account.server !== device.server);
}

/** Kept before accounts recorded their server (standalone accounts have none to record): src/auth.ts bindLegacyAccounts. */
/**
 * The server of an account whose own server was never recorded and can no
 * longer be known (its slot lost its device before servers were recorded):
 * it matches no device, so the account is hidden and none of its tokens is
 * sent. Signing in as that person again on their own server records it.
 */
export const UNKNOWN_SERVER = "unknown";

export function lacksServer(account: Pick<Account, "server" | "standalone">): boolean {
  return !account.standalone && account.server === undefined;
}
