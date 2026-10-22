import React, { useCallback, useEffect, useState } from "react";
import {
  Linking,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  type StyleProp,
  type ViewStyle,
} from "react-native";

import { getLocalStationLaunchToken } from "../api";
import {
  fontSize as themeFontSize,
  radius as themeRadius,
  spacing as themeSpacing,
  typography as themeTypography,
  ui,
  useTheme,
} from "../theme";
import { HeaderHelpSlot } from "./AppHeader";

const spacing = themeSpacing ?? {
  xxs: 4,
  xs: 8,
  sm: 12,
  md: 16,
  lg: 24,
  xl: 32,
  xxl: 48,
};
const radius = themeRadius ?? { sm: 4, md: 6, lg: 8, full: 9999 };
const captionTypography = themeTypography?.caption ?? {
  fontSize: themeFontSize?.caption ?? 12,
  lineHeight: 16,
  fontWeight: "400" as const,
};
const subheadTypography = themeTypography?.subhead ?? {
  fontSize: themeFontSize?.body ?? 14,
  lineHeight: 20,
  fontWeight: "400" as const,
};

export type ContextualHelpScreen =
  | "home"
  | "deathRegistration"
  | "myRegisteredDeaths"
  | "collection"
  | "interview"
  | "caseDetail"
  | "coding"
  | "caseCoding"
  | "reviewing"
  | "caseReviewing"
  | "caseView"
  | "mentoring"
  | "supervision"
  | "organization"
  | "settings";

export interface HelpSection {
  heading: string;
  items: readonly string[];
}

export interface ScreenHelpInfo {
  stageBadge: string;
  title: string;
  summary: string;
  bullets: readonly string[];
  sections: readonly HelpSection[];
  helpSlug: string;
  helpLabel: string;
}

export type ScreenHelpEntry = ScreenHelpInfo;

