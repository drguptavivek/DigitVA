import type { SubmissionData } from "./types.js";

export type WhoVaKnownSex = "female" | "male" | "undetermined";
export type WhoVaKnownLanguage = string;
export type WhoVaMortalityLevel = "high" | "low" | "veryl";
export type WhoVaCitizenship = "citizen_at_birth" | "naturalized_citizen" | "foreign_national" | "dk" | "ref";

export interface WhoVaLocationPrefill {
  country?: string;
  state?: string;
  district?: string;
  village?: string;
  deathPlace?: string;
}

export interface WhoVaPresetPrefill {
  hivAidsMortality?: WhoVaMortalityLevel;
  malariaMortality?: WhoVaMortalityLevel;
}

interface WhoVaDeceasedPrefillCommon {
  givenNames?: string;
  surname?: string;
  sex?: WhoVaKnownSex;
  citizenship?: WhoVaCitizenship;
}

type WhoVaBirthEvidence =
  | { dateOfBirth: string; ageInYears?: never }
  | { dateOfBirth?: never; ageInYears: number }
  | { dateOfBirth?: undefined; ageInYears?: undefined };

type WhoVaDeathEvidence =
  | { dateOfDeath: string; yearOfDeath?: never }
  | { dateOfDeath?: never; yearOfDeath: string }
  | { dateOfDeath?: undefined; yearOfDeath?: undefined };

export type WhoVaDeceasedPrefill = WhoVaDeceasedPrefillCommon & WhoVaBirthEvidence & WhoVaDeathEvidence;

export interface WhoVaInterviewerPrefill {
  name?: string;
  age?: number;
  sex?: WhoVaKnownSex;
  id?: string;
  language?: WhoVaKnownLanguage;
}

export interface WhoVaHostPrefill {
  deceased?: WhoVaDeceasedPrefill;
  interviewer?: WhoVaInterviewerPrefill;
  location?: WhoVaLocationPrefill;
  presets?: WhoVaPresetPrefill;
}

function addString(data: SubmissionData, name: string, value: string | undefined): void {
  const trimmed = value?.trim();
  if (trimmed) data[name] = trimmed;
}

function addNumber(data: SubmissionData, name: string, value: number | undefined): void {
  if (value != null && Number.isFinite(value)) data[name] = value;
}

function formatLocation(location: WhoVaLocationPrefill | undefined): string | undefined {
  if (!location) return undefined;
  const structured = [location.country, location.state, location.district, location.village]
    .map((part) => part?.trim())
    .filter((part): part is string => Boolean(part));
  const deathPlace = location.deathPlace?.trim();
  if (structured.length && deathPlace) return `${structured.join(", ")}; ${deathPlace}`;
  return structured.join(", ") || deathPlace || undefined;
}

function addPresets(data: SubmissionData, presets: WhoVaPresetPrefill | undefined): void {
  if (presets?.hivAidsMortality) data.Id10002 = presets.hivAidsMortality;
  if (presets?.malariaMortality) data.Id10003 = presets.malariaMortality;
}

function addInterviewer(data: SubmissionData, interviewer: WhoVaInterviewerPrefill | undefined): void {
  addString(data, "Id10010", interviewer?.name);
  addNumber(data, "Id10010a", interviewer?.age);
  if (interviewer?.sex) data.Id10010b = interviewer.sex;
  addString(data, "Id10010c", interviewer?.id);
  if (interviewer?.language) data.language = interviewer.language;
}

function addDeceased(data: SubmissionData, deceased: WhoVaDeceasedPrefill | undefined): void {
  if (deceased?.dateOfBirth && deceased.ageInYears != null) {
    throw new Error("Provide either deceased.dateOfBirth or deceased.ageInYears, not both");
  }
  if (deceased?.dateOfDeath && deceased.yearOfDeath) {
    throw new Error("Provide either deceased.dateOfDeath or deceased.yearOfDeath, not both");
  }
  addString(data, "Id10017", deceased?.givenNames);
  addString(data, "Id10018", deceased?.surname);
  if (deceased?.sex) data.Id10019 = deceased.sex;
  if (deceased?.citizenship) {
    data.Id10051 = "yes";
    data.Id10052 = deceased.citizenship;
  }

  if (deceased?.dateOfBirth) {
    data.Id10020 = "yes";
    data.Id10021 = deceased.dateOfBirth;
  } else if (deceased?.ageInYears != null && deceased.ageInYears > 11) {
    data.Id10020 = "no";
    data.age_group = "adult";
    data.age_adult = deceased.ageInYears;
  }

  if (deceased?.dateOfDeath) {
    data.Id10022 = "yes";
    if (deceased?.dateOfBirth) data.Id10023_a = deceased.dateOfDeath;
    else data.Id10023_b = deceased.dateOfDeath;
  } else if (deceased?.yearOfDeath) {
    data.Id10022 = "no";
    data.Id10024 = deceased.yearOfDeath;
  }
}

function addLocation(data: SubmissionData, location: WhoVaLocationPrefill | undefined): void {
  const formattedLocation = formatLocation(location);
  if (!formattedLocation) return;
  data.Id10051 = "yes";
  data.Id10057 = formattedLocation;
}

/**
 * Converts host application context into canonical WHO VA question answers.
 *
 * Keep host-only identifiers, such as a death-list UUID or RBAC assignment ID,
 * outside the WHO submission payload. Use the form `draftId`, your app route
 * state, or your server submission envelope for those identifiers.
 */
export function createWhoVaInitialDataFromPrefill(prefill: WhoVaHostPrefill): SubmissionData {
  const data: SubmissionData = {};
  addPresets(data, prefill.presets);
  addInterviewer(data, prefill.interviewer);
  addDeceased(data, prefill.deceased);
  addLocation(data, prefill.location);
  return data;
}
