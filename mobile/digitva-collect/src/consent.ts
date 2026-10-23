import { requestClientJson, type ClientCsrf } from "./api";
import type { Db } from "./drafts";

export type ConsentMode = "spoken" | "tap" | "signed";
export type LegacyConsentMode = ConsentMode | "tapped";
export type ConsentDecision = "granted" | "refused";
export type ConsentActionType = ConsentDecision;
export type ConsentStatus = "granted" | "refused" | "withdrawn" | "pending" | "not_required";

export interface ConsentPurposeSpec {
  code: string;
  label: string;
  required: boolean;
}

export interface ConsentPurposeChoice {
  code: string;
  granted: boolean;
}

export interface ConsentNoticeVersion {
  notice_version_id: string;
  version: number;
  language: string;
  text: string;
  text_sha256: string;
  purposes: ConsentPurposeSpec[];
  covered_fields: string[];
  allowed_modes: ConsentMode[];
  witness_allowed: boolean;
}

export interface DistrictContactInfo {
  name: string;
  email: string;
  phone: string;
}

export interface ConsentContacts {
  deletion: { email: string; phone: string };
  mentor_institution: { name?: string; email?: string; phone?: string };
  central_team: { email: string; phone: string };
  dpo: { name?: string; email?: string; phone?: string } | null;
  districts: Record<string, DistrictContactInfo>;
}

export interface ConsentRetentionPolicy {
  period_days: number | null;
  expiry_action: "erase" | "lock";
}

export type ConsentRefusalBehaviour = "interview_without_informant_data" | (string & {});

export interface ProjectConsentConfig {
  project_id: string;
  consent_required: boolean;
  notice_versions: ConsentNoticeVersion[];
  contacts: ConsentContacts;
  retention: ConsentRetentionPolicy;
  refusal_behaviour: ConsentRefusalBehaviour;
}

/**
 * Contract Section 5.3 canonical consent record / envelope shape.
 * Never carries `witness_name`.
 */
export interface ConsentRecordEnvelope {
  client_id: string;
  client_draft_id: string | null; // null at registration
  notice_version_id: string;
  notice_language: string;
  notice_sha256: string;
  decision: "granted" | "refused";
  purposes: ConsentPurposeChoice[]; // sorted by code
  mode: "spoken" | "tap" | "signed";
  witness_present: boolean; // NEVER witness_name
  supersedes_client_id: string | null;
  recorded_at: string;
}

export type ConsentEnvelope = ConsentRecordEnvelope;

export const INFORMANT_PII_FIELDS = [
  "informant_name",
  "informant_phone",
  "informant_phone_2",
  "address",
  "address_house_street",
  "address_village_ward",
  "address_landmark",
] as const;

export const SANDBOX_PROJECT_ID = "1";

export function isSandboxProject(projectId: string | number | null | undefined): boolean {
  return String(projectId ?? "").trim() === SANDBOX_PROJECT_ID;
}

export function normaliseConsentMode(mode: string | null | undefined): ConsentMode {
  const cleaned = String(mode ?? "").trim().toLowerCase();
  if (cleaned === "tap" || cleaned === "tapped") return "tap";
  if (cleaned === "signed") return "signed";
  return "spoken";
}

export function normaliseConsentDecision(decision: string | null | undefined): ConsentDecision {
  const cleaned = String(decision ?? "").trim().toLowerCase();
  if (cleaned === "refused" || cleaned === "refusal") return "refused";
  return "granted";
}

// ============================================================================
// Pure UTF-8 SHA-256 (Contract Sections 5.2, 5.3, 11)
// Hashes the exact UTF-8 bytes of `text`, never rendered Markdown.
// ============================================================================

const SHA256_K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

function utf8Bytes(text: string): Uint8Array {
  if (typeof TextEncoder !== "undefined") {
    return new TextEncoder().encode(text);
  }
  const encoded = unescape(encodeURIComponent(text));
  const out = new Uint8Array(encoded.length);
  for (let i = 0; i < encoded.length; i += 1) {
    out[i] = encoded.charCodeAt(i);
  }
  return out;
}

