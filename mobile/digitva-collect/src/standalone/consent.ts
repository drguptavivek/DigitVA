/**
 * The consent config a standalone interview asks with: the notice bundled in the app (src/standaloneConsent.ts)
 * wrapped as a project config, so the ordinary consent screen and gate run unchanged. null when the app has no
 * notice in `language` (no fallback to another language): the interview is then blocked, never recorded unasked.
 */
import type { ProjectConsentConfig } from "../consent";
import { getStandaloneConsentNotice, type StandaloneNoticeContext } from "../standaloneConsent";

export function standaloneConsentConfig(
  projectId: string,
  language: string,
  context: StandaloneNoticeContext = {},
): ProjectConsentConfig | null {
  const notice = getStandaloneConsentNotice(language, context);
  if (!notice) return null;
  return {
    project_id: projectId,
    consent_required: true,
    notice_versions: [notice],
    contacts: {
      deletion: { email: "", phone: "" },
      mentor_institution: {},
      central_team: { email: "", phone: "" },
      dpo: null,
      districts: {},
    },
    retention: { period_days: null, expiry_action: "lock" },
    refusal_behaviour: "interview_without_informant_data",
  };
}
