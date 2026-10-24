/**
 * Register a death with the web form's validation. Interviewers may save it
 * offline and start its questionnaire; reporter-only targets post online.
 *
 * A new registration being typed is kept in the encrypted store (debounced,
 * and flushed when the app is hidden, the screen loses focus or the store
 * locks) with its client death id, so returning restores it and a later save
 * reuses the same id (no duplicate). The screen still clears the visible
 * fields while hidden. Only Save or Discard (confirmed) removes the copy.
 * The browser registration keeps its wipe-on-hide rule (src/web).
 */
import { randomUUID } from "expo-crypto";
import { Redirect, useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, AppState, Text, View } from "react-native";
import { WhoVaQuestionControls } from "@drguptavivek/who-2022-va/native";
import {
  resolveUiMessages,
  WHO_VA_BUILT_IN_UI_TRANSLATIONS,
  type AnswerValue,
  type InstrumentQuestion,
  type QuestionControl,
  type ValidationIssue,
} from "@drguptavivek/who-2022-va";

import { useAppState } from "../AppState";
import { useStableAccount } from "../useStableAccount";
import {
  getDeathRegistrationAccess,
  getNativeRegistrationCase,
  getNativeRegisteredDeaths,
  patchNativeDeathRegistration,
  postNativeDeathRegistration,
  type RegistrationCase,
  type RegistrationChanges,
} from "../deathRegistrationApi";
import { ApiError, hasInterviewRegistrationAccess, intakeContextFromAccess, type AccessSummary, type CaseRow } from "../api";
import {
  cleanRegistration,
  getRegistration,
  getRegistrationRefusal,
  keepRegistrationConsentForCase,
  localToday,
  MAX_REGISTRATION_AGE,
  registrationAgeInfoIssue,
  registrationNeedsAgeConfirmation,
  saveRegistration,
  SEX_VALUES,
  validateRegistration,
  type RegistrationFields,
} from "../cases";
import { getMeta, setMeta, type Db } from "../drafts";
import type { ProjectConsentConfig } from "../consent";
import {
  coveredFieldsOf,
  getConsentConfig,
  getRegistrationConsent,
  registrationConsentGate,
  saveRegistrationConsent,
  storedConsent,
  withoutCovered,
  type StoredConsent,
} from "../consentStore";
import { sendRefusal } from "../unsentWork";
import { RespondentConsentPanel } from "../web/StationConsentPanel";
import { t, uiLocale, type StringKey } from "../i18n";
import { isUnlocked, openInterviewerDb } from "../interviewerDb";
import { platformServices } from "../platform";
import { calculateRegistrationAge } from "../registrationAgeDisplay";
import { formatRegistrationAge } from "../registrationAgeText";
import { IdentifierFields, identifierIssueText } from "../IdentifierFields";
import {
  identifierChanges, identifierFieldErrors, identifierIssues, identifierValues, isBadgeOnly,
  type CaseIdentifier, type IdentifierType,
} from "../identifiers";
import {
  getCachedIdentifierTypes,
  getCachedReferenceData,
  refreshIdentifierTypes,
  registersDeaths,
  targetsFrom,
  type ProjectSettings,
  type ReferenceData,
  type Target,
} from "../sync";
import { Button, Row, Screen, useUiStyles } from "../ui";
import { ConfirmDialog } from "../ConfirmDialog";
import { useLeaveGuard } from "../leaveGuard";
import { MultilineInput } from "../MultilineInput";
import { PhoneNumbers } from "../PhoneInput";

type Field = Exclude<keyof RegistrationFields, "identifiers">;
type BirthMode = "exact" | "month-year" | "year" | "unknown";

const REGISTRATION_FIELDS: Field[] = [
  "deceased_name", "deceased_sex", "date_of_death", "date_of_birth",
  "date_of_birth_partial", "age_years", "abha_number", "abha_address",
  "place_of_death", "address", "address_house_street", "address_village_ward",
  "address_landmark", "informant_name", "informant_phone", "informant_phone_2",
  "father_name", "mother_name", "remarks",
];