export const SCREEN_HELP_CONFIG: Record<ContextualHelpScreen, ScreenHelpInfo> = {
  home: {
    stageBadge: "All 5 Stages · Workspace Overview",
    title: "Your DigitVA Workspace",
    summary: "Your DigitVA personal dashboard showing your active roles, assignments, and quick actions.",
    bullets: [
      "Part of the 5-Stage Process: Start here to see which tasks need your attention today across registration, interview, coding, review, or supervision.",
      "Within Area vs All: Your badges show whether you cover a specific health facility/area ('Within Area') or the entire project ('All').",
      "Quick actions: Click any card or button (e.g., 'Start coding', 'Register a death', or 'Supervision') to jump directly into your assigned work.",
      "Role access: If you need access to another facility or role, contact your District Programme Manager or Facility In-charge.",
    ],
    sections: [
      {
        heading: "How the 5-Stage Process Works",
        items: [
          "Stage 1 (Death Register): Community health workers (ASHA, ANM, CHO) record newly reported deaths in their area.",
          "Stage 2 (Family Interview): Trained interviewers visit the household and complete the WHO Verbal Autopsy questionnaire.",
          "Stage 3 (Medical Coding): Medical Officers read the interview and assign the ICD medical cause of death.",
          "Stage 4 (Quality Review): Senior Medical Officers and Medical College Mentors independently review a sample of coded deaths.",
          "Stage 5 (Summary Reports): Facility In-charges and Programme Managers review mortality causes and operational progress.",
        ],
      },
      {
        heading: "Understanding Your Scope (Within Area vs All)",
        items: [
          "Within Area means your work is automatically filtered to your assigned health facility and all sub-units underneath it (for example, your PHC and its Sub-Centres).",
          "All means your role covers every facility across the project or district.",
        ],
      },
    ],
    helpSlug: "/help/getting-started",
    helpLabel: "Getting Started Guide",
  },
  deathRegistration: {
    stageBadge: "Stage 1 of 5 · Death Register",
    title: "Registering a Death",
    summary: "Record a newly reported death in your community or facility (Stage 1 of 5).",
    bullets: [
      "Stage 1 (Death Register): Log basic details (name, date of death, age, location) as soon as you learn about a death in your area.",
      "Save vs Save and start interview: Tap 'Save' if you or another worker will visit the family later; tap 'Save and start interview' if you are with the family right now.",
      "Within Area: Select the specific village, sub-centre, or facility where the deceased lived or died within your assigned area.",
      "Duplicate check: DigitVA automatically checks for similar deaths to prevent registering the same person twice.",
    ],
    sections: [
      {
        heading: "Filling Out the Death Register",
        items: [
          "Choose the exact health unit (Sub-Centre, PHC, or Ward) where the household is located so the right interviewer receives the case.",
          "Enter the deceased person's full name, sex, and date of death. If the exact date of birth is unknown, choose Month & Year, Year only, or Age in years.",
          "Record clear household address landmarks and informant phone numbers so the interviewer can locate the family respectfully.",
        ],
      },
      {
        heading: "Save vs Save and Start Interview",
        items: [
          "Tap 'Save' when reporting a death for a later household visit — the case enters the area worklist immediately.",
          "Tap 'Save and start interview' only when you are trained for interviews and are sitting with the bereaved family right now.",
        ],
      },
    ],
    helpSlug: "/help/data-collection",
    helpLabel: "Data Collection Guide",
  },
  myRegisteredDeaths: {
    stageBadge: "Stage 1 of 5 · Death Register",
    title: "My Registered Deaths",
    summary: "Track and update the deaths you reported before the family interview takes place.",
    bullets: [
      "Tracking status: See which of your reported deaths are pending an interview, currently in progress, or already completed.",
      "Correcting details: You can edit dates, names, or addresses for any death you registered until an interviewer finishes the interview.",
      "Family visits: Interviewers use this list to locate the household and conduct the WHO Verbal Autopsy visit.",
      "Within Area: View deaths registered across your assigned health facilities and sub-centres.",
    ],
    sections: [
      {
        heading: "Managing Reported Deaths",
        items: [
          "Review your list of reported deaths to verify that names, dates of death, and household landmarks are accurate.",
          "Tap 'Edit registration' on any pending record to fix spelling, update a phone number, or add a clearer landmark.",
        ],
      },
      {
        heading: "When a Record Locks",
        items: [
          "Once an interviewer completes and submits the family interview (Stage 2), the registration details lock so the clinical record remains consistent.",
          "If a death was registered twice by mistake, inform your Facility In-charge or Interview Supervisor so they can mark it as a duplicate.",
        ],
      },
    ],
    helpSlug: "/help/data-collection",
    helpLabel: "Data Collection Guide",
  },
  collection: {
    stageBadge: "Stage 2 of 5 · Family Interview",
    title: "Reported Deaths & Interview Worklist",
    summary: "Conduct and record the WHO Verbal Autopsy family interview (Stage 2 of 5).",
    bullets: [
      "Stage 2 (Interview): Visit the family to sensitively collect the illness history and symptoms using the WHO 2022 questionnaire.",
      "In-progress drafts: Save your draft frequently; if interrupted, you can safely resume the interview anytime from your draft list.",
      "Self-coding: If you are a Medical Officer with self-coding enabled, you can choose to assign the cause of death immediately after finishing the interview.",
      "Within Area vs All: Filter chips let you focus on interviews within your assigned facility or across all areas.",
    ],
    sections: [
      {
        heading: "Using Status & Area Filters",
        items: [
          "Use the status chips ('To visit', 'In progress', 'Completed') to see which families still need a household visit.",
          "Open any reported death card to view informant phone numbers, log a contact attempt, or schedule the next visit date.",
        ],
      },
      {
        heading: "Starting, Resuming & Self-Coding",
        items: [
          "Tap 'Start interview' when you arrive at the household, or 'Resume interview' to continue a saved draft.",
          "On the mobile app, tap 'Sync' when you have internet connectivity to upload finished interviews and download newly reported deaths.",
        ],
      },
    ],
    helpSlug: "/help/data-collection",
    helpLabel: "Data Collection Guide",
  },
  interview: {
    stageBadge: "Stage 2 of 5 · Family Interview",
    title: "WHO Verbal Autopsy Questionnaire",
    summary: "Conduct and record the household verbal autopsy interview section by section (Stage 2 of 5).",
    bullets: [
      "Automatic & manual saving: Your answers are saved automatically as you move between questions, and you can tap 'Save' anytime.",
      "Adaptive sections: The questionnaire automatically shows only the questions relevant to the deceased person's age group and sex.",
      "Local language support: Use the language selector at the top right to switch questions into Hindi or your local language while keeping English visible.",
      "Open narrative: Record the family's own story of the illness in clear clinical detail before completing the submission.",
    ],
    sections: [
      {
        heading: "Saving & Navigating Sections",
        items: [
          "Identity fields (name, sex, date of death) carried over from Stage 1 are pre-filled so you do not have to ask the family twice.",
          "If the family needs a break, tap 'Save' and 'Back to collection' — you can resume from the exact same section later.",
        ],
      },
      {
        heading: "Switching Language & Completing the Visit",
        items: [
          "Switch the form language anytime from the top header without losing any recorded answers.",
          "At the end of the questionnaire, review any highlighted required questions and submit the interview to advance the case to Stage 3 (Medical Coding).",
        ],
      },
    ],
    helpSlug: "/help/data-collection",
    helpLabel: "Data Collection Guide",
  },
  caseDetail: {
    stageBadge: "Stages 1–2 · Case Details & Follow-up",
    title: "Death Case Details & Visit Log",
    summary: "Review household address, informant contact details, visit attempts, and interview status for this death.",
    bullets: [
      "Household & informant details: View the full address, village/ward, landmark, and clickable phone numbers to contact the family.",
      "Log contact attempts: Record whether the family was reached, unavailable, moved, or refused so your supervisor sees accurate field progress.",
      "Schedule next visit: Set a planned visit date to organize your upcoming field schedule.",
      "Start or resume interview: Launch the WHO Verbal Autopsy questionnaire directly from this screen when ready.",
    ],
    sections: [
      {
        heading: "Logging Contact Attempts & Next Visit",
        items: [
          "Tap 'Log attempt' after calling or visiting the household to record the outcome (Reached, No answer, Wrong number, Moved, or Refused).",
          "Tap 'Set visit' to record the date you plan to visit the household so the worklist stays sorted by priority.",
        ],
      },
      {
        heading: "Starting or Resuming the Interview",
        items: [
          "Tap 'Start interview' to open the questionnaire with the deceased person's registration details pre-filled.",
          "If another interviewer already has an active draft on this case, DigitVA displays a notice so two workers do not interview the same family simultaneously.",
        ],
      },
    ],
    helpSlug: "/help/data-collection",
    helpLabel: "Data Collection Guide",
  },
  coding: {
    stageBadge: "Stage 3 of 5 · Medical Coding",
    title: "Medical Officer Coding Queue",
    summary: "Review interview answers and assign the medical cause of death (Stage 3 of 5).",
    bullets: [
      "Stage 3 (Coding): Read the family's narrative and symptom checklist, complete narrative quality assessment (if enabled), and select the ICD cause of death.",
      "Pick vs Random: Choose 'Start next random case' for automatic assignment or pick a specific case from your queue.",
      "Recode window: After submitting your final cause of death, you can reopen and correct your determination once, within the project's recode window (24 hours unless the project sets otherwise; 'Recode').",
      "Within Area: You only code deaths belonging to your assigned health facility, block, or district (or designated cross-facility roster).",
    ],
    sections: [
      {
        heading: "Pick a Case vs Random Allocation",
        items: [
          "Use 'Start next random case' to immediately open the next eligible completed interview matching your area and language skills.",
          "Or browse the 'Available' tab to inspect age group, sex, and health unit before picking a specific case.",
        ],
      },
      {
        heading: "Available vs My Coded Cases (Recode Window)",
        items: [
          "Cases currently assigned to you appear at the top so you can resume where you left off.",
          "Switch to 'My coded cases' to view cases you have already finalized; until the recode deadline shown on the case (24 hours after coding unless the project sets otherwise), you can click 'Recode' to revise your cause of death before the case enters Stage 4 review.",
        ],
      },
    ],
    helpSlug: "/help/coding-workflow",
    helpLabel: "Coding Workflow Guide",
  },
  caseCoding: {
    stageBadge: "Stage 3 of 5 · Coding a Case",
    title: "Assigning the Medical Cause of Death",
    summary: "Read the family narrative and symptom checklist on the left, then record Step 1 (Initial) and Step 2 (Final) ICD cause of death.",
    bullets: [
      "Left-to-right clinical review: Browse symptom categories, open-ended narrative, and any required quality panels before opening the COD assessment tab.",
      "Step 1 (Initial) & Step 2 (Final): Record your initial clinical impression in Step 1, review any decision-support reference, and submit your conclusive cause in Step 2.",
      "ICD search: Search by medical term or ICD code; DigitVA automatically filters codes appropriate for the deceased person's age and sex.",
      "Private notes: Use the Notes panel to jot down clinical reasoning while examining the case.",
    ],
    sections: [
      {
        heading: "Step 1 (Initial) & Step 2 (Final) Assessment",
        items: [
          "First review each symptom category on the left sidebar (and complete Narrative Quality or Social Autopsy panels if prompted).",
          "In Step 1, select the immediate and antecedent/underlying ICD causes based on your clinical judgment and save.",
          "In Step 2, confirm or refine the conclusive underlying cause of death and submit to complete coding.",
        ],
      },
      {
        heading: "When a Case Cannot Be Coded",
        items: [
          "If the interview lacks sufficient clinical information to determine any cause, use the 'Not codeable' option and state the reason clearly.",
          "If you need to step away and return the case to the general pool for another Medical Officer, use 'Release case'.",
        ],
      },
    ],
    helpSlug: "/help/coding-workflow",
    helpLabel: "Coding Workflow Guide",
  },
  reviewing: {
    stageBadge: "Stage 4 of 5 · Quality Review",
    title: "Senior Reviewer Queue",
    summary: "Independently review a sample of coded cases for clinical quality assurance (Stage 4 of 5).",
    bullets: [
      "Stage 4 (Review): Senior Medical Officers and Medical College Faculty independently assess cases once the original coder's recode window has closed.",
      "Independent assessment: You evaluate the narrative and symptoms without seeing the first coder's decision to ensure unbiased quality control.",
      "Reviewer authority: Your reviewed cause of death serves as the final quality-assured determination while preserving the first coder's record in history.",
      "Within Area: Cases are drawn from your assigned district, block, or mentoring medical college partner area.",
    ],
    sections: [
      {
        heading: "Selecting a Case to Review",
        items: [
          "Cases appear in this queue only after the original coder has finalized Step 2 and the project's recode window has elapsed.",
          "Click 'Start next random review' or select a case from the 'Available' tab to begin your quality review.",
        ],
      },
      {
        heading: "Blinded Quality Assurance",
        items: [
          "During your review, the original coder's ICD selection is hidden so your clinical judgment remains completely independent.",
          "If you also hold a reviewer role, you may review a case you coded yourself.",
        ],
      },
    ],
    helpSlug: "/help/coding-workflow",
    helpLabel: "Coding Workflow Guide",
  },
  caseReviewing: {
    stageBadge: "Stage 4 of 5 · Reviewing a Case",
    title: "Conducting an Independent Quality Review",
    summary: "Evaluate the symptom history and narrative, complete your independent cause-of-death assessment, and finalize the review.",
    bullets: [
      "Blinded evaluation: Review all interview sections and narrative details on the left before recording your independent ICD assessment.",
      "Two-step review: Save your initial reviewer impression (Step 1) and then confirm your final conclusive cause of death (Step 2).",
      "Audit preservation: DigitVA preserves both the original coder's assessment and your reviewer determination in the permanent audit trail.",
      "Reviewer recode: After submitting your review, you can reopen and adjust your determination within the project's recode window (24 hours unless the project sets otherwise).",
    ],
    sections: [
      {
        heading: "Completing the Reviewer Assessment",
        items: [
          "Examine each symptom category and the open narrative using the left navigation list.",
          "Select the ICD cause of death in the COD Assessment panel and submit both Step 1 and Step 2 to mark the case as Reviewed.",
        ],
      },
      {
        heading: "Releasing or Returning a Case",
        items: [
          "If you cannot complete the review right now, click 'Release' so another Senior Reviewer or Medical College Mentor can pick it up.",
        ],
      },
    ],
    helpSlug: "/help/coding-workflow",
    helpLabel: "Coding Workflow Guide",
  },
  caseView: {
    stageBadge: "Stages 3–4 · Read-Only Case View",
    title: "Completed Case Summary & Audit Trail",
    summary: "Read-only clinical view of the interview responses, coded causes of death, SmartVA reference, and workflow history.",
    bullets: [
      "Read-only inspection: Browse every questionnaire section and the family narrative without modifying any clinical data.",
      "COD Reference card: Compare the Final COD, Reviewer determination, and Initial Coder assessment side by side.",
      "Workflow History: Inspect the chronological audit log of registration, interview submission, coding, and review events.",
      "Recode button: If you coded or reviewed this case and its recode window is still open, use the 'Recode' action in the queue to make corrections.",
    ],
    sections: [
      {
        heading: "Browsing Symptom Categories & COD Reference",
        items: [
          "Click any category on the left sidebar to inspect the respondent's answers and highlighted positive symptoms.",
          "Scroll down to the COD Reference card to see the conclusive, immediate, and antecedent causes recorded for this death.",
        ],
      },
      {
        heading: "Recoding Within the Recode Window",
        items: [
          "This screen is read-only so you can safely review past work without accidental edits.",
          "If your recode window is still open, return to 'My coded cases' or 'My reviewed cases' and click 'Recode' to reopen the assessment editor.",
        ],
      },
    ],
    helpSlug: "/help/viewing-history",
    helpLabel: "Viewing History Guide",
  },
  mentoring: {
    stageBadge: "Stages 3–5 · Medical College Mentoring",
    title: "Mentoring Institution Portal",
    summary: "Medical college faculty and resident mentoring roster and district assignments.",
    bullets: [
      "Medical college role: Medical colleges provide academic mentoring and quality coding/review support to partner health districts.",
      "College roster: The College / Institute Admin adds and manages accounts for professors, assistant professors, and resident doctors.",
      "District assignments: District Programme Managers assign specific Within Area roles (Coder, Reviewer, Coding Tester, Viewer) to college mentors.",
      "Outside district headcount: Mentors sit alongside district staff without taking up permanent district health cadre posts.",
    ],
    sections: [
      {
        heading: "How Medical College Mentoring Works",
        items: [
          "Each Medical College or Mentoring Institute is linked to one or more partner districts or health areas.",
          "Faculty and residents assigned as Reviewers (Stage 4) or Coders (Stage 3) can jump directly to their Coding or Review queues from this page.",
        ],
      },
      {
        heading: "Roster Management vs District Role Assignment",
        items: [
          "If you are a Mentoring Institute Admin, use the roster table below to add faculty/residents, update their designations, or deactivate accounts.",
          "District Programme Managers then grant those college members 'Within Area' roles on the specific blocks or districts they support.",
        ],
      },
    ],
    helpSlug: "/help/mentoring-institutes",
    helpLabel: "Mentoring Institutes Guide",
  },
  supervision: {
    stageBadge: "Stage 2 Oversight · Field Supervision",
    title: "Interview Supervision & Quality Triage",
    summary: "Monitor field interview progress, resolve flags, and address duplicate reports.",
    bullets: [
      "Supervisory oversight: Facility In-charges (SMO/MO) track field interviewers, visit schedules, and completed interviews in their area.",
      "Resolving flags: Review cases where an interviewer reported a problem, family refusal, or duplicate registration.",
      "Reopen or cancel: Authorised supervisors can reopen an interview sent back for revision or cancel invalid registrations.",
      "Within Area: You supervise interviews and field staff across your assigned health facility and every sub-centre under it.",
    ],
    sections: [
      {
        heading: "Attention Tiles and the Deaths Tab",
        items: [
          "Four tiles count your cases: 'Needs my decision' (a flag waits or a second complete interview is to be chosen), 'Overdue revisits', 'Stuck (30 days)' and 'Total in scope'. Tap a tile to filter the list.",
          "In the Deaths tab, 'Needs my attention' lists those cases; switch to 'All deaths' to monitor every registered death across your facility's catchment area.",
        ],
      },
      {
        heading: "Supervisor Actions (Reopen, Duplicate, Close)",
        items: [
          "Use 'Reopen for revision' when an interviewer needs to return to the household to complete a partial interview or fix an error.",
          "Use 'Mark duplicate' or 'Cancel/Close' with a clear note when a death was registered twice or outside your jurisdiction.",
        ],
      },
    ],
    helpSlug: "/help/user-roles",
    helpLabel: "User Roles Guide",
  },
  organization: {
    stageBadge: "Health System Hierarchy · Within Area",
    title: "My Health Facility & Organization Tree",
    summary: "Manage health facilities, worker cadres, and user role grants across the health system.",
    bullets: [
      "Administrative hierarchy: View and configure the health system levels (District, Block/CHC, PHC, Sub-centre, Village).",
      "Assigning roles: Programme Managers and In-charges assign roles (Interviewer, Coder, Reviewer, Supervisor) to health workers.",
      "Scope ('Within Area' vs 'All'): Choose whether a worker's role covers their own facility subtree ('Within Area'), selected cross-area units, or the entire project.",
      "QR onboarding: Generate one-scan login QR codes to onboard field workers into the DigitVA mobile app instantly.",
    ],
    sections: [
      {
        heading: "Understanding Your 'Within Area' Coverage",
        items: [
          "Your assigned unit is highlighted in the tree; 'Within Area' access automatically includes that unit and all child facilities beneath it.",
          "Expand any Block/CHC, PHC, or Sub-Centre node to see its child units and reporting structure.",
        ],
      },
      {
        heading: "Viewing Facility Staff & Sub-Units",
        items: [
          "Click any health unit in the tree to see the health workers, Medical Officers, and supervisors assigned to that facility.",
          "Programme Managers and Admins can also add new sub-units or assign worker roles directly from the selected unit panel.",
        ],
      },
    ],
    helpSlug: "/help/user-roles",
    helpLabel: "User Roles Guide",
  },
  settings: {
    stageBadge: "Preferences · Display & Device",
    title: "App Settings & Display Preferences",
    summary: "Customize your colour theme (System, Light, or Dark) and manage your local device preferences.",
    bullets: [
      "Appearance modes: Choose 'System' to follow your device's day/night schedule, 'Light' for bright outdoor field visits, or 'Dark' for low-glare reading.",
      "Instant saving: Your display preference is saved immediately on this browser or phone.",
      "Profile & passkeys: To change your coding languages, password, or passkey sign-in, open your account menu at the top right.",
    ],
    sections: [
      {
        heading: "Display Theme & Language",
        items: [
          "Select 'Light' mode for high contrast in daylight when conducting household interviews outdoors.",
          "Select 'Dark' mode when coding or reviewing cases in low-light clinical environments.",
        ],
      },
    ],
    helpSlug: "/help/getting-started",
    helpLabel: "Getting Started Guide",
  },
};