function rotr(x: number, n: number): number {
  return (x >>> n) | (x << (32 - n));
}

export function computeUtf8Sha256HexSync(text: string): string {
  const bytes = utf8Bytes(text);
  const bitLenHi = Math.floor((bytes.length * 8) / 0x100000000);
  const bitLenLo = (bytes.length * 8) >>> 0;

  const paddedLen = ((bytes.length + 9 + 63) >> 6) << 6;
  const padded = new Uint8Array(paddedLen);
  padded.set(bytes);
  padded[bytes.length] = 0x80;
  const view = new DataView(padded.buffer);
  view.setUint32(paddedLen - 8, bitLenHi, false);
  view.setUint32(paddedLen - 4, bitLenLo, false);

  let h0 = 0x6a09e667;
  let h1 = 0xbb67ae85;
  let h2 = 0x3c6ef372;
  let h3 = 0xa54ff53a;
  let h4 = 0x510e527f;
  let h5 = 0x9b05688c;
  let h6 = 0x1f83d9ab;
  let h7 = 0x5be0cd19;

  const w = new Uint32Array(64);

  for (let offset = 0; offset < paddedLen; offset += 64) {
    for (let i = 0; i < 16; i += 1) {
      w[i] = view.getUint32(offset + i * 4, false);
    }
    for (let i = 16; i < 64; i += 1) {
      const s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3);
      const s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
    }

    let a = h0;
    let b = h1;
    let c = h2;
    let d = h3;
    let e = h4;
    let f = h5;
    let g = h6;
    let h = h7;

    for (let i = 0; i < 64; i += 1) {
      const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const ch = (e & f) ^ (~e & g);
      const temp1 = (h + S1 + ch + SHA256_K[i] + w[i]) >>> 0;
      const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = (S0 + maj) >>> 0;

      h = g;
      g = f;
      f = e;
      e = (d + temp1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (temp1 + temp2) >>> 0;
    }

    h0 = (h0 + a) >>> 0;
    h1 = (h1 + b) >>> 0;
    h2 = (h2 + c) >>> 0;
    h3 = (h3 + d) >>> 0;
    h4 = (h4 + e) >>> 0;
    h5 = (h5 + f) >>> 0;
    h6 = (h6 + g) >>> 0;
    h7 = (h7 + h) >>> 0;
  }

  return [h0, h1, h2, h3, h4, h5, h6, h7]
    .map((word) => word.toString(16).padStart(8, "0"))
    .join("");
}

export async function computeUtf8Sha256Hex(text: string): Promise<string> {
  return computeUtf8Sha256HexSync(text);
}

export function verifyNoticeTextSha256(
  notice: Pick<ConsentNoticeVersion, "text" | "text_sha256">,
): boolean {
  if (typeof notice.text !== "string" || typeof notice.text_sha256 !== "string") {
    return false;
  }
  const expected = notice.text_sha256.trim().toLowerCase();
  if (!/^[0-9a-f]{64}$/.test(expected)) return false;
  return computeUtf8Sha256HexSync(notice.text) === expected;
}

/**
 * Compare notice `version` as an integer (Contract 5.2 & 5.6: never compare as text).
 */
export function compareNoticeVersions(
  a: Pick<ConsentNoticeVersion, "version">,
  b: Pick<ConsentNoticeVersion, "version">,
): number {
  const va = Math.trunc(Number(a.version));
  const vb = Math.trunc(Number(b.version));
  return va - vb;
}

export function selectActiveNoticeVersion(
  config: ProjectConsentConfig | null | undefined,
  preferredLanguage?: string,
): ConsentNoticeVersion | null {
  if (!config || !Array.isArray(config.notice_versions) || config.notice_versions.length === 0) {
    return null;
  }
  const validVersions = config.notice_versions.filter(
    (v) => Number.isInteger(Number(v.version)) && verifyNoticeTextSha256(v),
  );
  if (validVersions.length === 0) return null;

  const lang = preferredLanguage?.trim().toLowerCase();
  const candidates = lang
    ? validVersions.filter((v) => v.language.toLowerCase() === lang)
    : [];
  const pool = candidates.length > 0 ? candidates : validVersions;
  return [...pool].sort((a, b) => compareNoticeVersions(b, a))[0] ?? null;
}

