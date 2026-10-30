import { CryptoDigestAlgorithm, digestStringAsync } from "expo-crypto";

import type { OfflineProfile } from "../offlineProfile";
import { STANDALONE_SMARTVA_DEFAULTS } from "../standalone/config";
import type { SmartVaOptions } from "./contracts";

export interface SmartVaOptionsSnapshot {
  schemaVersion: 1;
  formId: string;
  formUpdatedAt: string;
  options: SmartVaOptions;
  optionsDigest: string;
  /**
   * "interview": HIV and malaria came from the interview's own Id10002/Id10003 answers because nothing was frozen at
   * first save (standaloneSmartVaSnapshotFromAnswers). Absent: frozen from the profile or the project target. Outside
   * `options`, so the digest and the engine input are unchanged.
   */
  source?: "interview";
}

export interface SmartVaTarget {
  schema_version: 1;
  site_id: string;
  org_unit_id: string | null;
  form_id: string;
  form_updated_at: string;
  options: SmartVaOptions;
  options_digest: string;
}

const DIGEST = /^sha256:[a-f0-9]{64}$/i;

export function isSmartVaOptions(value: unknown): value is SmartVaOptions {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const options = value as Partial<SmartVaOptions>;
  return typeof options.country === "string" && options.country.trim() !== "" &&
    typeof options.hiv === "boolean" && typeof options.malaria === "boolean" &&
    typeof options.hce === "boolean" && typeof options.freetext === "boolean";
}

export function isSmartVaOptionsSnapshot(value: unknown): value is SmartVaOptionsSnapshot {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const snapshot = value as Partial<SmartVaOptionsSnapshot>;
  return snapshot.schemaVersion === 1 && typeof snapshot.formId === "string" && snapshot.formId.trim() !== "" &&
    typeof snapshot.formUpdatedAt === "string" && snapshot.formUpdatedAt.trim() !== "" &&
    isSmartVaOptions(snapshot.options) && typeof snapshot.optionsDigest === "string" && DIGEST.test(snapshot.optionsDigest);
}

export async function digestSmartVaOptions(options: SmartVaOptions): Promise<string> {
  return `sha256:${await digestStringAsync(CryptoDigestAlgorithm.SHA256, JSON.stringify(options))}`;
}

export function projectSmartVaSnapshot(
  targets: readonly SmartVaTarget[] | undefined,
  target: { siteId: string; orgUnitId?: string | null },
): SmartVaOptionsSnapshot | null {
  const exact = targets?.find((entry) => entry.schema_version === 1 &&
    entry.site_id === target.siteId && entry.org_unit_id === (target.orgUnitId ?? null));
  if (!exact || !exact.form_id || !exact.form_updated_at || !isSmartVaOptions(exact.options) || !DIGEST.test(exact.options_digest)) return null;
  return {
    schemaVersion: 1,
    formId: exact.form_id,
    formUpdatedAt: exact.form_updated_at,
    options: { ...exact.options },
    optionsDigest: exact.options_digest,
  };
}

/** A standalone interview freezes only profile choices supplied before its first save. */
export async function standaloneSmartVaSnapshot(
  profile: OfflineProfile | null,
  formId: string,
  formUpdatedAt: string,
): Promise<SmartVaOptionsSnapshot | null> {
  if (!profile?.country.trim() || !profile.hiv_mortality || !profile.malaria_mortality) return null;
  const options: SmartVaOptions = {
    country: profile.country.trim(),
    hiv: profile.hiv_mortality === "high",
    malaria: profile.malaria_mortality === "high",
    ...STANDALONE_SMARTVA_DEFAULTS,
  };
  return {
    schemaVersion: 1,
    formId,
    formUpdatedAt,
    options,
    optionsDigest: await digestSmartVaOptions(options),
  };
}

/** Id10002/Id10003 (HIGH_LOW_VERY) as a SmartVA flag: "high" is high, "low" and "veryl" are not; anything else is unknown. */
function highFromAnswer(value: unknown): boolean | null {
  if (value === "high") return true;
  return value === "low" || value === "veryl" ? false : null;
}

/**
 * A standalone interview with no frozen settings (digitva-0vz7): HIV and malaria from its own Id10002/Id10003
 * answers, country from the profile. Null when either answer or the country is missing, so SmartVA still asks.
 */
export async function standaloneSmartVaSnapshotFromAnswers(
  profile: OfflineProfile | null,
  answers: Record<string, unknown> | undefined,
  formId: string,
  formUpdatedAt: string,
): Promise<SmartVaOptionsSnapshot | null> {
  const country = profile?.country.trim();
  const hiv = highFromAnswer(answers?.Id10002);
  const malaria = highFromAnswer(answers?.Id10003);
  if (!country || hiv === null || malaria === null) return null;
  const options: SmartVaOptions = { country, hiv, malaria, ...STANDALONE_SMARTVA_DEFAULTS };
  return {
    schemaVersion: 1,
    formId,
    formUpdatedAt,
    options,
    optionsDigest: await digestSmartVaOptions(options),
    source: "interview",
  };
}