const remoteHelpCache = new Map<ContextualHelpScreen, ScreenHelpInfo>();

export function clearContextualHelpCache(): void {
  remoteHelpCache.clear();
}

function normalizeHelpPayload(
  fallback: ScreenHelpInfo,
  payload: unknown,
): ScreenHelpInfo | null {
  if (!payload || typeof payload !== "object") return null;
  const record = payload as Record<string, unknown>;
  const summary = typeof record.summary === "string" && record.summary.trim()
    ? record.summary.trim()
    : fallback.summary;
  const title = typeof record.title === "string" && record.title.trim()
    ? record.title.trim()
    : fallback.title;
  const stageBadge = typeof (record.stage_badge ?? record.stageBadge) === "string"
    ? String(record.stage_badge ?? record.stageBadge)
    : fallback.stageBadge;
  const helpSlug = typeof (record.help_slug ?? record.helpSlug) === "string"
    ? String(record.help_slug ?? record.helpSlug)
    : fallback.helpSlug;
  const helpLabel = typeof (record.help_label ?? record.helpLabel) === "string"
    ? String(record.help_label ?? record.helpLabel)
    : fallback.helpLabel;
  const bullets = Array.isArray(record.bullets)
    ? record.bullets.filter((item): item is string => typeof item === "string")
    : fallback.bullets;
  const sections = Array.isArray(record.sections)
    ? record.sections
        .filter((sec): sec is { heading: string; items: string[] } =>
          Boolean(
            sec &&
              typeof sec === "object" &&
              typeof (sec as Record<string, unknown>).heading === "string" &&
              Array.isArray((sec as Record<string, unknown>).items),
          ),
        )
        .map((sec) => ({
          heading: sec.heading,
          items: sec.items.filter((item): item is string => typeof item === "string"),
        }))
    : fallback.sections;

  return {
    stageBadge,
    title,
    summary,
    bullets: bullets.length ? bullets : fallback.bullets,
    sections: sections.length ? sections : fallback.sections,
    helpSlug,
    helpLabel,
  };
}