const SANDBOX_EN_TEXT =
  "We are sorry for your loss. Before we write down your name, phone number or address, please read or listen to how this information is used under the Digital Personal Data Protection Act, 2023.\n\n" +
  "**Why we ask for your details:**\n" +
  "1. To record the death and conduct the Verbal Autopsy interview.\n" +
  "2. To contact you if a health worker needs to schedule or follow up on the visit.\n" +
  "3. For trained physicians to assign a cause of death (without seeing your name or phone).\n" +
  "4. For anonymised public-health and government mortality statistics.\n\n" +
  "**Your rights:** You may refuse to share your contact details (the death record and interview can still proceed without them), and you may withdraw your consent or ask for your contact details to be erased at any time.";

const SANDBOX_HI_TEXT =
  "आपके दुःख में हम सहभागी हैं। आपका नाम, फ़ोन नंबर या पता लिखने से पहले कृपया जान लें कि डिजिटल व्यक्तिगत डेटा संरक्षण अधिनियम (DPDP Act, 2023) के अंतर्गत इस जानकारी का उपयोग कैसे किया जाएगा।\n\n" +
  "आप अपनी संपर्क जानकारी देने से मना कर सकते हैं और किसी भी समय अपनी सहमति वापस ले सकते हैं।";

const SANDBOX_PURPOSES: ConsentPurposeSpec[] = [
  {
    code: "cause_of_death_coding",
    label: "Assign cause of death (physicians see clinical answers only, not my contact details)",
    required: true,
  },
  {
    code: "contact_followup",
    label: "Contact me by phone or visit for interview scheduling and follow-up",
    required: true,
  },
  {
    code: "record_and_interview",
    label: "Record the death and conduct the verbal autopsy interview",
    required: true,
  },
  {
    code: "research_sharing",
    label: "Optional: Share de-identified clinical data in approved health research repositories",
    required: false,
  },
  {
    code: "sms_whatsapp_messages",
    label: "Optional: Send appointment or follow-up messages by SMS / WhatsApp",
    required: false,
  },
  {
    code: "statistical_reports",
    label: "Include de-identified data in public-health and government mortality reports",
    required: true,
  },
];

/**
 * Built-in consent config ONLY for the unprovisioned standalone sandbox (`projectId === "1"`).
 * Contract Section 5.6: Provisioned projects MUST NOT fall back to hardcoded defaults.
 */
export function sandboxProjectConsentConfig(): ProjectConsentConfig {
  return {
    project_id: SANDBOX_PROJECT_ID,
    consent_required: true,
    notice_versions: [
      {
        notice_version_id: "00000000-0000-4000-8000-000000000001",
        version: 1,
        language: "en",
        text: SANDBOX_EN_TEXT,
        text_sha256: computeUtf8Sha256HexSync(SANDBOX_EN_TEXT),
        purposes: SANDBOX_PURPOSES.map((p) => ({ ...p })),
        covered_fields: [...INFORMANT_PII_FIELDS, "Id10007"],
        allowed_modes: ["spoken", "tap", "signed"],
        witness_allowed: true,
      },
      {
        notice_version_id: "00000000-0000-4000-8000-000000000002",
        version: 1,
        language: "hi",
        text: SANDBOX_HI_TEXT,
        text_sha256: computeUtf8Sha256HexSync(SANDBOX_HI_TEXT),
        purposes: SANDBOX_PURPOSES.map((p) => ({ ...p })),
        covered_fields: [...INFORMANT_PII_FIELDS, "Id10007"],
        allowed_modes: ["spoken", "tap", "signed"],
        witness_allowed: true,
      },
    ],
    contacts: {
      deletion: {
        email: "privacy-support@digitva.org",
        phone: "01126588500",
      },
      mentor_institution: {
        name: "Regional Medical Institute / State Nodal Unit",
        email: "mentor@digitva.org",
        phone: "01126588501",
      },
      central_team: {
        email: "central-team@digitva.org",
        phone: "01126588502",
      },
      dpo: {
        name: "Data Protection Officer",
        email: "dpo@digitva.org",
        phone: "01126588503",
      },
      districts: {},
    },
    retention: {
      period_days: 1825,
      expiry_action: "erase",
    },
    refusal_behaviour: "interview_without_informant_data",
  };
}

