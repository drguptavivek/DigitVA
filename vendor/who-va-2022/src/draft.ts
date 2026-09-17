/**
 * Cross-platform draft identifiers and the browser localStorage draft-store
 * adapter. Native hosts provide their own implementation of the same contract.
 */
import type { AnswerValue, SubmissionData, WhoVaDraft, WhoVaDraftStore } from "./types.js";
import { WHO_VA_FORM_VERSION } from "./version.js";

export const WHO_VA_DRAFT_KEY_PREFIX = "who-va-2022:draft:";
export const WHO_VA_DRAFT_SCHEMA_VERSION = 1 as const;

export interface DraftKeyValueStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

function randomBytes(): Uint8Array {
  const bytes = new Uint8Array(16);
  if (globalThis.crypto?.getRandomValues) return globalThis.crypto.getRandomValues(bytes);
  for (let index = 0; index < bytes.length; index += 1) bytes[index] = Math.floor(Math.random() * 256);
  return bytes;
}

export function createDraftId(): string {
  if (typeof globalThis.crypto?.randomUUID === "function") return globalThis.crypto.randomUUID();
  const bytes = randomBytes();
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40;
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value != null && typeof value === "object" && !Array.isArray(value);
}

function isAnswerValue(value: unknown): value is AnswerValue | undefined {
  if (value == null || ["string", "boolean"].includes(typeof value)) return true;
  if (typeof value === "number") return Number.isFinite(value);
  if (Array.isArray(value)) return value.every((item) => typeof item === "string");
  return isRecord(value);
}

function decodedSubmissionData(value: unknown): SubmissionData | undefined {
  if (!isRecord(value)) return undefined;
  return Object.values(value).every(isAnswerValue) ? (value as SubmissionData) : undefined;
}

function requiredString(value: Record<string, unknown>, property: string): string {
  const candidate = value[property];
  if (typeof candidate !== "string" || candidate.trim() === "") {
    throw new Error(`Stored WHO VA draft has an invalid ${property}`);
  }
  return candidate;
}

/** Validates persisted data and migrates the pre-versioned draft envelope to schema version 1. */
export function decodeWhoVaDraft(value: unknown): WhoVaDraft {
  if (!isRecord(value)) throw new Error("Stored WHO VA draft must be an object");
  const schemaVersion = value.schemaVersion ?? WHO_VA_DRAFT_SCHEMA_VERSION;
  if (schemaVersion !== WHO_VA_DRAFT_SCHEMA_VERSION) {
    throw new Error(`Unsupported WHO VA draft schema version '${String(schemaVersion)}'`);
  }
  const id = requiredString(value, "id");
  const instrumentId = requiredString(value, "instrumentId");
  const instrumentVersion = requiredString(value, "instrumentVersion");
  const currentSection = requiredString(value, "currentSection");
  const createdAt = requiredString(value, "createdAt");
  const updatedAt = requiredString(value, "updatedAt");
  if (Number.isNaN(Date.parse(createdAt)) || Number.isNaN(Date.parse(updatedAt))) {
    throw new Error("Stored WHO VA draft has invalid timestamps");
  }
  const data = decodedSubmissionData(value.data);
  if (!data) throw new Error("Stored WHO VA draft has invalid answer data");
  return {
    schemaVersion: WHO_VA_DRAFT_SCHEMA_VERSION,
    formVersion: value.formVersion === undefined ? WHO_VA_FORM_VERSION : requiredString(value, "formVersion"),
    id,
    instrumentId,
    instrumentVersion,
    currentSection,
    createdAt,
    updatedAt,
    data: { ...data }
  };
}

export function createLocalStorageDraftStore(storage?: DraftKeyValueStorage): WhoVaDraftStore {
  const resolveStorage = () => {
    const resolved = storage ?? globalThis.localStorage;
    if (!resolved) throw new Error("Local storage is unavailable; provide a WhoVaDraftStore adapter");
    return resolved;
  };
  return {
    save(draft) {
      resolveStorage().setItem(`${WHO_VA_DRAFT_KEY_PREFIX}${draft.id}`, JSON.stringify(draft));
    },
    load(id) {
      const serialized = resolveStorage().getItem(`${WHO_VA_DRAFT_KEY_PREFIX}${id}`);
      if (!serialized) return undefined;
      try {
        return decodeWhoVaDraft(JSON.parse(serialized) as unknown);
      } catch (error) {
        throw new Error(`Stored WHO VA draft '${id}' is invalid`, { cause: error });
      }
    },
    remove(id) {
      resolveStorage().removeItem(`${WHO_VA_DRAFT_KEY_PREFIX}${id}`);
    }
  };
}