/**
 * Fetch contextual help for a screen from the dedicated `/api/v1/help/contextual/<screen>` API.
 * Falls back gracefully to `null` when offline or unauthenticated. The offline station (a per-launch
 * token is present) has no help route: it uses the static help without a request.
 */
export async function fetchContextualHelp(
  screen: ContextualHelpScreen,
): Promise<ScreenHelpInfo | null> {
  const cached = remoteHelpCache.get(screen);
  if (cached) return cached;
  if (typeof fetch !== "function" || getLocalStationLaunchToken()) return null;
  try {
    const response = await fetch(
      `/api/v1/help/contextual/${encodeURIComponent(screen)}`,
      {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      },
    );
    if (!response || !response.ok) return null;
    const payload: unknown = await response.json();
    const fallback = SCREEN_HELP_CONFIG[screen] ?? SCREEN_HELP_CONFIG.home;
    const normalized = normalizeHelpPayload(fallback, payload);
    if (normalized) {
      remoteHelpCache.set(screen, normalized);
    }
    return normalized;
  } catch {
    return null;
  }
}

function storageKey(screen: ContextualHelpScreen): string {
  return `digitva.helpExpanded.${screen}`;
}

export function readExpandedPreference(screen: ContextualHelpScreen): boolean {
  try {
    if (typeof window !== "undefined" && window.localStorage) {
      return window.localStorage.getItem(storageKey(screen)) === "true";
    }
  } catch {
    // Storage unavailable
  }
  return false;
}