/**
 * Returns the sandbox consent config ONLY when `projectId === "1"`.
 * Returns `null` for any provisioned project (`projectId !== "1"`) per Contract Section 5.6.
 */
export function defaultProjectConsentConfig(
  projectId: string | number = SANDBOX_PROJECT_ID,
): ProjectConsentConfig | null {
  if (!isSandboxProject(projectId)) {
    return null;
  }
  return sandboxProjectConsentConfig();
}

function resolveNoticePurposes(
  source: ProjectConsentConfig | ConsentNoticeVersion | null | undefined,
): ConsentPurposeSpec[] {
  if (!source) return [];
  if ("purposes" in source && Array.isArray(source.purposes)) {
    return source.purposes;
  }
  if ("notice_versions" in source) {
    const active = selectActiveNoticeVersion(source);
    return active ? active.purposes : [];
  }
  return [];
}

export function createDefaultPurposeMap(
  source: ProjectConsentConfig | ConsentNoticeVersion | null | undefined,
): Record<string, boolean> {
  const out: Record<string, boolean> = {};
  for (const purpose of resolveNoticePurposes(source)) {
    out[purpose.code] = purpose.required;
  }
  return out;
}

export function buildSortedPurposeChoices(
  source: ProjectConsentConfig | ConsentNoticeVersion | null | undefined,
  choices?: Record<string, boolean> | ConsentPurposeChoice[],
): ConsentPurposeChoice[] {
  const specs = resolveNoticePurposes(source);
  const byCode = new Map<string, boolean>();
  if (Array.isArray(choices)) {
    for (const item of choices) {
      if (item && typeof item.code === "string") {
        byCode.set(item.code, Boolean(item.granted));
      }
    }
  } else if (choices && typeof choices === "object") {
    for (const [code, granted] of Object.entries(choices)) {
      byCode.set(code, Boolean(granted));
    }
  }
  return [...specs]
    .sort((a, b) => a.code.localeCompare(b.code))
    .map((spec) => ({
      code: spec.code,
      granted: byCode.has(spec.code) ? Boolean(byCode.get(spec.code)) : spec.required,
    }));
}

export function allRequiredPurposesGranted(
  source: ProjectConsentConfig | ConsentNoticeVersion | null | undefined,
  purposes: Record<string, boolean> | ConsentPurposeChoice[],
): boolean {
  const specs = resolveNoticePurposes(source);
  const grantedMap = new Map<string, boolean>();
  if (Array.isArray(purposes)) {
    for (const p of purposes) {
      grantedMap.set(p.code, Boolean(p.granted));
    }
  } else if (purposes && typeof purposes === "object") {
    for (const [code, val] of Object.entries(purposes)) {
      grantedMap.set(code, Boolean(val));
    }
  }
  return specs.filter((p) => p.required).every((p) => grantedMap.get(p.code) === true);
}

export function hasNonEmptyInformantPii(
  input: Record<string, unknown>,
  coveredFields: readonly string[] = INFORMANT_PII_FIELDS,
): boolean {
  const fieldsToCheck = new Set<string>([...INFORMANT_PII_FIELDS, ...coveredFields]);
  for (const field of fieldsToCheck) {
    const val = input[field];
    if (typeof val === "string" && val.trim().length > 0) {
      return true;
    }
  }
  return false;
}

