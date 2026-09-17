import * as SecureStore from "expo-secure-store";

import type { RegisteredUser } from "./LocalDatabase";

const ACCESS_TOKEN_KEY = "who_va_2022_auth_access_token";
const REFRESH_TOKEN_KEY = "who_va_2022_auth_refresh_token";
const USER_ID_KEY = "who_va_2022_auth_user_id";
const USER_PROFILE_KEY = "who_va_2022_auth_user_profile";
const API_BASE_URL_KEY = "who_va_2022_auth_api_base_url";
const LEGACY_AUTH_KEYS = [
  "who-va-2022:auth:access-token",
  "who-va-2022:auth:refresh-token",
  "who-va-2022:auth:user-id",
  "who-va-2022:auth:user-profile",
  "who-va-2022:auth:api-base-url"
];

export interface AuthTokens {
  accessToken: string;
  refreshToken: string;
}

export interface StoredAuthSession extends AuthTokens {
  user: RegisteredUser;
  apiBaseUrl: string;
}

export class SessionExpiredError extends Error {
  constructor(message = "Session expired. Please log in again.") {
    super(message);
    this.name = "SessionExpiredError";
  }
}

function normalizeApiBaseUrl(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return trimmed;
  const withProtocol = /^https?:\/\//iu.test(trimmed) ? trimmed : `http://${trimmed}`;
  try {
    const url = new URL(withProtocol);
    url.pathname = url.pathname.replace(/\/api(?:\/.*)?$/u, "");
    url.search = "";
    url.hash = "";
    return url.toString().replace(/\/$/u, "");
  } catch {
    return withProtocol.replace(/\/api(?:\/.*)?$/u, "");
  }
}

async function setSecureValue(key: string, value: string): Promise<void> {
  await SecureStore.setItemAsync(key, value, {
    keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY
  });
}

export async function saveAuthSession(session: StoredAuthSession): Promise<void> {
  await Promise.all([
    setSecureValue(ACCESS_TOKEN_KEY, session.accessToken),
    setSecureValue(REFRESH_TOKEN_KEY, session.refreshToken),
    setSecureValue(USER_ID_KEY, session.user.userId),
    setSecureValue(USER_PROFILE_KEY, JSON.stringify(session.user)),
    setSecureValue(API_BASE_URL_KEY, normalizeApiBaseUrl(session.apiBaseUrl))
  ]);
}

export async function loadAuthSession(): Promise<StoredAuthSession | undefined> {
  const [accessToken, refreshToken, userProfile, apiBaseUrl] = await Promise.all([
    SecureStore.getItemAsync(ACCESS_TOKEN_KEY),
    SecureStore.getItemAsync(REFRESH_TOKEN_KEY),
    SecureStore.getItemAsync(USER_PROFILE_KEY),
    SecureStore.getItemAsync(API_BASE_URL_KEY)
  ]);
  if (!accessToken || !refreshToken || !userProfile || !apiBaseUrl) return undefined;
  try {
    return {
      accessToken,
      refreshToken,
      user: JSON.parse(userProfile) as RegisteredUser,
      apiBaseUrl
    };
  } catch {
    await clearSecureAuthValues();
    return undefined;
  }
}

export async function loadStoredUserId(): Promise<string | undefined> {
  return (await SecureStore.getItemAsync(USER_ID_KEY)) ?? undefined;
}

export async function clearSecureAuthValues(): Promise<void> {
  await Promise.all([
    SecureStore.deleteItemAsync(ACCESS_TOKEN_KEY),
    SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY),
    SecureStore.deleteItemAsync(USER_ID_KEY),
    SecureStore.deleteItemAsync(USER_PROFILE_KEY),
    SecureStore.deleteItemAsync(API_BASE_URL_KEY),
    ...LEGACY_AUTH_KEYS.map((key) => SecureStore.deleteItemAsync(key))
  ]);
}

export async function revokeRefreshToken(apiBaseUrl?: string): Promise<void> {
  const session = await loadAuthSession();
  if (!session?.refreshToken || !apiBaseUrl) return;
  const url = `${normalizeApiBaseUrl(apiBaseUrl).replace(/\/$/u, "")}/api/logout`;
  try {
    await fetch(url, {
      method: "POST",
      headers: {
        authorization: `Bearer ${session.accessToken}`,
        "content-type": "application/json"
      },
      body: JSON.stringify({ refreshToken: session.refreshToken })
    });
  } catch {
    // Local cleanup must still continue when the device is offline.
  }
}

async function refreshAuthSession(apiBaseUrl: string): Promise<StoredAuthSession> {
  const session = await loadAuthSession();
  if (!session?.refreshToken) throw new SessionExpiredError();
  const url = `${normalizeApiBaseUrl(apiBaseUrl).replace(/\/$/u, "")}/api/refresh-token`;
  const response = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ refreshToken: session.refreshToken })
  });
  const responseText = await response.text();
  const body = responseText
    ? (JSON.parse(responseText) as {
        ok?: boolean;
        accessToken?: string;
        refreshToken?: string;
        user?: RegisteredUser;
        error?: string;
      })
    : {};
  if (!response.ok || !body.ok || !body.accessToken || !body.refreshToken || !body.user) {
    await clearSecureAuthValues();
    throw new SessionExpiredError(body.error);
  }
  const nextSession: StoredAuthSession = {
    accessToken: body.accessToken,
    refreshToken: body.refreshToken,
    user: body.user,
    apiBaseUrl
  };
  await saveAuthSession(nextSession);
  return nextSession;
}

export async function fetchWithAuth(
  apiBaseUrl: string,
  path: string,
  init: RequestInit = {}
): Promise<Response> {
  const session = await loadAuthSession();
  if (!session?.accessToken) throw new SessionExpiredError();
  const url = `${normalizeApiBaseUrl(apiBaseUrl).replace(/\/$/u, "")}${path}`;
  const headers = new Headers(init.headers);
  headers.set("authorization", `Bearer ${session.accessToken}`);
  const response = await fetch(url, { ...init, headers });
  if (response.status !== 401) return response;

  const refreshed = await refreshAuthSession(apiBaseUrl);
  const retryHeaders = new Headers(init.headers);
  retryHeaders.set("authorization", `Bearer ${refreshed.accessToken}`);
  const retry = await fetch(url, { ...init, headers: retryHeaders });
  if (retry.status === 401) {
    await clearSecureAuthValues();
    throw new SessionExpiredError();
  }
  return retry;
}
