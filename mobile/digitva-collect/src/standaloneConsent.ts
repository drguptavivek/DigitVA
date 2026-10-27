/**
 * The consent notice bundled for a phone used without a server (Collect Plus Path C; owner decision
 * 2026-10-27, digitva-5bzf; docs/policy/respondent-consent-notice-draft.md "Standalone notice").
 *
 * The asset is generated from app/services/consent_notice_seed.py (scripts/export_standalone_consent_notice.py);
 * never edit it. Its gaps ([PROJECT NAME], [ORGANISATION], contacts...) are filled here at display time, so the
 * hash of what the respondent saw is taken on the phone and the record keeps the exact rendered text for the push
 * (offline contract section 17). Enrolled accounts never use this: they use the server's notice (contract 5.6).
 */
import bundled from "../assets/standalone-consent-notice.json";
import {
  computeUtf8Sha256HexSync,
  createDefaultPurposeMap,
  INFORMANT_PII_FIELDS,
  type ConsentDecision,
  type ConsentMode,
  type ConsentNoticeVersion,
  type ConsentPurposeSpec,
  type ConsentRecordEnvelope,
} from "./consent";

interface StandaloneAsset {
  schema: number;
  version: string;
  sha256: string;
  text: Record<string, string>;
  purposes: Record<string, ConsentPurposeSpec[]>;
  allowed_modes: ConsentMode[];
}

const ASSET = bundled as StandaloneAsset;

/** What an unfilled gap reads as (owner default); Hindi for the Hindi notice. */
const STUDY_TEAM: Record<string, string> = { en: "the study team", hi: "अध्ययन दल" };

export interface StandaloneNoticeContext {
  /** The study's name; blank reads as "the study team". */
  projectName?: string | null;
  /** The organisation, from the offline profile's facility; blank reads as "the study team". */
  organisation?: string | null;
}

export type StandaloneConsentNotice = ConsentNoticeVersion & {
  /** The asset's version string and content hash, kept in the record for the server's allowlist check. */
  bundle_version: string;
  bundle_sha256: string;
};

/** Fill the named gaps, then turn every other `[...]` into "the study team"; a bracket is never shown. */
export function fillPlaceholders(text: string, language: string, context: StandaloneNoticeContext = {}): string {
  const fallback = STUDY_TEAM[language] ?? STUDY_TEAM.en;
  const project = context.projectName?.trim() || fallback;
  const organisation = context.organisation?.trim() || fallback;
  return text
    .split("[PROJECT NAME]").join(project)
    .split("[ORGANISATION]").join(organisation)
    .replace(/\[[^\]]*\]/g, fallback);
}

/**
 * The bundled notice in `language`, placeholders filled, or null when the app has none in that language
 * (policy: no fallback to another language). The S4 guard calls this; null means no standalone interview.
 */
export function getStandaloneConsentNotice(
  language: string,
  context: StandaloneNoticeContext = {},
): StandaloneConsentNotice | null {
  const code = String(language ?? "").trim().toLowerCase();
  const raw = ASSET.text[code];
  const purposes = ASSET.purposes[code];
  if (!raw || !purposes?.length) return null;
  const text = fillPlaceholders(raw, code, context);
  const sha = computeUtf8Sha256HexSync(text);
  return {
    notice_version_id: `standalone-${sha}`,
    version: 1,
    language: code,
    text,
    text_sha256: sha,
    purposes: purposes.map((p) => ({ ...p, label: fillPlaceholders(p.label, code, context) })),
    covered_fields: [...INFORMANT_PII_FIELDS, "Id10007"],
    allowed_modes: [...ASSET.allowed_modes],
    witness_allowed: true,
    bundle_version: ASSET.version,
    bundle_sha256: ASSET.sha256,
  };
}

/** Starting toggles: required purposes on, every optional one (item 7 included) off. */
export const standaloneDefaultPurposes = (notice: StandaloneConsentNotice) => createDefaultPurposeMap(notice);

/**
 * A standalone decision as kept on the phone. `envelope` is the contract 5.3 consent object; the extra fields
 * are what the push (section 17) adds: the exact text the respondent saw and which bundled notice it came from.
 */
export interface StandaloneConsentRecord {
  envelope: ConsentRecordEnvelope;
  /** The rendered notice text, placeholders filled; `envelope.notice_sha256` is its UTF-8 SHA-256. */
  notice_text: string;
  bundle_version: string;
  bundle_sha256: string;
}

export function buildStandaloneConsentRecord(input: {
  notice: StandaloneConsentNotice;
  clientId: string;
  clientDraftId: string | null;
  decision: ConsentDecision;
  /** Code to granted for every purpose of the notice; missing codes take the defaults. */
  choices?: Record<string, boolean>;
  mode: ConsentMode;
  witnessPresent: boolean;
  recordedAt?: string;
}): StandaloneConsentRecord {
  const { notice } = input;
  const answers = { ...standaloneDefaultPurposes(notice), ...input.choices };
  return {
    envelope: {
      client_id: input.clientId,
      client_draft_id: input.clientDraftId,
      notice_version_id: notice.notice_version_id,
      notice_language: notice.language,
      notice_sha256: notice.text_sha256,
      decision: input.decision,
      purposes: notice.purposes
        .map((p) => ({ code: p.code, granted: Boolean(answers[p.code]) }))
        .sort((a, b) => a.code.localeCompare(b.code)),
      mode: input.mode,
      witness_present: input.witnessPresent,
      supersedes_client_id: null,
      recorded_at: input.recordedAt ?? new Date().toISOString(),
    },
    notice_text: notice.text,
    bundle_version: notice.bundle_version,
    bundle_sha256: notice.bundle_sha256,
  };
}
