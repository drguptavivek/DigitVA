/**
 * Coder/facility profile for Collect Plus pure-offline coding (phase 1): who coded, where, and the SmartVA
 * endemicity inputs, captured on-device and kept as JSON in Keystore-backed SecureStore. It is the provenance
 * a future offline-coding sync attributes records to (together with the device identity); nothing here ever
 * reaches a server or a log in this phase. The plain build and the web never write one: saveOfflineProfile
 * refuses outside Collect Plus, like the device identity's gate.
 */
import { Platform } from "react-native";
import * as SecureStore from "expo-secure-store";

import { isPlusVariant } from "./appVariant";

export interface OfflineProfile {
  /** Coder name. */
  name: string;
  age_years: number | null;
  sex: "male" | "female" | "other" | null;
  /** e.g. health worker, coder. */
  designation: string;
  /** Facility / organization name. */
  facility_name: string;
  country: string;
  state: string;
  /** Optional org code naming the facility unit (owner default, Path C); a claim validated by the server on push. */
  org_code?: string;
  /** SmartVA HIV adjustment input. */
  hiv_mortality: "none" | "low" | "high" | null;
  /** SmartVA malaria endemicity input. */
  malaria_mortality: "none" | "low" | "high" | null;
  updated_at: string;
}

const PROFILE_KEY = "offline_profile";
const OPTIONS: SecureStore.SecureStoreOptions = {
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
};

const MORTALITY_LEVELS = ["none", "low", "high"] as const;
const SEXES = ["male", "female", "other"] as const;

class OfflineProfileError extends Error {
  constructor(readonly code: string) {
    super(code);
    this.name = "OfflineProfileError";
  }
}

function trimmedText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function nullableText(value: unknown): string | null {
  const text = trimmedText(value);
  return text === "" ? null : text;
}

function nullableChoice<T extends string>(value: unknown, allowed: readonly T[]): T | null {
  return (allowed as readonly string[]).includes(value as string) ? (value as T) : null;
}

/** A plausible coder age: a whole number, or null when not answered. Anything else fails the save. */
function nullableAgeYears(value: unknown): number | null | undefined {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= 130) return value;
  if (typeof value === "string" && /^-?\d+$/.test(value.trim())) return nullableAgeYears(Number(value.trim()));
  return undefined;
}

/** The saved profile, or null when none was saved yet (an unreadable one counts as none; the form re-saves it). */
export async function getOfflineProfile(): Promise<OfflineProfile | null> {
  const raw = await SecureStore.getItemAsync(PROFILE_KEY, OPTIONS);
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    return isOfflineProfile(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function isOfflineProfile(value: unknown): value is OfflineProfile {
  if (typeof value !== "object" || value === null) return false;
  const profile = value as Record<string, unknown>;
  return (
    typeof profile.name === "string" &&
    profile.name !== "" &&
    typeof profile.country === "string" &&
    profile.country !== "" &&
    typeof profile.updated_at === "string" &&
    (profile.age_years === null || typeof profile.age_years === "number")
  );
}

/**
 * Validate, trim, stamp and persist the profile. Name and country are required; every other field may be
 * left out (null or blank). Throws OfflineProfileError with a short code the form can name.
 */
export async function saveOfflineProfile(input: OfflineProfile): Promise<void> {
  if (Platform.OS !== "android" || !isPlusVariant()) throw new OfflineProfileError("offline_profile_plus_only");
  const name = trimmedText(input.name);
  if (!name) throw new OfflineProfileError("offline_profile_name_required");
  const country = trimmedText(input.country);
  if (!country) throw new OfflineProfileError("offline_profile_country_required");
  const ageYears = nullableAgeYears(input.age_years);
  if (ageYears === undefined) throw new OfflineProfileError("offline_profile_age_invalid");
  const profile: OfflineProfile = {
    name,
    age_years: ageYears,
    sex: nullableChoice(input.sex, SEXES),
    designation: nullableText(input.designation) ?? "",
    facility_name: nullableText(input.facility_name) ?? "",
    country,
    state: nullableText(input.state) ?? "",
    org_code: nullableText(input.org_code) ?? "",
    hiv_mortality: nullableChoice(input.hiv_mortality, MORTALITY_LEVELS),
    malaria_mortality: nullableChoice(input.malaria_mortality, MORTALITY_LEVELS),
    updated_at: new Date().toISOString(),
  };
  await SecureStore.setItemAsync(PROFILE_KEY, JSON.stringify(profile), OPTIONS);
}