export function writeExpandedPreference(screen: ContextualHelpScreen, expanded: boolean): void {
  try {
    if (typeof window !== "undefined" && window.localStorage) {
      window.localStorage.setItem(storageKey(screen), String(expanded));
    }
  } catch {
    // Storage unavailable
  }
}

export function openHelpGuide(url: string): void {
  if (typeof window !== "undefined" && typeof window.open === "function") {
    try {
      window.open(url, "_blank");
      return;
    } catch {
      // Fallback to Linking
    }
  }
  try {
    const res = Linking.openURL(url);
    if (res && typeof (res as Promise<unknown>).catch === "function") {
      void (res as Promise<unknown>).catch(() => undefined);
    }
  } catch {
    // Storage or linking unavailable
  }
}

export interface ContextualHelpBannerProps {
  screen: ContextualHelpScreen;
  testID?: string;
  style?: StyleProp<ViewStyle>;
}

export function ContextualHelpBanner({ screen, testID, style }: ContextualHelpBannerProps) {
  const theme = useTheme();
  const colors = theme?.colors ?? ({} as Record<string, string | undefined>);
  const bundled = SCREEN_HELP_CONFIG[screen] ?? SCREEN_HELP_CONFIG.home;
  const [remoteConfig, setRemoteConfig] = useState<ScreenHelpInfo | null>(
    () => remoteHelpCache.get(screen) ?? null,
  );
  const config = remoteConfig ?? bundled;
  const [expanded, setExpanded] = useState<boolean>(false);

  useEffect(() => {
    setExpanded(false);
    setRemoteConfig(remoteHelpCache.get(screen) ?? null);
  }, [screen]);

  useEffect(() => {
    if (Platform.OS !== "web" || typeof document === "undefined") return undefined;
    const styleId = "digitva-contextual-help-fixed-css";
    if (document.getElementById(styleId)) return undefined;
    const el = document.createElement("style");
    el.id = styleId;
    el.textContent = `
      #digitva-help-flyout {
        position: fixed !important;
        top: 56px !important;
        right: 0 !important;
        bottom: 0 !important;
        left: 0 !important;
        z-index: 1060 !important;
      }
    `;
    document.head.appendChild(el);
    return undefined;
  }, []);

  useEffect(() => {
    if (!expanded || process.env.NODE_ENV === "test") return undefined;
    let active = true;
    void fetchContextualHelp(screen).then((result) => {
      if (active && result) {
        setRemoteConfig(result);
      }
    });
    return () => {
      active = false;
    };
  }, [expanded, screen]);

  const toggleExpanded = useCallback(() => {
    setExpanded((prev) => {
      const next = !prev;
      writeExpandedPreference(screen, next);
      return next;
    });
  }, [screen]);

  const handleOpenGuide = useCallback(() => {
    openHelpGuide(config.helpSlug);
  }, [config.helpSlug]);

  // On the web the trigger sits in the app header (never over page toolbars); the bar is brand blue in both modes.
  return <HeaderHelpSlot>{(inHeader) => (
    <View
      testID={testID ?? `contextual-help-${screen}`}
      accessibilityRole="summary"
      accessibilityLabel="Contextual help"
      style={[inHeader ? styles.headerAnchor : styles.inlineAnchor, style]}
    >
      <Pressable
        nativeID="digitva-help-trigger"
        testID={`contextual-help-toggle-${screen}`}
        accessibilityRole="button"
        accessibilityLabel={expanded ? "Hide guide" : "How this screen works"}
        accessibilityState={{ expanded }}
        hitSlop={spacing.xs}
        onPress={toggleExpanded}
        style={({ pressed }) => [
          styles.triggerPill,
          {
            backgroundColor: inHeader ? "transparent" : colors.accent,
            borderColor: inHeader ? ui.light.primaryForeground : colors.accent,
            opacity: pressed ? 0.85 : 1,
          },
        ]}
      >
        <View style={[styles.badge, { backgroundColor: inHeader ? ui.light.primaryForeground : colors.surface }]}>
          <Text style={[styles.badgeText, { color: inHeader ? ui.light.primary : colors.accent }]}>?</Text>
        </View>
        <Text style={[styles.triggerText, { color: inHeader ? ui.light.primaryForeground : colors.surface }]}>Help</Text>
      </Pressable>

      {!expanded ? (
        <>
          <Text style={styles.srOnly}>{config.summary}</Text>
          <Pressable
            testID={`contextual-help-link-${screen}`}
            accessibilityRole="link"
            accessibilityLabel={`Open ${config.helpLabel}`}
            onPress={handleOpenGuide}
            style={styles.srOnly}
          >
            <Text style={styles.srOnly}>Open Help Guide ↗</Text>
          </Pressable>
        </>
      ) : null}

      {expanded ? (
        <View
          nativeID="digitva-help-flyout"
          testID={`contextual-help-flyout-${screen}`}
          style={
            Platform.OS === "web"
              ? styles.flyoutOverlayWeb
              : styles.flyoutOverlayNative
          }
        >
          <Pressable
            testID={`contextual-help-backdrop-${screen}`}
            onPress={toggleExpanded}
            style={[
              styles.flyoutBackdrop,
              {
                backgroundColor: colors.text,
              },
            ]}
          />
          <View
            testID={`contextual-help-bullets-${screen}`}
            style={[
              styles.flyoutDrawer,
              {
                backgroundColor: colors.surface,
                borderColor: colors.border,
              },
            ]}
          >
            <View style={styles.expandedHeaderRow}>
              <View style={styles.headerTitleStack}>
                <View
                  style={[
                    styles.stagePill,
                    {
                      backgroundColor: colors.accentSoft,
                      borderColor: colors.border,
                    },
                  ]}
                >
                  <Text style={[styles.stagePillText, { color: colors.accent }]}>
                    {config.stageBadge}
                  </Text>
                </View>
                <Text style={[styles.titleText, { color: colors.text }]}>
                  {config.title}
                </Text>
              </View>
              <Pressable
                testID={`contextual-help-close-${screen}`}
                hitSlop={spacing.xs}
                onPress={toggleExpanded}
                style={({ pressed }) => [
                  styles.toggleButton,
                  {
                    backgroundColor: colors.surfaceMuted,
                    borderColor: colors.border,
                    opacity: pressed ? 0.75 : 1,
                  },
                ]}
              >
                <Text style={[styles.buttonText, { color: colors.text }]}>
                  Hide guide ▴
                </Text>
              </Pressable>
            </View>

            <View style={[styles.divider, { backgroundColor: colors.border }]} />

            <ScrollView style={styles.flyoutScroll} contentContainerStyle={styles.flyoutBody}>
              <Text style={[styles.summaryText, { color: colors.text }]}>
                {config.summary}
              </Text>

              <View style={styles.bulletList}>
                {config.bullets.map((point, index) => (
                  <View key={index} style={styles.bulletRow}>
                    <Text style={[styles.bulletDot, { color: colors.accent }]}>•</Text>
                    <Text style={[styles.bulletText, { color: colors.textMuted }]}>
                      {point}
                    </Text>
                  </View>
                ))}
              </View>

              {config.sections.length > 0 ? (
                <View
                  testID={`contextual-help-sections-${screen}`}
                  style={styles.sectionsGrid}
                >
                  {config.sections.map((section, secIndex) => (
                    <View
                      key={secIndex}
                      style={[
                        styles.sectionCard,
                        {
                          backgroundColor: colors.surfaceMuted,
                          borderColor: colors.border,
                        },
                      ]}
                    >
                      <Text style={[styles.sectionHeading, { color: colors.accent }]}>
                        {section.heading}
                      </Text>
                      {section.items.map((item, itemIndex) => (
                        <View key={itemIndex} style={styles.bulletRow}>
                          <Text style={[styles.bulletDot, { color: colors.accent }]}>‣</Text>
                          <Text style={[styles.bulletText, { color: colors.text }]}>
                            {item}
                          </Text>
                        </View>
                      ))}
                    </View>
                  ))}
                </View>
              ) : null}
            </ScrollView>

            <View style={[styles.divider, { backgroundColor: colors.border }]} />

            <Pressable
              testID={`contextual-help-link-${screen}`}
              accessibilityRole="link"
              accessibilityLabel={`Open ${config.helpLabel}`}
              hitSlop={spacing.xs}
              onPress={handleOpenGuide}
              style={({ pressed }) => [
                styles.linkButton,
                {
                  backgroundColor: colors.accentSoft,
                  borderColor: colors.accent,
                  opacity: pressed ? 0.85 : 1,
                },
              ]}
            >
              <Text style={[styles.linkButtonText, { color: colors.accent }]}>
                Open Help Guide ↗
              </Text>
            </Pressable>
          </View>
        </View>
      ) : null}
    </View>
  )}</HeaderHelpSlot>;
}

