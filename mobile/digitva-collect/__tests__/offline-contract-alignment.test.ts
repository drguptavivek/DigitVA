import { getLocalStationLaunchToken } from "../src/api";
import {
  buildSortedPurposeChoices,
  computeUtf8Sha256HexSync,
  normaliseConsentDecision,
  normaliseConsentMode,
  sandboxProjectConsentConfig,
  selectActiveNoticeVersion,
  validateConsentBeforeRegistrationSave,
  verifyNoticeTextSha256,
  type ConsentRecordEnvelope,
} from "../src/consent";
import {
  normalisePhone,
  PII_FIELDS_FLOOR,
  validateIdentifier,
  type IdentifierTypeSpec,
} from "../src/identifiers";
import {
  daysUntilConfigExpiry,
  normaliseActingRole,
  normaliseStationRosterSnapshot,
  validateUserPin,
} from "../src/roster";

describe("Offline API Contract v1 frontend alignment", () => {
  describe("consent.ts (Contract Section 5)", () => {
    it("normalises consent modes and decisions to canonical contract tokens", () => {
      expect(normaliseConsentMode("tapped")).toBe("tap");
      expect(normaliseConsentMode("tap")).toBe("tap");
      expect(normaliseConsentMode("spoken")).toBe("spoken");
      expect(normaliseConsentMode("signed")).toBe("signed");
      expect(normaliseConsentDecision("grant")).toBe("granted");
      expect(normaliseConsentDecision("refusal")).toBe("refused");
    });

    it("computes exact UTF-8 SHA-256 and verifies notice_sha256", () => {
      const text = "Consent notice text — नमस्ते";
      const sha = computeUtf8Sha256HexSync(text);
      expect(sha).toHaveLength(64);
      expect(verifyNoticeTextSha256({ text, text_sha256: sha })).toBe(true);
      expect(verifyNoticeTextSha256({ text: `${text} `, text_sha256: sha })).toBe(false);
    });

    it("refuses hardcoded fallback for provisioned projects (projectId !== '1')", () => {
      const res = validateConsentBeforeRegistrationSave(
        null,
        null,
        { informant_name: "Asha Devi", informant_phone: "9876543210" },
        "proj-provisioned-42",
      );
      expect(res.valid).toBe(false);
      if (!res.valid) {
        expect(res.error).toContain("consent configuration");
      }
    });

    it("validates sorted ConsentRecordEnvelope with boolean witness_present and no witness_name", () => {
      const cfg = sandboxProjectConsentConfig();
      const notice = selectActiveNoticeVersion(cfg, "en")!;
      const purposes = buildSortedPurposeChoices(notice, {
        statistics_reports: true,
        record_and_interview: true,
        contact_followup: true,
        cause_of_death_coding: true,
        messages: false,
        narrative_automated_processing: false,
        research_sharing: true,
      });
      const env: ConsentRecordEnvelope = {
        client_id: "00000000-0000-4000-8000-000000000999",
        client_draft_id: null,
        notice_version_id: notice.notice_version_id,
        notice_language: notice.language,
        notice_sha256: notice.text_sha256,
        decision: "granted",
        purposes,
        mode: "tap",
        witness_present: true,
        supersedes_client_id: null,
        recorded_at: "2026-10-21T04:00:00Z",
      };
      const codes = env.purposes.map((p) => p.code);
      expect(codes).toEqual([...codes].sort());

      const check = validateConsentBeforeRegistrationSave(
        cfg,
        env,
        { informant_name: "Asha Devi", informant_phone: "9876543210" },
        "1",
      );
      expect(check.valid).toBe(true);
    });
  });

  describe("identifiers.ts (Contract Section 6)", () => {
    it("exports exact 19-field PII_FIELDS_FLOOR from Contract 6.6", () => {
      expect(PII_FIELDS_FLOOR).toHaveLength(19);
      expect(PII_FIELDS_FLOOR).toContain("Id10073");
      expect(PII_FIELDS_FLOOR).toContain("abha_number");
      expect(PII_FIELDS_FLOOR).not.toContain("Id10476");
    });

    it("rejects spaces in letters_digits_hyphen_slash and anchors pattern full-match with example", () => {
      const rule: IdentifierTypeSpec = {
        code: "crs_reg_no",
        label: "CRS Registration Number",
        char_type: "letters_digits_hyphen_slash",
        min_length: 4,
        max_length: 20,
        pattern: "[A-Z]{2}/[0-9]{4}",
        example: "DL/2026",
        required_at_report: false,
        sort_order: 10,
      };

      expect(validateIdentifier("DL/2026", rule)).toEqual({
        valid: true,
        value: "DL/2026",
      });

      // Space is forbidden in letters_digits_hyphen_slash
      const spaceRes = validateIdentifier("DL 2026", rule);
      expect(spaceRes.valid).toBe(false);

      // Substring match must fail because pattern is full-match anchored ^(?:...)$
      const subRes = validateIdentifier("XX-DL/2026-YY", rule);
      expect(subRes.valid).toBe(false);
      if (!subRes.valid) {
        expect(subRes.error).toBe("CRS Registration Number must look like DL/2026.");
        expect(subRes.error).not.toContain("XX-DL/2026-YY");
      }
    });

    it("normalises Indian phone numbers per Contract 6.5", () => {
      expect(normalisePhone("+91 98765-43210")).toBe("9876543210");
      expect(normalisePhone("91-9876543210")).toBe("9876543210");
      expect(normalisePhone("09876543210")).toBe("9876543210");
      expect(normalisePhone("(987) 654-3210")).toBe("9876543210");
    });
  });

  describe("roster.ts (Contract Sections 4 & 10)", () => {
    it("normalises legacy acting roles to canonical contract role codes", () => {
      expect(normaliseActingRole("reporter")).toBe("death_reporter");
      expect(normaliseActingRole("supervisor")).toBe("station_supervisor");
      expect(normaliseActingRole("death_reporter")).toBe("death_reporter");
      expect(normaliseActingRole("station_supervisor")).toBe("station_supervisor");
      expect(normaliseActingRole("interviewer")).toBe("interviewer");
      expect(normaliseActingRole("coder")).toBe("coder");
    });

    it("validates 6-16 digit user PINs", () => {
      expect(validateUserPin("123456").valid).toBe(true);
      expect(validateUserPin("12345").valid).toBe(false);
      expect(validateUserPin("12345a").valid).toBe(false);
      expect(validateUserPin("12345678901234567").valid).toBe(false);
    });

    it("parses provisioned station roster with custodian, designations, and user_id sorting", () => {
      const snap = normaliseStationRosterSnapshot({
        station_mode: "provisioned",
        station_config_id: "58f23b10-91a4-4f12-8b10-001122334455",
        config_expires_at: "2026-11-05T00:00:00Z",
        custodian: {
          name: "Dr. Meera Nair",
          designation: "Medical Officer in Charge",
          phone: "+919876543210",
          onboarded_on: "2026-10-15",
          verified_by_user_id: 12,
        },
        designations: [
          { code: "mo", label: "Medical Officer" },
          { code: "anm", label: "ANM" },
        ],
        roster: [
          {
            user_id: 51,
            name: "Suresh",
            designation: "anm",
            roles: [{ role: "interviewer", project_id: "proj-1", site_id: "SITE01", org_unit_id: null }],
            active: true,
          },
          {
            user_id: 42,
            name: "Kavita",
            designation: "mo",
            roles: [
              { role: "station_supervisor", project_id: "proj-1", site_id: "SITE01", org_unit_id: null },
              { role: "coder", project_id: "proj-1", site_id: "SITE01", org_unit_id: null },
            ],
            active: true,
          },
        ],
      });

      expect(snap).not.toBeNull();
      expect(snap!.editable).toBe(false);
      expect(snap!.custodian?.name).toBe("Dr. Meera Nair");
      expect(snap!.members.map((m) => m.user_id)).toEqual([42, 51]);
      expect(snap!.members[0].is_supervisor).toBe(true);
      expect(snap!.members[0].is_coder).toBe(true);
      expect(daysUntilConfigExpiry("2026-11-05T00:00:00Z", Date.parse("2026-10-21T00:00:00Z"))).toBe(15);
    });

    it("reads in-memory __DIGITVA_LAUNCH_TOKEN__ when injected by the local station shell", () => {
      const g = globalThis as { __DIGITVA_LAUNCH_TOKEN__?: string };
      expect(getLocalStationLaunchToken()).toBeUndefined();
      g.__DIGITVA_LAUNCH_TOKEN__ = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
      try {
        expect(getLocalStationLaunchToken()).toBe(
          "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        );
      } finally {
        delete g.__DIGITVA_LAUNCH_TOKEN__;
      }
      expect(getLocalStationLaunchToken()).toBeUndefined();
    });
  });
});