/**
 * Hard client-side DPDP consent check (Contract Sections 5.1–5.6):
 * - For any provisioned project (`projectId !== "1"`), if no consent config is loaded
 *   from the signed station config or `GET /api/v1/intake/consent-config`, blocks saving
 *   informant personal data until the station config is imported.
 * - Verifies integer notice version, exact UTF-8 `text_sha256`, allowed mode, witness flag,
 *   and sorted required purposes.
 */
export function validateConsentBeforeRegistrationSave(
  config: ProjectConsentConfig | null | undefined,
  consent: ConsentRecordEnvelope | null | undefined,
  registrationInput: Record<string, unknown>,
  projectId?: string,
): { valid: true } | { valid: false; error: string } {
  const effectiveProjectId = String(
    projectId ?? registrationInput.project_id ?? config?.project_id ?? "",
  ).trim();
  const hasPii = hasNonEmptyInformantPii(registrationInput);

  if (!config) {
    if (!isSandboxProject(effectiveProjectId)) {
      if (hasPii) {
        return {
          valid: false,
          error:
            "Station consent configuration is not loaded for this project. Import a signed station config before saving informant personal data.",
        };
      }
      return { valid: true };
    }
    config = sandboxProjectConsentConfig();
  }

  if (
    config.refusal_behaviour &&
    config.refusal_behaviour !== "interview_without_informant_data"
  ) {
    return {
      valid: false,
      error: "Consent settings need an app update.",
    };
  }

  if (!config.consent_required) {
    return { valid: true };
  }

  const notice =
    (consent
      ? config.notice_versions.find((v) => v.notice_version_id === consent.notice_version_id)
      : null) ?? selectActiveNoticeVersion(config);
  const coveredHasPii = hasNonEmptyInformantPii(registrationInput, notice?.covered_fields);

  if (!consent) {
    if (coveredHasPii) {
      return {
        valid: false,
        error:
          "Respondent consent must be recorded before saving informant name, phone, or address.",
      };
    }
    return { valid: true };
  }

  if (!notice) {
    return {
      valid: false,
      error: "Selected consent notice version is missing or retired.",
    };
  }

  if (!verifyNoticeTextSha256(notice) || consent.notice_sha256 !== notice.text_sha256) {
    return {
      valid: false,
      error: "Consent notice text hash (notice_sha256) failed verification.",
    };
  }

  if (consent.notice_language !== notice.language) {
    return {
      valid: false,
      error: "Consent notice language does not match the selected notice version.",
    };
  }

  const mode = normaliseConsentMode(consent.mode);
  if (!notice.allowed_modes.includes(mode)) {
    return {
      valid: false,
      error: `Consent mode '${mode}' is not allowed for this notice version.`,
    };
  }

  if (!notice.witness_allowed && consent.witness_present) {
    return {
      valid: false,
      error: "Witness is not allowed for this consent notice version.",
    };
  }

  if (consent.decision === "refused") {
    if (coveredHasPii) {
      return {
        valid: false,
        error:
          "Respondent refused consent; informant name, phone, and address must be left blank.",
      };
    }
    return { valid: true };
  }

  if (consent.decision === "granted") {
    if (!allRequiredPurposesGranted(notice, consent.purposes)) {
      return {
        valid: false,
        error:
          "All required respondent consent purposes must be granted, or record the decision as 'refused' and leave informant details blank.",
      };
    }
    return { valid: true };
  }

  return { valid: false, error: "Invalid respondent consent decision." };
}

/**
 * Clear informant personal data fields when respondent refuses consent so the death
 * registration and interview can continue with deceased/event details only.
 */
export function stripInformantPiiOnRefusal<T extends Record<string, unknown>>(
  input: T,
  coveredFields: readonly string[] = INFORMANT_PII_FIELDS,
): T {
  const clone: Record<string, unknown> = { ...input };
  const fieldsToClear = new Set<string>([...INFORMANT_PII_FIELDS, ...coveredFields]);
  for (const field of fieldsToClear) {
    if (field in clone) {
      clone[field] = "";
    }
  }
  return clone as T;
}