const styles = StyleSheet.create({
  headerAnchor: {
    flexShrink: 0,
    marginRight: spacing.xs,
  },
  inlineAnchor: {
    alignSelf: "flex-end",
    zIndex: 45,
  },
  triggerPill: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xxs,
    borderWidth: 1,
    borderRadius: radius.full,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xxs,
  },
  triggerText: {
    ...captionTypography,
    fontWeight: "700",
  },
  srOnly: {
    position: "absolute",
    width: 1,
    height: 1,
    opacity: 0,
    overflow: "hidden",
  },
  flyoutOverlayWeb: {
    position: "fixed" as unknown as "absolute",
    left: 0,
    right: 0,
    top: 0,
    bottom: 0,
    zIndex: 60,
    flexDirection: "row",
    justifyContent: "flex-end",
  },
  flyoutOverlayNative: {
    position: "absolute",
    left: 0,
    right: 0,
    top: 0,
    bottom: 0,
    zIndex: 60,
    flexDirection: "row",
    justifyContent: "flex-end",
  },
  flyoutBackdrop: {
    position: "absolute",
    left: 0,
    right: 0,
    top: 0,
    bottom: 0,
    opacity: 0.45,
  },
  flyoutDrawer: {
    width: "88%",
    maxWidth: 380,
    height: "100%",
    borderLeftWidth: 1,
    padding: spacing.md,
    gap: spacing.sm,
    zIndex: 61,
  },
  flyoutScroll: {
    flex: 1,
  },
  flyoutBody: {
    gap: spacing.sm,
    paddingBottom: spacing.sm,
  },
  headerTitleStack: {
    flex: 1,
    alignItems: "flex-start",
    gap: spacing.xxs,
  },
  badge: {
    width: 18,
    height: 18,
    borderRadius: radius.full,
    alignItems: "center",
    justifyContent: "center",
  },
  badgeText: {
    ...captionTypography,
    fontWeight: "700",
    lineHeight: 16,
  },
  summaryText: {
    ...captionTypography,
    lineHeight: 18,
  },
  toggleButton: {
    borderWidth: 1,
    borderRadius: radius.full,
    paddingHorizontal: spacing.xs,
    paddingVertical: spacing.xxs,
  },
  buttonText: {
    ...captionTypography,
    fontWeight: "600",
  },
  linkButton: {
    borderWidth: 1,
    borderRadius: radius.full,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    alignItems: "center",
  },
  linkButtonText: {
    ...captionTypography,
    fontWeight: "600",
  },
  divider: {
    height: 1,
    width: "100%",
  },
  expandedHeaderRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: spacing.xs,
  },
  titleText: {
    ...subheadTypography,
    fontWeight: "700",
  },
  stagePill: {
    borderWidth: 1,
    borderRadius: radius.full,
    paddingHorizontal: spacing.xs,
    paddingVertical: 2,
  },
  stagePillText: {
    ...captionTypography,
    fontWeight: "600",
  },
  bulletList: {
    gap: spacing.xxs,
  },
  bulletRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.xs,
  },
  bulletDot: {
    ...captionTypography,
    lineHeight: 18,
    fontWeight: "700",
  },
  bulletText: {
    ...captionTypography,
    flex: 1,
    lineHeight: 18,
  },
  sectionsGrid: {
    gap: spacing.xs,
    paddingTop: spacing.xxs,
  },
  sectionCard: {
    borderWidth: 1,
    borderRadius: radius.sm,
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.sm,
    gap: spacing.xxs,
  },
  sectionHeading: {
    ...captionTypography,
    fontWeight: "700",
  },
});

export default ContextualHelpBanner;
