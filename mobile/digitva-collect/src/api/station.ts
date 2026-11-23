/** Desktop station endpoints (launch-token session); calls go through ../api's shared transport. */
import { requestClientJson } from "../api";
import type { ClientCsrf } from "./types";

/** The never-online station's enrolment file, exactly as the server's Project Setup accepts it. */
export interface StationEnrolmentFile {
  device_id: string;
  signing_public_key: string;
  app_version?: string;
}

/** Desktop station only (launch token): GET the enrolment file from the local server. */
export async function fetchStationEnrolmentFile(csrf?: ClientCsrf): Promise<StationEnrolmentFile> {
  return requestClientJson<StationEnrolmentFile>("/api/v1/station/enrolment-file", { csrf });
}

/** The station's own plain facility details (desktop edition only). */
export interface StationFacility {
  name: string;
  code: string;
  type: string;
  address: string;
  district: string;
  state: string;
}

export async function fetchStationFacility(csrf?: ClientCsrf): Promise<StationFacility> {
  return requestClientJson<StationFacility>("/api/v1/station/facility", { csrf });
}

export async function saveStationFacility(facility: StationFacility, csrf: ClientCsrf): Promise<StationFacility> {
  return requestClientJson<StationFacility>("/api/v1/station/facility", { method: "PUT", json: facility, csrf });
}

export type StationCodingMode = "icd11_doris" | "icd10";

export interface StationSettings {
  modules: { code: string; label: string; enabled: boolean }[];
  modules_locked: boolean;
  /** null when the signed config says this station does not code the project (coded on the server). */
  coding_mode: StationCodingMode | null;
  coding_mode_locked: boolean;
  available_coding_modes: StationCodingMode[];
}

export async function fetchStationSettings(csrf?: ClientCsrf): Promise<StationSettings> {
  return requestClientJson<StationSettings>("/api/v1/station/settings", { csrf });
}

export async function saveStationSettings(
  change: { enabled_modules?: string[]; coding_mode?: StationCodingMode },
  csrf: ClientCsrf,
): Promise<StationSettings> {
  return requestClientJson<StationSettings>("/api/v1/station/settings", { method: "PUT", json: change, csrf });
}