export function normaliseProjectConsentConfig(raw: unknown): ProjectConsentConfig | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const obj = raw as Record<string, unknown>;
  if (typeof obj.consent_required !== "boolean") return null;
  const rawVersions = Array.isArray(obj.notice_versions) ? obj.notice_versions : [];
  const noticeVersions: ConsentNoticeVersion[] = [];

  for (const item of rawVersions) {
    if (!item || typeof item !== "object") continue;
    const v = item as Record<string, unknown>;
    const versionNum = Number(v.version);
    if (
      typeof v.notice_version_id !== "string" ||
      !Number.isInteger(versionNum) ||
      typeof v.language !== "string" ||
      typeof v.text !== "string" ||
      typeof v.text_sha256 !== "string"
    ) {
      return null;
    }
    const purposesRaw = Array.isArray(v.purposes) ? v.purposes : [];
    const purposes: ConsentPurposeSpec[] = purposesRaw
      .filter((p): p is Record<string, unknown> => !!p && typeof p === "object")
      .map((p) => ({
        code: String(p.code ?? ""),
        label: String(p.label ?? p.default_label ?? p.code ?? ""),
        required: Boolean(p.required),
      }))
      .filter((p) => p.code.length > 0);
    const allowedModesRaw = Array.isArray(v.allowed_modes) ? v.allowed_modes : ["spoken", "tap", "signed"];
    const allowedModes = allowedModesRaw.map((m) => normaliseConsentMode(String(m)));
    const notice: ConsentNoticeVersion = {
      notice_version_id: v.notice_version_id,
      version: versionNum,
      language: v.language,
      text: v.text,
      text_sha256: v.text_sha256.toLowerCase(),
      purposes,
      covered_fields: Array.isArray(v.covered_fields)
        ? v.covered_fields.map((f) => String(f))
        : [...INFORMANT_PII_FIELDS],
      allowed_modes: allowedModes.length > 0 ? allowedModes : ["spoken", "tap", "signed"],
      witness_allowed: Boolean(v.witness_allowed),
    };
    if (!verifyNoticeTextSha256(notice)) {
      return null;
    }
    noticeVersions.push(notice);
  }

  noticeVersions.sort((a, b) => compareNoticeVersions(b, a));

  const contactsRaw =
    obj.contacts && typeof obj.contacts === "object"
      ? (obj.contacts as Record<string, unknown>)
      : {};
  const deletionRaw =
    contactsRaw.deletion && typeof contactsRaw.deletion === "object"
      ? (contactsRaw.deletion as Record<string, unknown>)
      : {};
  const centralRaw =
    contactsRaw.central_team && typeof contactsRaw.central_team === "object"
      ? (contactsRaw.central_team as Record<string, unknown>)
      : {};
  const mentorRaw =
    contactsRaw.mentor_institution && typeof contactsRaw.mentor_institution === "object"
      ? (contactsRaw.mentor_institution as Record<string, unknown>)
      : {};
  const dpoRaw =
    contactsRaw.dpo && typeof contactsRaw.dpo === "object"
      ? (contactsRaw.dpo as Record<string, unknown>)
      : null;
  const districtsRaw =
    contactsRaw.districts && typeof contactsRaw.districts === "object"
      ? (contactsRaw.districts as Record<string, unknown>)
      : {};
  const districts: Record<string, DistrictContactInfo> = {};
  for (const [unitId, dVal] of Object.entries(districtsRaw)) {
    if (dVal && typeof dVal === "object") {
      const d = dVal as Record<string, unknown>;
      districts[unitId] = {
        name: String(d.name ?? ""),
        email: String(d.email ?? ""),
        phone: String(d.phone ?? ""),
      };
    }
  }

  const retentionRaw =
    obj.retention && typeof obj.retention === "object"
      ? (obj.retention as Record<string, unknown>)
      : {};

  return {
    project_id: String(obj.project_id ?? ""),
    consent_required: obj.consent_required,
    notice_versions: noticeVersions,
    contacts: {
      deletion: {
        email: String(deletionRaw.email ?? ""),
        phone: String(deletionRaw.phone ?? ""),
      },
      mentor_institution: {
        name: typeof mentorRaw.name === "string" ? mentorRaw.name : undefined,
        email: typeof mentorRaw.email === "string" ? mentorRaw.email : undefined,
        phone: typeof mentorRaw.phone === "string" ? mentorRaw.phone : undefined,
      },
      central_team: {
        email: String(centralRaw.email ?? ""),
        phone: String(centralRaw.phone ?? ""),
      },
      dpo: dpoRaw
        ? {
            name: typeof dpoRaw.name === "string" ? dpoRaw.name : undefined,
            email: typeof dpoRaw.email === "string" ? dpoRaw.email : undefined,
            phone: typeof dpoRaw.phone === "string" ? dpoRaw.phone : undefined,
          }
        : null,
      districts,
    },
    retention: {
      period_days:
        typeof retentionRaw.period_days === "number" ? retentionRaw.period_days : null,
      expiry_action: retentionRaw.expiry_action === "lock" ? "lock" : "erase",
    },
    refusal_behaviour:
      typeof obj.refusal_behaviour === "string"
        ? obj.refusal_behaviour
        : "interview_without_informant_data",
  };
}