function registrationFieldsFromCase(value: RegistrationCase | CaseRow): RegistrationFields {
  const source = value as unknown as Record<string, unknown>;
  if (typeof source.death_id !== "string" || !source.death_id || typeof source.project_id !== "string" ||
      !source.project_id || typeof source.site_id !== "string" || !source.site_id) throw new Error("malformed_registration");
  const nested = isRecord(source.deceased) ? source.deceased : source;
  const address = isRecord(source.household_address) ? source.household_address : source;
  const informant = isRecord(source.informant) ? source.informant : source;
  const text = (item: unknown) => {
    if (item === undefined || item === null) return "";
    if (typeof item === "string") return item;
    throw new Error("malformed_registration");
  };
  const age = nested.age_years;
  if (age !== undefined && age !== null && (typeof age !== "number" || !Number.isFinite(age))) throw new Error("malformed_registration");
  return {
    deceased_name: text(nested.name ?? nested.deceased_name),
    deceased_sex: text(nested.sex ?? nested.deceased_sex),
    date_of_death: text(nested.date_of_death),
    date_of_birth: text(nested.date_of_birth),
    date_of_birth_partial: text(nested.date_of_birth_partial),
    age_years: typeof age === "number" ? String(age) : "",
    abha_number: text(value.abha_number),
    abha_address: text(value.abha_address),
    place_of_death: text(nested.place_of_death),
    address: text(address.address),
    address_house_street: text(address.house_street ?? address.address_house_street),
    address_village_ward: text(address.village_ward ?? address.address_village_ward),
    address_landmark: text(address.landmark ?? address.address_landmark),
    informant_name: text(informant.name ?? informant.informant_name),
    informant_phone: text(informant.phone ?? informant.informant_phone),
    informant_phone_2: text(informant.phone_2 ?? informant.informant_phone_2),
    father_name: text(value.father_name),
    mother_name: text(value.mother_name),
    remarks: text(value.remarks),
    identifiers: identifierValues(source.identifiers as CaseIdentifier[] | undefined),
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

/** Text fields in the web form's order, with their label. */
const TEXT_FIELDS: Array<{
  name: Field;
  label: StringKey;
  help?: StringKey;
}> = [
  { name: "deceased_name", label: "fieldDeceasedName" },
  { name: "date_of_death", label: "fieldDateOfDeath" },
  { name: "address", label: "fieldAddress" },
  { name: "informant_name", label: "fieldInformantName" },
  // Rendered with informant_phone_2 by PhoneNumbers.
  { name: "informant_phone", label: "fieldPhoneNumber" },
  { name: "abha_number", label: "fieldAbhaNumber" },
  { name: "abha_address", label: "fieldAbhaAddress" },
  { name: "place_of_death", label: "fieldPlaceOfDeath" },
  { name: "address_house_street", label: "fieldHouseStreet" },
  { name: "address_village_ward", label: "fieldVillageWard" },
  { name: "address_landmark", label: "fieldLandmark" },
  { name: "father_name", label: "fieldFatherName" },
  { name: "mother_name", label: "fieldMotherName" },
  { name: "remarks", label: "fieldRemarks", help: "remarksHelp" },
];

/** Restore the DOB choice without inventing precision for age-only records. */
export function birthModeFor(fields: RegistrationFields): BirthMode {
  if (fields.date_of_birth?.trim()) return "exact";
  if (/^\d{4}-\d{2}$/.test(fields.date_of_birth_partial?.trim() ?? ""))
    return "month-year";
  if (/^\d{4}$/.test(fields.date_of_birth_partial?.trim() ?? "")) return "year";
  if (fields.age_years?.trim()) return "unknown";
  return "exact";
}

/** The encrypted-store copy of the new registration being typed (one per interviewer). */
const IN_PROGRESS_KEY = "registration-in-progress";

interface InProgressRegistration {
  clientDeathId: string;
  projectId?: string;
  siteId?: string;
  orgUnitId?: string | null;
  fields: RegistrationFields;
  birthMode: BirthMode;
  ageConfirmationPending: boolean;
  ageConfirmationStartAfter: boolean;
}

function hasContent(fields: RegistrationFields): boolean {
  const { identifiers, ...rest } = fields;
  return Object.values(rest).some((value) => typeof value === "string" && value.trim() !== "") ||
    Object.values(identifiers ?? {}).some((value) => typeof value === "string" && value.trim() !== "");
}

export function requiredBirthField(
  mode: BirthMode,
  fields: RegistrationFields,
): "date_of_birth" | "date_of_birth_partial" | undefined {
  if (mode === "unknown") return undefined;
  if (mode === "exact")
    return fields.date_of_birth?.trim() ? undefined : "date_of_birth";
  return fields.date_of_birth_partial?.trim()
    ? undefined
    : "date_of_birth_partial";
}

function nativeQuestion(
  field: Field,
  label: string,
  appearance?: string,
  readOnly = false,
): InstrumentQuestion {
  const control: QuestionControl =
    field === "date_of_death" ||
    field === "date_of_birth" ||
    field === "date_of_birth_partial"
      ? "date"
      : field === "age_years"
        ? "integer"
        : "text";
  return {
    name: field,
    order: 0,
    sourceRow: 0,
    sourceType: "digitva-registration",
    dataType:
      control === "date" ? "date" : control === "integer" ? "number" : "string",
    control,
    label: { en: label },
    hint: {},
    guidance: {},
    required: field === "deceased_name" || field === "date_of_death",
    readOnly,
    constraintMessage: {},
    sectionPath: [],
    ...(appearance ? { appearance } : {}),
  };
}

export function NativeRegistrationFieldControl({
  field,
  label,
  value,
  onChange,
  issue,
  onIssue,
  appearance = "exact",
  disabled = false,
}: {
  field: Field;
  label: string;
  value: string;
  onChange: (value: string) => void;
  issue?: StringKey;
  onIssue?: (issue?: StringKey) => void;
  appearance?: "exact" | "month-year" | "year" | "multiline";
  disabled?: boolean;
}) {
  const question = nativeQuestion(
    field,
    label,
    appearance === "exact" ? undefined : appearance,
    disabled,
  );
  const issues: ValidationIssue[] = issue
    ? [{ question: field, code: "constraint", message: t(issue) }]
    : [];
  const locale = uiLocale();
  const onIssueRef = useRef(onIssue);
  onIssueRef.current = onIssue;
  const onDraftIssue = useCallback(
    (_question: string, draftIssue?: ValidationIssue) => {
      onIssueRef.current?.(draftIssue ? "errDate" : undefined);
    },
    [],
  );
  const controlProps = {
    question,
    value: (field === "age_years"
      ? value
        ? Number(value)
        : undefined
      : field === "date_of_birth_partial" && value
        ? `${value}${appearance === "year" ? "-01-01" : "-01"}`
        : value || undefined) as AnswerValue | undefined,
    data: {},
    locale,
    messages: resolveUiMessages(locale, WHO_VA_BUILT_IN_UI_TRANSLATIONS),
    issues,
    onAnswer: (next: AnswerValue | undefined) => {
      if (
        field === "age_years" &&
        typeof next === "number" &&
        (next < 0 || next > MAX_REGISTRATION_AGE)
      ) {
        onChange(String(next));
        onIssue?.("errAge");
        return;
      }
      if (field === "date_of_birth_partial" && typeof next === "string") {
        onChange(
          appearance === "month-year" ? next.slice(0, 7) : next.slice(0, 4),
        );
      } else onChange(next == null ? "" : String(next));
      onIssue?.();
    },
  };
  if (question.control === "date") {
    return (
      <WhoVaQuestionControls.Date
        {...controlProps}
        platform={platformServices}
        onDraftIssue={onDraftIssue}
      />
    );
  }
  if (question.control === "integer")
    return <WhoVaQuestionControls.Integer {...controlProps} />;
  if (appearance === "multiline") {
    return <MultilineInput label={label} value={value} disabled={disabled} onChange={(next) => { onChange(next); onIssue?.(); }} />;
  }
  return <WhoVaQuestionControls.Text {...controlProps} />;
}

const SEX_LABELS: Record<(typeof SEX_VALUES)[number], StringKey> = {
  male: "sexMale",
  female: "sexFemale",
  undetermined: "sexUndetermined",
  unknown: "sexUnknown",
};

function registrationTargetsFromAccess(access: AccessSummary): Target[] {
  return intakeContextFromAccess(access, "register_death").flatMap((entry) => {
    const project = access.projects.find((item) => item.project_id === entry.project_id);
    const units = (entry.org_units ?? []).filter((unit) => unit.is_active !== false && unit.selectable !== false);
    if (!project?.has_tree) return [{
      key: `${entry.project_id}:${entry.site_id}`,
      label: entry.site_name ?? entry.site_id,
      projectId: entry.project_id,
      siteId: entry.site_id,
    }];
    return units.map((unit) => ({
      key: `${entry.project_id}:${entry.site_id}:${unit.org_unit_id}`,
      label: `${entry.site_name ?? entry.site_id} · ${unit.unit_name ?? unit.org_unit_id}`,
      projectId: entry.project_id,
      siteId: entry.site_id,
      orgUnitId: unit.org_unit_id,
    }));
  });
}

export default function Register() {
  const styles = useUiStyles();
  const router = useRouter();
  const params = useLocalSearchParams<{
    userId: string;
    projectId?: string;
    clientDeathId?: string;
    deathId?: string;
    registrationCursor?: string;
    registrationSource?: string;
  }>();
  const { accounts, lockVersion, onBeforeLock, holdRefresh } = useAppState();
  useEffect(() => holdRefresh?.(), [holdRefresh]);
  const account = useStableAccount(accounts.find((a) => a.user_id === params.userId));
  const accountsRef = useRef(accounts);
  accountsRef.current = accounts;
  const [db, setDb] = useState<Db | undefined>();
  const [targets, setTargets] = useState<Target[]>([]);
  const [allTargets, setAllTargets] = useState<Target[]>([]);
  const [registerProjects, setRegisterProjects] = useState<Array<{ project_id: string; project_name: string }>>([]);
  const [registrationAccess, setRegistrationAccess] = useState<AccessSummary>();
  const [referenceData, setReferenceData] = useState<ReferenceData>();
  const [projectId, setProjectId] = useState<string | undefined>(
    params.projectId,
  );
  const [target, setTarget] = useState<Target | undefined>();
  const [fields, setFields] = useState<RegistrationFields>({
    deceased_name: "",
    deceased_sex: "",
    date_of_death: "",
  });
  const [birthMode, setBirthMode] = useState<BirthMode>("exact");
  const [errors, setErrors] = useState<Partial<Record<Field, StringKey>>>({});
  const [message, setMessage] = useState("");
  // Registration numbers: the project's cached types and, per code, the server's refusal of a value.
  const [idTypes, setIdTypes] = useState<IdentifierType[]>([]);
  const [idErrors, setIdErrors] = useState<Record<string, string>>({});
  const [idEditable, setIdEditable] = useState(true);
  const [ageConfirmationPending, setAgeConfirmationPending] = useState(false);
  const [ageConfirmationStartAfter, setAgeConfirmationStartAfter] =
    useState(false);
  const [busy, setBusy] = useState(false);
  // Informant details need a granted consent decision (docs/policy/respondent-consent-notice-draft.md, "Phone flow").
  const [consentConfig, setConsentConfig] = useState<ProjectConsentConfig | undefined>();
  const [consent, setConsent] = useState<StoredConsent | undefined>();
  const registrationId = useRef(randomUUID());
  const registrationOnly = account?.collection_access !== true;
  const editing = params.clientDeathId;
  const serverDeathId = params.deathId;
  const ownRegistrationSource = registrationOnly || params.registrationSource === "mine";
  const [serverReadOnly, setServerReadOnly] = useState(false);
  const serverUpdatedAt = useRef<string | undefined>(undefined);
  const serverBase = useRef<RegistrationFields | undefined>(undefined);
  const operationGeneration = useRef(0);
  const appState = useRef(AppState.currentState);
  const focused = useRef(false);
  // Only a new registration is kept while typing; an edit starts from its saved row.
  const persistable = !editing && !serverDeathId;
  const persistableRef = useRef(persistable);
  persistableRef.current = persistable;
  const [resumeVersion, setResumeVersion] = useState(0);
  // An edit of a saved registration is not kept while typing: leaving with typed changes asks first.
  const dirty = useRef(false);
  const [discardAsk, setDiscardAsk] = useState<(() => void) | undefined>();
  const leaveGuard = useLeaveGuard(true);
  // A lock or sign-out redirect must never be held, so only an unlocked screen asks.
  leaveGuard.holds.current = () => dirty.current && !persistableRef.current && !!account && isUnlocked(account.user_id);
  leaveGuard.handler.current = (proceed) => setDiscardAsk(() => proceed);
  const hydrated = useRef(false);
  const blurred = useRef(false);
  const inProgressDb = useRef<Db | undefined>(undefined);
  const pendingCopy = useRef<InProgressRegistration | undefined>(undefined);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  /**
   * Write the latest typed values now (or drop the copy when the form is
   * empty). Writes are chained, so a lock waits for one already in flight.
   */
  const flushing = useRef<Promise<void>>(Promise.resolve());
  const flushInProgress = useCallback(() => {
    if (copyTimer.current) clearTimeout(copyTimer.current);
    copyTimer.current = undefined;
    const copy = pendingCopy.current;
    const handle = inProgressDb.current;
    pendingCopy.current = undefined;
    if (!copy || !handle) return flushing.current;
    flushing.current = flushing.current.then(async () => {
      try {
        if (hasContent(copy.fields)) await setMeta(handle, IN_PROGRESS_KEY, copy);
        else await handle.runAsync("DELETE FROM meta WHERE key = ?", [IN_PROGRESS_KEY]);
      } catch (error) {
        console.warn(`registration copy not saved: ${error instanceof Error ? error.name : "error"}`);
      }
    });
    return flushing.current;
  }, []);

  /** Saved or discarded: forget the copy and give the next registration its own id. */
  const clearInProgress = useCallback(async (handle: Db) => {
    if (copyTimer.current) clearTimeout(copyTimer.current);
    copyTimer.current = undefined;
    pendingCopy.current = undefined;
    await flushing.current;
    await handle.runAsync("DELETE FROM meta WHERE key = ?", [IN_PROGRESS_KEY]);
    registrationId.current = randomUUID();
  }, []);

  /** Leaving the screen: keep the copy, then clear the visible fields. */
  const hideFields = useCallback(() => {
    void flushInProgress();
    hydrated.current = false;
    operationGeneration.current += 1;
    serverBase.current = undefined;
    serverUpdatedAt.current = undefined;
    setFields({ deceased_name: "", deceased_sex: "", date_of_death: "" });
    setBusy(false);
  }, [flushInProgress]);

  useEffect(() => onBeforeLock?.(flushInProgress), [onBeforeLock, flushInProgress]);

  useFocusEffect(useCallback(() => {
    focused.current = true;
    if (blurred.current && persistableRef.current) setResumeVersion((version) => version + 1);
    return () => {
      focused.current = false;
      blurred.current = true;
      hideFields();
    };
  }, [hideFields]));

  useEffect(() => {
    const subscription = AppState.addEventListener("change", (next) => {
      const previous = appState.current;
      appState.current = next;
      if (next !== "active") hideFields();
      else if (previous !== "active" && persistableRef.current) setResumeVersion((version) => version + 1);
    });
    return () => {
      operationGeneration.current += 1;
      subscription.remove();
    };
  }, [hideFields]);

  useEffect(() => {
    if (!account) return;
    operationGeneration.current += 1;
    const loadGeneration = operationGeneration.current;
    let active = true;
    setFields({ deceased_name: "", deceased_sex: "", date_of_death: "" });
    setServerReadOnly(false);
    hydrated.current = false;
    serverBase.current = undefined;
    serverUpdatedAt.current = undefined;
    void (async () => {
      try {
        const handle = await openInterviewerDb(account.user_id);
        const [referenceData, existing, access, serverExisting] = await Promise.all([
          getCachedReferenceData(handle),
          editing && !registrationOnly
            ? getRegistration(handle, editing)
            : Promise.resolve(undefined),
          getDeathRegistrationAccess(account.user_id),
          serverDeathId
            ? ownRegistrationSource
              ? getNativeRegisteredDeaths(account.user_id, true, params.registrationCursor).then((page) =>
                  page.deaths.find((death) => death.death_id === serverDeathId))
              : getNativeRegistrationCase(account.user_id, serverDeathId)
            : Promise.resolve(undefined),
        ]);
        const saved = persistable
          ? await getMeta<InProgressRegistration>(handle, IN_PROGRESS_KEY)
          : undefined;
        if (!active || loadGeneration !== operationGeneration.current) return;
        inProgressDb.current = handle;
        setDb(handle);
        setReferenceData(referenceData);
        setRegistrationAccess(access);
        if (serverDeathId && !serverExisting) {
          setMessage(t("registerLoadFailed"));
          return;
        }
        if (registrationOnly && !access) {
          setAllTargets([]);
          setTargets([]);
          setRegisterProjects([]);
          setMessage(t("registerLoadFailed"));
          return;
        }
        const registerProjects = access
          ? access.projects.filter((project) => project.actions.register_death.length > 0)
              .map(({ project_id, project_name }) => ({ project_id, project_name }))
          : (referenceData?.projects ?? [])
              .filter(({ project }) => project.sites.some((site) => ["death_register", "both"].includes(site.web_intake_mode ?? project.web_intake_mode)))
              .map(({ project }) => ({ project_id: project.project_id, project_name: project.project_name }));
        setRegisterProjects(registerProjects);
        const choices = access
          ? registrationTargetsFromAccess(access)
          : (referenceData?.projects ?? []).flatMap(({ project, units }) =>
              targetsFrom(project, units).filter((choice) => registersDeaths(project, choice.siteId)));
        setAllTargets(choices);
        const serverFields = serverExisting ? registrationFieldsFromCase(serverExisting) : undefined;
        if (serverFields) {
          const serverSource = serverExisting as unknown as Record<string, unknown>;
          serverBase.current = serverFields;
          serverUpdatedAt.current = typeof serverSource.updated_at === "string"
            ? serverSource.updated_at
            : undefined;
          const serverState = typeof serverSource.state === "string" ? serverSource.state : typeof serverSource.status === "string" ? serverSource.status : "";
          const pending = serverSource.details_pending === true || serverState === "draft_identity";
          const completed = serverSource.other_complete_interview === true || ["completed", "submitted"].includes(serverState);
          setServerReadOnly(pending || completed);
          setIdEditable(!isBadgeOnly(serverSource.identifiers as CaseIdentifier[] | undefined) || serverSource.can_edit_identifiers === true);
          if (pending || completed) setMessage(t("registerSaveFailed"));
          setFields(serverFields);
          setBirthMode(birthModeFor(serverFields));
        }
        const serverProjectId = serverExisting && typeof serverExisting.project_id === "string" ? serverExisting.project_id : undefined;
        const serverSiteId = serverExisting && typeof serverExisting.site_id === "string" ? serverExisting.site_id : undefined;
        const serverOrgUnitId = serverExisting && typeof serverExisting.org_unit_id === "string" ? serverExisting.org_unit_id : undefined;
        const restored = saved && typeof saved.clientDeathId === "string" && saved.fields ? saved : undefined;
        if (restored) {
          registrationId.current = restored.clientDeathId;
          setFields(restored.fields);
          setBirthMode(restored.birthMode ?? birthModeFor(restored.fields));
          setAgeConfirmationPending(restored.ageConfirmationPending === true);
          setAgeConfirmationStartAfter(restored.ageConfirmationStartAfter === true);
        }
        if (persistable) hydrated.current = true;
        setConsent(serverDeathId ? undefined : await getRegistrationConsent(handle, editing ?? registrationId.current));
        const nextProjectId =
          serverProjectId ??
          existing?.project_id ??
          restored?.projectId ??
          params.projectId ??
          (registerProjects.length === 1
            ? registerProjects[0].project_id
            : undefined);
        setProjectId(nextProjectId);
        const selectedChoices = choices.filter((choice) => choice.projectId === nextProjectId);
        setTargets(selectedChoices);
        if (serverExisting && serverSiteId && serverProjectId) {
          setTarget(selectedChoices.find((choice) => choice.siteId === serverSiteId && (choice.orgUnitId ?? undefined) === serverOrgUnitId) ?? {
            key: "existing-server-case",
            label: serverSiteId,
            siteId: serverSiteId,
            orgUnitId: serverOrgUnitId,
            projectId: serverProjectId,
          });
        } else if (existing) {
          if (existing.state === "needs_edit") {
            // The server refused a number: show its message under the field again.
            const refused = await getRegistrationRefusal(handle, existing.client_death_id);
            if (Object.keys(refused).length) {
              setIdErrors(refused);
              setMessage(t("serverValidation"));
            }
            const last = await sendRefusal(handle, existing.client_death_id);
            if (last?.message) setMessage(last.message);
          }
          setFields(existing.fields);
          setBirthMode(birthModeFor(existing.fields));
          setTarget(
            selectedChoices.find(
              (c) =>
                c.siteId === existing.site_id &&
                (c.orgUnitId ?? null) === existing.org_unit_id,
            ) ?? {
              key: "existing",
              label: existing.site_id,
              siteId: existing.site_id,
              orgUnitId: existing.org_unit_id ?? undefined,
              projectId: existing.project_id,
            },
          );
        } else if (restored?.siteId && selectedChoices.some((c) =>
          c.siteId === restored.siteId && (c.orgUnitId ?? null) === (restored.orgUnitId ?? null))) {
          setTarget(selectedChoices.find((c) =>
            c.siteId === restored.siteId && (c.orgUnitId ?? null) === (restored.orgUnitId ?? null)));
        } else if (selectedChoices.length === 1) {
          setTarget(selectedChoices[0]);
        } else if (!access && registrationOnly) {
          setMessage(t("registerLoadFailed"));
        }
      } catch (error) {
        if (active && loadGeneration === operationGeneration.current) {
          setMessage(error instanceof ApiError && error.status === 404 ? t("registerLoadFailed") : t("registerLoadFailed"));
        }
      }
    })();
    return () => {
      active = false;
    };
  }, [account, editing, registrationOnly, serverDeathId, ownRegistrationSource, params.registrationCursor, lockVersion, resumeVersion]);

  // Keep the typed registration in the encrypted store, debounced.
  useEffect(() => {
    if (!persistable || !db || !hydrated.current) return;
    pendingCopy.current = {
      clientDeathId: registrationId.current,
      ...(projectId ? { projectId } : {}),
      ...(target ? { siteId: target.siteId, orgUnitId: target.orgUnitId ?? null } : {}),
      fields,
      birthMode,
      ageConfirmationPending,
      ageConfirmationStartAfter,
    };
    if (copyTimer.current) clearTimeout(copyTimer.current);
    copyTimer.current = setTimeout(() => void flushInProgress(), 400);
  }, [persistable, db, projectId, target, fields, birthMode, ageConfirmationPending, ageConfirmationStartAfter, flushInProgress]);

  useEffect(() => () => {
    if (copyTimer.current) clearTimeout(copyTimer.current);
  }, []);

  // The project's types come from the encrypted cache filled with the case list; an empty cache asks once.
  useEffect(() => {
    if (!db || !account || !projectId) {
      setIdTypes([]);
      return undefined;
    }
    let active = true;
    void (async () => {
      let types: IdentifierType[] = [];
      try {
        types = await getCachedIdentifierTypes(db, projectId);
        if (!types.length) types = (await refreshIdentifierTypes(account.user_id, db, projectId)) ?? [];
      } catch {
        types = [];
      }
      if (active) setIdTypes(types);
    })();
    return () => { active = false; };
  }, [db, account?.user_id, projectId]);

  useEffect(() => {
    if (!db || !projectId) {
      setConsentConfig(undefined);
      return undefined;
    }
    let active = true;
    void getConsentConfig(db, projectId).then((config) => { if (active) setConsentConfig(config); }).catch(() => undefined);
    return () => { active = false; };
  }, [db, projectId]);

  if (!account) return <Redirect href="/" />;
  if (registrationOnly && editing) return <Redirect href="/worklist" />;
  if (!isUnlocked(account.user_id)) {
    return (
      <Redirect
        href={{ pathname: "/unlock", params: { userId: account.user_id } }}
      />
    );
  }

  const set = (name: Field) => (value: string) => {
    dirty.current = true;
    setFields((current) => ({ ...current, [name]: value }));
    setAgeConfirmationPending(false);
    setAgeConfirmationStartAfter(false);
  };

  const setIdentifier = (code: string, value: string) => {
    dirty.current = true;
    setFields((current) => ({ ...current, identifiers: { ...current.identifiers, [code]: value } }));
    setIdErrors((current) => (current[code] ? { ...current, [code]: "" } : current));
    setAgeConfirmationPending(false);
    setAgeConfirmationStartAfter(false);
  };
  const idShown = idTypes.length > 0 && (!serverDeathId || idEditable);

  // Informant details: closed until a decision is recorded; a granted one opens them, a refusal keeps them empty.
  const covered = coveredFieldsOf(consentConfig);
  const informantNames = new Set<string>(covered);
  const consentGate = registrationConsentGate(consentConfig);
  const decision = consent?.envelope.decision;
  const informantFilled = (name: string) => ((fields as unknown as Record<string, string | undefined>)[name] ?? "").trim() !== "";
  const informantEntered = serverDeathId
    ? covered.some((name) => informantFilled(name) &&
        ((fields as unknown as Record<string, string | undefined>)[name] ?? "") !== ((serverBase.current as unknown as Record<string, string | undefined> | undefined)?.[name] ?? ""))
    : covered.some(informantFilled);
  // A new registration always needs consent for informant details (the station rule); a correction to a server
  // registration only where the project requires it (the server refuses it otherwise).
  const needsConsent = informantEntered && decision !== "granted" && (!serverDeathId || consentConfig?.consent_required === true);
  const informantOpen = decision === "granted" || Boolean(serverDeathId) || (informantEntered && !consent);
  const clientDeathIdForConsent = editing ?? registrationId.current;

  async function recordConsent(envelope: import("../consent").ConsentRecordEnvelope) {
    if (!db || !account || !consentConfig) return;
    const record = storedConsent(envelope, consentConfig, account.user_id);
    if (!serverDeathId) await saveRegistrationConsent(db, clientDeathIdForConsent, record);
    setConsent(record);
    if (envelope.decision === "refused") setFields((current) => withoutCovered(current, covered));
    setMessage("");
  }

  // The stored decision stays until a new one replaces it: a queued registration still holds the informant's
  // details, and deleting it would let them upload with no decision. Saving without a new one is blocked (needsConsent).
  function changeConsent() {
    setConsent(undefined);
  }

  const setFieldIssue = (field: Field, issue?: StringKey) => {
    setErrors((current) =>
      current[field] === issue ? current : { ...current, [field]: issue },
    );
  };

  const chooseBirthMode = (next: BirthMode) => {
    dirty.current = true;
    setAgeConfirmationPending(false);
    setAgeConfirmationStartAfter(false);
    setBirthMode(next);
    setFields((current) => ({
      ...current,
      date_of_birth:
        next === "exact" && birthMode === "exact"
          ? current.date_of_birth
          : undefined,
      date_of_birth_partial:
        next === birthMode ? current.date_of_birth_partial : undefined,
      age_years: next === "exact" ? undefined : current.age_years,
    }));
    setErrors((current) => ({
      ...current,
      date_of_birth: undefined,
      date_of_birth_partial: undefined,
      age_years: undefined,
    }));
  };

  const phoneUnchanged = (name: "informant_phone" | "informant_phone_2") =>
    Boolean(serverDeathId) && (fields[name] ?? "") === (serverBase.current?.[name] ?? "");

  const renderTextField = (field: (typeof TEXT_FIELDS)[number]) => field.name === "informant_phone" ? (
    <PhoneNumbers
      key={field.name}
      values={{ informant_phone: fields.informant_phone ?? "", informant_phone_2: fields.informant_phone_2 ?? "" }}
      errors={{
        informant_phone: errors.informant_phone ? t(errors.informant_phone) : undefined,
        informant_phone_2: errors.informant_phone_2 ? t(errors.informant_phone_2) : undefined,
      }}
      disabled={serverReadOnly}
      onChange={(name, digits) => {
        set(name)(digits);
        setFieldIssue(name);
      }}
      onValidity={(name, valid) => setFieldIssue(name, valid || phoneUnchanged(name) ? undefined : "errPhone")}
    />
  ) : (
    <View key={field.name} style={{ gap: 4 }}>
      <Text style={styles.muted}>{t(field.label)}</Text>
      <NativeRegistrationFieldControl
        field={field.name}
        label={t(field.label)}
        value={fields[field.name] ?? ""}
        disabled={serverReadOnly}
        onChange={set(field.name)}
        issue={errors[field.name]}
        onIssue={(issue) => setFieldIssue(field.name, issue)}
        appearance={
          field.name === "remarks" || field.name === "address"
            ? "multiline"
            : "exact"
        }
      />
      {field.help ? <Text style={styles.muted}>{t(field.help)}</Text> : null}
      {errorFor(field.name)}
    </View>
  );

  const canStartInterview = Boolean(target && referenceData?.projects.some(({ project, units }) =>
    targetsFrom(project, units).some((choice) => choice.projectId === target.projectId &&
      choice.siteId === target.siteId && (choice.orgUnitId ?? null) === (target.orgUnitId ?? null)),
  ) && (!registrationAccess || hasInterviewRegistrationAccess(
    registrationAccess, target.projectId, target.siteId, target.orgUnitId,
  )));

  function operationIsCurrent(generation: number, userId: string): boolean {
    return generation === operationGeneration.current && focused.current && appState.current === "active" &&
      isUnlocked(userId) && accountsRef.current.some((item) => item.user_id === userId);
  }

  async function reloadServerRegistration(
    userId: string,
    deathId: string,
    isCurrent: () => boolean,
  ): Promise<void> {
    const fresh = ownRegistrationSource
      ? (await getNativeRegisteredDeaths(userId, true, params.registrationCursor)).deaths.find((row) => row.death_id === deathId)
      : await getNativeRegistrationCase(userId, deathId);
    if (!isCurrent()) return;
    if (!fresh) throw new Error("registration_unavailable");
    const nextFields = registrationFieldsFromCase(fresh);
    serverBase.current = nextFields;
    serverUpdatedAt.current = "updated_at" in fresh && typeof fresh.updated_at === "string" ? fresh.updated_at : undefined;
    setFields(nextFields);
    setBirthMode(birthModeFor(nextFields));
    const source = fresh as unknown as Record<string, unknown>;
    const state = typeof source.state === "string" ? source.state : typeof source.status === "string" ? source.status : "";
    setServerReadOnly(source.details_pending === true || source.other_complete_interview === true || ["draft_identity", "completed", "submitted"].includes(state));
    setMessage("This registration changed. Review the latest values and make your correction again.");
  }

  async function save(startAfter: boolean, confirmAge = false) {
    if (!db || !account || !target || !projectId) return;
    setMessage("");
    const found = validateRegistration(fields, localToday());
    for (const key of ["informant_phone", "informant_phone_2"] as const) if (phoneUnchanged(key)) delete found[key];
    const nextErrors = { ...found };
    if (registrationAgeInfoIssue(fields, serverDeathId ? serverBase.current : undefined)) {
      if (birthMode === "unknown") nextErrors.age_years = "errRequired";
      else nextErrors[birthMode === "exact" ? "date_of_birth" : "date_of_birth_partial"] = "errBirthOrAge";
    }
    setErrors(nextErrors);
    // Advice from the type's own rules (the server checks again); a refused number would only queue as needs_edit.
    const idIssues = idShown ? identifierIssues(idTypes, fields.identifiers ?? {}, !serverDeathId) : {};
    setIdErrors(Object.fromEntries(idTypes.filter((type) => idIssues[type.code]).map((type) => [type.code, identifierIssueText(type, idIssues[type.code])])));
    if (Object.keys(nextErrors).length > 0 || Object.keys(idIssues).length > 0) {
      setAgeConfirmationPending(false);
      setAgeConfirmationStartAfter(false);
      setMessage(t("registerFixErrors"));
      return;
    }
    if (needsConsent) {
      setMessage(t("consentNeededBeforeSave"));
      return;
    }
    if (!confirmAge && registrationNeedsAgeConfirmation(fields)) {
      setAgeConfirmationPending(true);
      setAgeConfirmationStartAfter(startAfter);
      return;
    }
    setAgeConfirmationPending(false);
    setAgeConfirmationStartAfter(false);
    if (startAfter && !canStartInterview) return;
    const clientDeathId = editing ?? registrationId.current;
    // A refusal (or no decision) never saves the informant's details.
    const registrationToSave = decision === "granted" || serverDeathId ? fields : withoutCovered(fields, covered);
    const operation = ++operationGeneration.current;
    const current = () => operationIsCurrent(operation, account.user_id);
    setBusy(true);
    try {
      if (!current()) return;
      if (serverDeathId) {
        if (serverReadOnly || !serverBase.current) return;
        const changes: RegistrationChanges = {};
        for (const field of REGISTRATION_FIELDS) {
          const nextValue = fields[field] ?? "";
          if (nextValue !== (serverBase.current[field] ?? "")) changes[field] = nextValue.trim();
        }
        const idChanges = idShown ? identifierChanges(serverBase.current.identifiers, fields.identifiers) : {};
        if (Object.keys(idChanges).length) changes.identifiers = idChanges;
        if (!Object.keys(changes).length) {
          dirty.current = false;
          router.back();
          return;
        }
        if (consent && covered.some((name) => name in changes)) changes.consent = consent.envelope;
        const corrected = await patchNativeDeathRegistration(account.user_id, serverDeathId, changes, serverUpdatedAt.current);
        if (!current()) return;
        serverBase.current = registrationFieldsFromCase(corrected);
        serverUpdatedAt.current = corrected.updated_at;
        dirty.current = false;
        router.back();
        return;
      }
      if (!canStartInterview) {
        const registered = await postNativeDeathRegistration(account.user_id, {
          project_id: projectId,
          site_id: target.siteId,
          ...(target.orgUnitId ? { org_unit_id: target.orgUnitId } : {}),
          ...cleanRegistration(registrationToSave),
          client_death_id: clientDeathId,
          ...(consent ? { consent: consent.envelope } : {}),
        });
        // Its interviews reuse the decision (as acknowledgeRegistration does for a queued registration).
        await keepRegistrationConsentForCase(db, clientDeathId, registered.death_id);
        if (persistable) {
          await clearInProgress(db);
          hydrated.current = false;
        }
        if (!current()) return;
        router.replace({
          pathname: "/worklist",
          params: {
            userId: account.user_id,
            ...(account.registered_deaths_access ? { registeredMine: "1" } : {}),
          },
        });
        return;
      }
      await saveRegistration(db, {
        project_id: projectId,
        client_death_id: clientDeathId,
        site_id: target.siteId,
        org_unit_id: target.orgUnitId ?? null,
        fields: cleanRegistration(registrationToSave),
      });
      if (persistable) {
        await clearInProgress(db);
        hydrated.current = false;
      }
      if (!current()) return;
      dirty.current = false;
      if (!startAfter) {
        router.back();
        return;
      }
      router.replace({
        pathname: "/form",
        params: {
          userId: account.user_id,
          projectId,
          siteId: target.siteId,
          ...(target.orgUnitId ? { orgUnitId: target.orgUnitId } : {}),
          draftId: randomUUID(),
          clientDeathId,
        },
      });
    } catch (error) {
      if (!current()) return;
      if (error instanceof ApiError && error.status === 409 && error.code === "death_stale" && serverDeathId) {
        try {
          await reloadServerRegistration(account.user_id, serverDeathId, current);
        } catch {
          if (current()) setMessage(t("registerLoadFailed"));
        }
      } else if (error instanceof ApiError && error.status === 409 && serverDeathId && ["case_completed", "details_pending"].includes(error.code ?? "")) {
        setServerReadOnly(true);
        setMessage(t("registerSaveFailed"));
      } else {
        const refused = identifierFieldErrors(error);
        if (Object.keys(refused).length) setIdErrors(refused);
        if (error instanceof ApiError && error.status === 422 && error.code?.startsWith("consent_")) {
          // The decision was unusable (or missing): ask again.
          setConsent(undefined);
          setMessage(t("consentNeededBeforeSave"));
        } else {
          setMessage(error instanceof ApiError && error.status === 422 ? t("serverValidation") : t("registerSaveFailed"));
        }
      }
    } finally {
      if (current()) setBusy(false);
    }
  }

  async function discard(handle: Db) {
    await handle.runAsync("DELETE FROM meta WHERE key = ?", [`consent:reg:${registrationId.current}`]);
    setConsent(undefined);
    await clearInProgress(handle);
    setFields({ deceased_name: "", deceased_sex: "", date_of_death: "" });
    setBirthMode("exact");
    setErrors({});
    setIdErrors({});
    setAgeConfirmationPending(false);
    setAgeConfirmationStartAfter(false);
    setMessage("");
  }

  const errorFor = (name: Field) =>
    errors[name] ? (
      <Text style={styles.error} accessibilityRole="alert">
        {t(errors[name]!)}
      </Text>
    ) : null;
  const chooseProject = (nextProjectId: string) => {
    setProjectId(nextProjectId);
    setTarget(undefined);
    setTargets(allTargets.filter((choice) => choice.projectId === nextProjectId));
  };

  return (
    <Screen title={t("registerDeath")}>
      {!serverDeathId && registerProjects.length > 1 ? (
        <View style={{ gap: 8 }}>
          <Text style={styles.text}>{t("chooseProject")}</Text>
          {registerProjects.map((project) => (
            <Button
              key={project.project_id}
              kind={project.project_id === projectId ? "primary" : "secondary"}
              label={project.project_name}
              onPress={() => chooseProject(project.project_id)}
            />
          ))}
        </View>
      ) : null}
      <Text style={styles.text}>{t("chooseSite")}</Text>
      {targets.length === 0 && !target ? (
        <Text style={styles.muted}>{t("noSites")}</Text>
      ) : null}
      <View style={{ gap: 8 }}>
        {editing && target ? (
          <Text style={styles.muted}>{target.label}</Text>
        ) : (
          targets.map((choice) => (
            <Button
              key={choice.key}
              kind={choice.key === target?.key ? "primary" : "secondary"}
              label={choice.label}
              onPress={() => setTarget(choice)}
            />
          ))
        )}
      </View>
      {renderTextField(TEXT_FIELDS[0])}
      {renderTextField(TEXT_FIELDS[1])}
      <Text style={styles.muted}>{t("fieldDateOfBirth")}</Text>
      <Text style={styles.muted}>{t("dobPrecision")}</Text>
      <Row>
        {(["exact", "month-year", "year", "unknown"] as const).map((mode) => {
          const labels: Record<BirthMode, StringKey> = {
            exact: "dobExact",
            "month-year": "dobMonthYear",
            year: "dobYear",
            unknown: "dobUnknown",
          };
          return (
            <Button
              key={mode}
              kind={birthMode === mode ? "primary" : "secondary"}
              label={t(labels[mode])}
              disabled={serverReadOnly}
              onPress={() => chooseBirthMode(mode)}
            />
          );
        })}
      </Row>
      {birthMode === "exact" ? (
        <View style={{ gap: 4 }}>
          <NativeRegistrationFieldControl
            field="date_of_birth"
            label={t("fieldDateOfBirth")}
            value={fields.date_of_birth ?? ""}
            disabled={serverReadOnly}
            onChange={set("date_of_birth")}
            issue={errors.date_of_birth}
            onIssue={(issue) => setFieldIssue("date_of_birth", issue)}
          />
          {errorFor("date_of_birth")}
        </View>
      ) : null}
      {birthMode === "month-year" || birthMode === "year" ? (
        <View style={{ gap: 4 }}>
          <NativeRegistrationFieldControl
            field="date_of_birth_partial"
            label={t("fieldDateOfBirth")}
            value={fields.date_of_birth_partial ?? ""}
            disabled={serverReadOnly}
            onChange={set("date_of_birth_partial")}
            issue={errors.date_of_birth_partial}
            onIssue={(issue) => setFieldIssue("date_of_birth_partial", issue)}
            appearance={birthMode}
          />
          {errorFor("date_of_birth_partial")}
        </View>
      ) : null}
      {(() => {
        const display = calculateRegistrationAge(fields);
        return display ? (
          <Text style={styles.muted}>{formatRegistrationAge(display)}</Text>
        ) : null;
      })()}
      {birthMode !== "exact" ? (
        <View style={{ gap: 4 }}>
          <Text style={styles.muted}>{t(birthMode === "unknown" ? "fieldEstimatedAgeRequired" : "fieldAge")}</Text>
          <NativeRegistrationFieldControl
            field="age_years"
            label={t(birthMode === "unknown" ? "fieldEstimatedAgeRequired" : "fieldAge")}
            value={fields.age_years ?? ""}
            disabled={serverReadOnly}
            onChange={set("age_years")}
            issue={errors.age_years}
            onIssue={(issue) => setFieldIssue("age_years", issue)}
          />
          {errorFor("age_years")}
        </View>
      ) : null}
      <Text style={styles.muted}>{t("fieldSex")}</Text>
      <Row>
        {SEX_VALUES.map((sex) => (
          <Button
            key={sex}
            kind={fields.deceased_sex === sex ? "primary" : "secondary"}
            label={t(SEX_LABELS[sex])}
            disabled={serverReadOnly}
            onPress={() => set("deceased_sex")(sex)}
          />
        ))}
      </Row>
      {errorFor("deceased_sex")}
      {TEXT_FIELDS.slice(2).filter((field) => !informantNames.has(field.name)).map(renderTextField)}
      {consent ? (
        <Row>
          <Text style={styles.muted} testID="respondent-consent-recorded">{t(decision === "granted" ? "consentRecordedGranted" : "consentRecordedRefused")}</Text>
          {!serverReadOnly ? <Button size="sm" kind="secondary" label={t("consentChange")} disabled={busy} onPress={changeConsent} /> : null}
        </Row>
      ) : consentGate.state === "ask" && !serverReadOnly && (!serverDeathId || needsConsent) ? (
        <RespondentConsentPanel
          config={consentGate.config}
          language={uiLocale()}
          clientDraftId={null}
          busy={busy}
          makeId={randomUUID}
          onDecision={(envelope) => void recordConsent(envelope)}
        />
      ) : consentGate.state === "unavailable" && !serverDeathId ? (
        <Text style={styles.muted} testID="informant-no-notice">{t("consentInformantNoNotice")}</Text>
      ) : null}
      {!informantOpen && !consent && consentGate.state === "ask" ? <Text style={styles.muted} testID="informant-closed">{t("consentInformantClosed")}</Text> : null}
      {informantOpen ? TEXT_FIELDS.slice(2).filter((field) => informantNames.has(field.name)).map(renderTextField) : null}
      {idShown ? (
        <IdentifierFields
          types={idTypes}
          values={fields.identifiers ?? {}}
          errors={idErrors}
          disabled={serverReadOnly}
          onChange={setIdentifier}
        />
      ) : null}
      {message ? (
        <Text style={styles.error} accessibilityRole="alert">
          {message}
        </Text>
      ) : null}
      {discardAsk ? (
        <ConfirmDialog
          destructive
          title={t("discardChangesTitle")}
          message={t("discardChangesMessage")}
          confirmLabel={t("discard")}
          cancelLabel={t("stay")}
          onConfirm={() => { const go = discardAsk; setDiscardAsk(undefined); go(); }}
          onCancel={() => setDiscardAsk(undefined)}
        />
      ) : null}
      {ageConfirmationPending ? (
        <View style={styles.card} accessibilityRole="alert">
          <Text style={styles.text}>{t("ageReviewConfirm")}</Text>
          <Row>
            <Button
              kind="secondary"
              label={t("cancel")}
              disabled={busy}
              onPress={() => {
                setAgeConfirmationPending(false);
                setAgeConfirmationStartAfter(false);
              }}
            />
            <Button
              loading={busy}
              disabled={busy}
              label={t("ageReviewSave")}
              onPress={() => void save(ageConfirmationStartAfter, true)}
            />
          </Row>
        </View>
      ) : null}
      <Row>
        {!serverReadOnly ? (
        <Button
          label={t("save")}
          disabled={!db || !target || busy || ageConfirmationPending}
          onPress={() => void save(false)}
        />
        ) : null}
        {!serverDeathId && !serverReadOnly && canStartInterview ? (
          <Button
            label={t("registerSaveStart")}
            disabled={!db || !target || busy || ageConfirmationPending}
            onPress={() => void save(true)}
          />
        ) : null}
        <Button
          kind="secondary"
          label={t("cancel")}
          disabled={busy}
          onPress={() => router.back()}
        />
        {persistable && db ? (
          <Button
            kind="danger"
            label={t("discard")}
            disabled={busy}
            onPress={() => Alert.alert(t("discard"), t("registrationDiscardConfirm"), [
              { text: t("cancel"), style: "cancel" },
              { text: t("discard"), style: "destructive", onPress: () => void discard(db) },
            ])}
          />
        ) : null}
      </Row>
    </Screen>
  );
}
