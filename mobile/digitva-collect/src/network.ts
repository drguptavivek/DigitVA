/**
 * Phone network state (docs/policy/expo-client.md, "Offline gate"). Offline means expo-network reports no connection
 * or no reachable internet; an unknown reachability counts as online so calls are never blocked on a guess. Inert
 * until `startNetworkWatch` runs (native shell only), so the web client is unchanged.
 */
import { addNetworkStateListener, getNetworkStateAsync, type NetworkState } from "expo-network";
import { useSyncExternalStore } from "react";

/** Thrown instead of calling the server while offline. A TypeError so existing "no network" handling applies. */
export class OfflineError extends TypeError {
  constructor() {
    super("offline");
    this.name = "OfflineError";
  }
}

/**
 * A request that never reached the server. A TypeError, like the fetch of React Native and browsers, so the "no
 * network" handling applies; iOS's expo fetch instead rejects with a plain Error ("fetch failed: ... Could not
 * connect to the server"), which serverFetch turns into this.
 */
export class NetworkError extends TypeError {
  constructor(cause: unknown) {
    super(cause instanceof Error ? cause.message : "network request failed");
    this.name = "NetworkError";
  }
}

// The messages fetch rejects with when no response arrived: Chrome and Android, Safari, Firefox, React Native, and a
// lazy chunk that could not download. A TypeError matching none of them is a code bug, not a connection problem.
const FETCH_FAILURE = /failed to fetch|load failed|network ?error|network request (failed|timed out)|network connection was lost|internet connection appears to be offline|fetch failed|dynamically imported module|importing a module script/i;

/** True only for a request that never got a response; any other TypeError is a bug and must not read as "offline". */
export function isFetchFailure(error: unknown): boolean {
  if (error instanceof OfflineError || error instanceof NetworkError) return true;
  return error instanceof TypeError && FETCH_FAILURE.test(error.message);
}

/** fetch whose transport failures are always TypeErrors; an abort (timeout or caller) rejects as it did. */
export async function serverFetch(url: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch (error) {
    if (error instanceof TypeError || init.signal?.aborted) throw error;
    throw new NetworkError(error);
  }
}

let offline = false;
/** Bumped at each connectivity change and each good response; the error log files a network failure once per value. */
let spell = 0;
const listeners = new Set<() => void>();
const reconnectListeners = new Set<() => void>();

export const isOffline = (): boolean => offline;
export const networkSpell = (): number => spell;

/** Throws OfflineError while offline; call before any server request. */
export function assertOnline(): void {
  if (offline) throw new OfflineError();
}

/** A response arrived: the current spell of network failures (if any were logged) is over. */
export function noteRequestOk(): void {
  spell += 1;
}

function apply(state: Pick<NetworkState, "isConnected" | "isInternetReachable">): void {
  const next = state.isConnected === false || state.isInternetReachable === false;
  if (next === offline) return;
  offline = next;
  spell += 1;
  listeners.forEach((listener) => listener());
  if (!next) reconnectListeners.forEach((listener) => listener());
}

/** Read the state once and follow changes. Returns the unsubscribe. */
export function startNetworkWatch(): () => void {
  const subscription = addNetworkStateListener(apply);
  void getNetworkStateAsync().then(apply, () => undefined);
  return () => subscription.remove();
}

/** Called when the phone goes from offline to online. Returns the unsubscribe. */
export function onReconnect(listener: () => void): () => void {
  reconnectListeners.add(listener);
  return () => void reconnectListeners.delete(listener);
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => void listeners.delete(listener);
}

export function useIsOffline(): boolean {
  return useSyncExternalStore(subscribe, isOffline, isOffline);
}

/** Test hook. */
export function resetNetwork(): void {
  offline = false;
  spell = 0;
  listeners.clear();
  reconnectListeners.clear();
}