/**
 * Fetch project consent config from `/api/v1/intake/consent-config`.
 * Contract Section 5.6: Never falls back to hardcoded defaults for a provisioned project (`projectId !== "1"`).
 */
export async function fetchProjectConsentConfig(
  projectId: string,
  csrf: ClientCsrf,
): Promise<ProjectConsentConfig | null> {
  try {
    const res = await requestClientJson<unknown>(
      `/api/v1/intake/consent-config?project_id=${encodeURIComponent(projectId)}`,
      { csrf },
    );
    const parsed = normaliseProjectConsentConfig(res);
    if (parsed) {
      return parsed;
    }
  } catch {
    // Only unprovisioned standalone sandbox (projectId === "1") may use built-in defaults
  }
  return defaultProjectConsentConfig(projectId);
}

/** `GET/POST /api/v1/intake/drafts/<id>/consent`: the decision on file for a browser interview's case. */
export interface DraftConsentStatus {
  consent_required: boolean;
  decision: "granted" | "refused" | "withdrawn" | null;
  covered_fields: string[];
  client_draft_id: string | null;
}

export function getDraftConsent(draftsLink: string, draftId: string, csrf: ClientCsrf): Promise<DraftConsentStatus> {
  return requestClientJson(`${draftsLink}/${encodeURIComponent(draftId)}/consent`, { csrf });
}

export function postDraftConsent(
  draftsLink: string,
  draftId: string,
  consent: ConsentRecordEnvelope,
  csrf: ClientCsrf,
): Promise<DraftConsentStatus> {
  return requestClientJson(`${draftsLink}/${encodeURIComponent(draftId)}/consent`, {
    method: "POST", json: { consent }, csrf,
  });
}

export async function initConsentTables(db: Db): Promise<void> {
  await db.execAsync(`
    CREATE TABLE IF NOT EXISTS consent_configs (
      project_id TEXT PRIMARY KEY,
      consent_required INTEGER NOT NULL DEFAULT 1,
      config_json TEXT NOT NULL,
      synced_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS consent_records (
      client_id TEXT PRIMARY KEY,
      project_id TEXT NOT NULL,
      client_death_id TEXT,
      death_id TEXT,
      client_draft_id TEXT,
      notice_version_id TEXT NOT NULL,
      notice_language TEXT NOT NULL,
      notice_sha256 TEXT NOT NULL,
      decision TEXT NOT NULL,
      purposes_json TEXT NOT NULL,
      mode TEXT NOT NULL,
      witness_present INTEGER NOT NULL DEFAULT 0,
      supersedes_client_id TEXT,
      recorded_by TEXT NOT NULL,
      recorded_at TEXT NOT NULL,
      sync_state TEXT NOT NULL DEFAULT 'pending'
    );
  `);
}
