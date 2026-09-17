import type { RegisteredUser } from "./LocalDatabase";

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

export async function saveAuthSession(_session: StoredAuthSession): Promise<void> {
  return undefined;
}

export async function loadAuthSession(): Promise<StoredAuthSession | undefined> {
  return undefined;
}

export async function loadStoredUserId(): Promise<string | undefined> {
  return undefined;
}

export async function clearSecureAuthValues(): Promise<void> {
  return undefined;
}

export async function revokeRefreshToken(_apiBaseUrl?: string): Promise<void> {
  return undefined;
}

export async function fetchWithAuth(apiBaseUrl: string, path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(`${apiBaseUrl.replace(/\/$/u, "")}${path}`, init);
}
