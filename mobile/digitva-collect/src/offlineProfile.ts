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
import type { Prefill } from "./cases";
import { interviewerNameFromAccount } from "./interviewerRecall";

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
  /** Optional org code naming a unit at any level of the project tree (owner decision 2026-10-27, Path C); a claim validated by the server on push. */
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

/** The profile fields a standalone interview needs before it starts (docs/policy/field-data-collection.md, Path C). */
export type StandaloneProfileField = "name" | "age_years" | "sex" | "country" | "hiv_mortality" | "malaria_mortality";

/** Interviewer age as the WHO form's Id10010a constraint accepts it: (. >= 18 and . < 90) or . = 99. */
const formAcceptsAge = (age: number | null | undefined): age is number =>
  typeof age === "number" && Number.isInteger(age) && ((age >= 18 && age < 90) || age === 99);

/**
 * The fields a standalone interview still lacks, in form order; empty means ready (owner decision 2026-10-30,
 * digitva-0vz7). Stricter than saveOfflineProfile, which enrolled offline coding shares: the values must be ones the
 * form accepts once prefilled and locked (a name with A-Z letters left, an age of 18 to 89 or 99), so no locked
 * answer can trap the interviewer.
 */
export function standaloneProfileMissing(profile: OfflineProfile | null | undefined): StandaloneProfileField[] {
  const missing: StandaloneProfileField[] = [];
  if (!interviewerNameFromAccount(profile?.name ?? "")) missing.push("name");
  if (!formAcceptsAge(profile?.age_years)) missing.push("age_years");
  if (!profile?.sex) missing.push("sex");
  if (!profile?.country?.trim()) missing.push("country");
  if (!profile?.hiv_mortality) missing.push("hiv_mortality");
  if (!profile?.malaria_mortality) missing.push("malaria_mortality");
  return missing;
}

const FORM_SEX = { male: "male", female: "female", other: "undetermined" } as const;
/** HIGH_LOW_VERY choice values (who-va-2022.instrument.json): high, low, veryl ("Very low"). */
const FORM_LEVEL = { high: "high", low: "low", none: "veryl" } as const;
const LOCKED = ["Id10010", "Id10010a", "Id10010b", "Id10002", "Id10003"];

/**
 * A new standalone interview's prefill from the profile: the interviewer's name, age and sex and the area HIV and
 * malaria levels, locked. The same shape the server builds for an enrolled case (interviewer, answers for the area
 * presets, lockedQuestionNames), so the form fills and locks them the same way. A value the form would not accept is
 * left out, and the engine only locks a question that holds an answer.
 */
export function standalonePrefill(profile: OfflineProfile): Prefill {
  const answers: Record<string, string> = {};
  if (profile.hiv_mortality) answers.Id10002 = FORM_LEVEL[profile.hiv_mortality];
  if (profile.malaria_mortality) answers.Id10003 = FORM_LEVEL[profile.malaria_mortality];
  const name = interviewerNameFromAccount(profile.name);
  return {
    interviewer: {
      ...(name ? { name } : {}),
      ...(formAcceptsAge(profile.age_years) ? { age: profile.age_years } : {}),
      ...(profile.sex ? { sex: FORM_SEX[profile.sex] } : {}),
    },
    answers,
    lockedQuestionNames: [...LOCKED],
  };
}
