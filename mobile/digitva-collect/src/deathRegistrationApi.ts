/** Native-only API calls for registration-only accounts. */
import {
  ApiError,
  INTAKE_API,
  parseRegisteredDeathPage,
  type AccessSummary,
  type RegistrationInput,
  type RegisteredDeathPage,
} from "./api";
import { authedRequest, refreshAccessSummaryForAction } from "./auth";

export type RegistrationChanges = Partial<Omit<RegistrationInput, "project_id" | "site_id" | "org_unit_id">>;

export interface RegistrationCase {
  death_id: string;
  project_id: string;
  site_id: string;
  org_unit_id?: string | null;
  state: string;
  details_pending?: boolean;
  other_complete_interview?: boolean;
  updated_at: string;
  deceased: { name?: string | null; sex?: string | null; date_of_death?: string | null; date_of_birth?: string | null; date_of_birth_partial?: string | null; age_years?: number | null; place_of_death?: string | null };
  household_address: { address?: string | null; house_street?: string | null; village_ward?: string | null; landmark?: string | null };
  informant: { name?: string | null; phone?: string | null; phone_2?: string | null };
  remarks?: string | null;
  abha_number?: string | null;
  abha_address?: string | null;
  father_name?: string | null;
  mother_name?: string | null;
  links: Record<string, unknown>;
}

/** Read current registration and interview reach without form reference data. */
export async function getDeathRegistrationAccess(userId: string): Promise<AccessSummary | undefined> {
  try {
    return await refreshAccessSummaryForAction(userId);
  } catch (error) {
    if (error instanceof TypeError) return undefined;
    throw error;
  }
}

/** Read one server-bounded page of the current account's registered deaths. */
export async function getNativeRegisteredDeaths(
  userId: string,
  registeredMine: boolean,
  cursor?: string | null,
): Promise<RegisteredDeathPage> {
  const params = new URLSearchParams({ limit: "50" });
  if (registeredMine) params.set("registered", "mine");
  if (cursor) params.set("cursor", cursor);
  const { body } = await authedRequest<unknown>(userId, `${INTAKE_API}/deaths?${params}`);
  return parseRegisteredDeathPage(body);
}

/** Submit one online registration and reject an interview-shaped response. */
export async function postNativeDeathRegistration(
  userId: string,
  input: RegistrationInput & { client_death_id: string },
): Promise<{ death_id: string; unique_id: string }> {
  const { body } = await authedRequest<unknown>(userId, `${INTAKE_API}/deaths`, {
    method: "POST",
    body: input,
  });
  const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
  if (!record(body) || !record(body.case) || typeof body.case.death_id !== "string" ||
      typeof body.case.unique_id !== "string" || "prefill" in body.case ||
      !record(body.case.links) || typeof body.case.links.update !== "string" ||
      !body.case.links.update.startsWith(`${INTAKE_API}/deaths/`) ||
      Object.keys(body.case.links).some((key) => key !== "update")) {
    throw new ApiError(200, "malformed_response");
  }
  return { death_id: body.case.death_id, unique_id: body.case.unique_id };
}

/** Fetch a single authorised interviewer case before editing its registration. */
export async function getNativeRegistrationCase(userId: string, deathId: string): Promise<RegistrationCase> {
  const { body } = await authedRequest<unknown>(userId, `${INTAKE_API}/cases/${encodeURIComponent(deathId)}`);
  if (!record(body) || !isRegistrationCase(body.case) || body.case.death_id !== deathId) {
    throw new ApiError(200, "malformed_response");
  }
  return body.case;
}

/** Apply only changed form fields; empty strings intentionally clear stored values. */
export async function patchNativeDeathRegistration(
  userId: string,
  deathId: string,
  changes: RegistrationChanges,
  ifUpdatedAt?: string,
): Promise<RegistrationCase> {
  const { body } = await authedRequest<unknown>(userId, `${INTAKE_API}/deaths/${encodeURIComponent(deathId)}`, {
    method: "PATCH",
    body: { ...changes, ...(ifUpdatedAt ? { if_updated_at: ifUpdatedAt } : {}) },
  });
  if (!record(body) || !isRegistrationCase(body.case) || body.case.death_id !== deathId) {
    throw new ApiError(200, "malformed_response");
  }
  return body.case;
}

function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function isRegistrationCase(value: unknown): value is RegistrationCase {
  if (!record(value) || typeof value.death_id !== "string" || !value.death_id || typeof value.project_id !== "string" || !value.project_id ||
      typeof value.site_id !== "string" || !value.site_id || typeof value.state !== "string" || !value.state ||
      typeof value.updated_at !== "string" || !value.updated_at ||
      !(value.org_unit_id === undefined || value.org_unit_id === null || typeof value.org_unit_id === "string") ||
      !record(value.deceased) || !record(value.household_address) || !record(value.informant) || !record(value.links)) return false;
  const links = value.links;
  const stringFields = [
    [value.deceased, ["name", "sex", "date_of_death", "date_of_birth", "date_of_birth_partial", "place_of_death"]],
    [value.household_address, ["address", "house_street", "village_ward", "landmark"]],
    [value.informant, ["name", "phone", "phone_2"]],
    [value, ["remarks", "abha_number", "abha_address", "father_name", "mother_name"]],
  ] as const;
  if (stringFields.some(([source, keys]) => keys.some((key) => source[key] !== undefined && source[key] !== null && typeof source[key] !== "string"))) return false;
  if (value.deceased.age_years !== undefined && value.deceased.age_years !== null &&
      (typeof value.deceased.age_years !== "number" || !Number.isFinite(value.deceased.age_years))) return false;
  const linkNames = Object.keys(links);
  if (linkNames.length === 1 && linkNames[0] === "update") return typeof links.update === "string";
  return ["self", "attempts", "visit"].every((key) => typeof links[key] === "string");
}
