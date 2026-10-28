import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { Text, View } from "react-native";
import { randomUUID } from "expo-crypto";

import { guardedNavigate, useNavigationGuard } from "./navigationGuard";

import { ApiError, SUPERVISION_ROLES, getLocalStationLaunchToken, getCaseDetail, getRegisteredDeaths, hasInterviewRegistrationAccess, intakeContextFromAccess, requestClientJson, type CaseDetail, type CaseRow, type IntakeBootstrap, type RegistrationInput } from "../api";
import { INTAKE_API, registerDeath, startDraft } from "../client/api";
import { useAppState } from "../AppState";
import { localToday, registrationAgeInfoIssue, registrationNeedsAgeConfirmation, validateRegistration, type RegistrationFields } from "../cases";
import { t, uiLocale, type StringKey } from "../i18n";
import { calculateRegistrationAge } from "../registrationAgeDisplay";
import { formatRegistrationAge } from "../registrationAgeText";
import { Button, useUiStyles } from "../ui";
import { browserErrorText, WebShell } from "./common";
import { ContextualHelpBanner } from "./ContextualHelp";
import { DeathsListPanel } from "./DeathsList";
import { TRAINING_INTERVIEW_FORM_ROUTE, TRAINING_INTERVIEW_HOME, TRAINING_REPORTING_ROUTE } from "../training";
import { SupervisionPanel } from "./SupervisionPanel";
import { convertPrecision, type Precision } from "../workspace/doris/dateFieldShared";
import { LocationCapture, type GpsFix } from "./LocationCapture";
import { RegistrationFieldControl, type RegistrationDateAppearance } from "./registrationControls";
import { PhoneNumbers } from "../PhoneInput";
import { IdentifierFields, identifierIssueText } from "../IdentifierFields";
import { IdentifierFacts } from "./CaseIdentifiers";
import { RespondentConsentPanel, StationConsentPanel } from "./StationConsentPanel";
import { fetchProjectConsentConfig, INFORMANT_PII_FIELDS, type ConsentRecordEnvelope, type ProjectConsentConfig } from "../consent";
import { RefusalPanel } from "../RefusalPanel";
import {
  identifierChanges, identifierFieldErrors, identifierIssues, identifiersToSend, identifierValues, identifierWarnings,
  isBadgeOnly, loadIdentifierTypes, type CaseIdentifier, type IdentifierType,
} from "../identifiers";

const FIELD_DEFINITIONS: Array<{ key: keyof RegistrationInput; label: StringKey; help?: StringKey }> = [
  { key: "deceased_name", label: "fieldDeceasedName" },
  { key: "date_of_death", label: "fieldDateOfDeath" },
  { key: "address", label: "fieldAddress" },
  { key: "informant_name", label: "fieldInformantName" },
  { key: "informant_phone", label: "fieldInformantPhone" },
  { key: "remarks", label: "fieldRemarks", help: "remarksHelp" }
];

type DraftIssue = { code?: StringKey; message: string };

const REGISTRATION_FIELDS: Array<Exclude<keyof RegistrationInput, "identifiers">> = [
  "deceased_name", "deceased_sex", "date_of_death", "date_of_birth", "date_of_birth_partial",
  "age_years", "abha_number", "abha_address", "place_of_death", "address", "address_house_street",
  "address_village_ward", "address_landmark", "informant_name", "father_name", "mother_name",
  "informant_phone", "informant_phone_2", "remarks"
];

function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function registrationValues(value: CaseDetail | CaseRow): Partial<RegistrationInput> {
  const source = value as unknown as Record<string, unknown>;
  if (typeof source.death_id !== "string" || !source.death_id || typeof source.project_id !== "string" ||
      !source.project_id || typeof source.site_id !== "string" || !source.site_id) throw new ApiError(200, "malformed_response");
  const deceased = record(source.deceased) ? source.deceased : source;
  const address = record(source.household_address) ? source.household_address : source;
  const informant = record(source.informant) ? source.informant : source;
  const text = (item: unknown) => {
    if (item === undefined || item === null) return "";
    if (typeof item === "string") return item;
    throw new ApiError(200, "malformed_response");
  };
  const age = deceased.age_years;
  if (age !== undefined && age !== null && (typeof age !== "number" || !Number.isFinite(age))) throw new ApiError(200, "malformed_response");
  return {
    deceased_name: text(deceased.name ?? deceased.deceased_name),
    deceased_sex: text(deceased.sex ?? deceased.deceased_sex),
    date_of_death: text(deceased.date_of_death),
    date_of_birth: text(deceased.date_of_birth),
    date_of_birth_partial: text(deceased.date_of_birth_partial),
    age_years: typeof age === "number" ? String(age) : "",
    abha_number: text(source.abha_number),
    abha_address: text(source.abha_address),
    place_of_death: text(deceased.place_of_death),
    address: text(address.address),
    address_house_street: text(address.house_street ?? address.address_house_street),
    address_village_ward: text(address.village_ward ?? address.address_village_ward),
    address_landmark: text(address.landmark ?? address.address_landmark),
    informant_name: text(informant.name ?? informant.informant_name),
    informant_phone: text(informant.phone ?? informant.informant_phone),
    informant_phone_2: text(informant.phone_2 ?? informant.informant_phone_2),
    father_name: text(source.father_name),
    mother_name: text(source.mother_name),
    remarks: text(source.remarks)
  };
}

/** The stored GPS fix of a case detail or list row, or null (docs/policy/web-intake.md, "Death-site GPS location"). */
function registrationLocation(value: unknown): GpsFix | null {
  if (!record(value)) return null;
  const source = record(value.household_address) ? value.household_address : value;
  const { latitude, longitude, accuracy_m: accuracy } = source;
  if (typeof latitude !== "number" || typeof longitude !== "number" || !Number.isFinite(latitude) || !Number.isFinite(longitude)) return null;
  return { latitude, longitude, accuracy_m: typeof accuracy === "number" && Number.isFinite(accuracy) ? accuracy : null };
}

const sameFix = (a: GpsFix | null, b: GpsFix | null) =>
  a === b || (!!a && !!b && a.latitude === b.latitude && a.longitude === b.longitude && a.accuracy_m === b.accuracy_m);

type BirthMode = RegistrationDateAppearance | "unknown";

const PRECISION_OF: Record<Exclude<BirthMode, "unknown">, Precision> = { exact: "date", "month-year": "month", year: "year" };

function birthModeFor(fields: Partial<RegistrationInput>): BirthMode {
  if (fields.date_of_birth?.trim()) return "exact";
  if (/^\d{4}-\d{2}$/.test(fields.date_of_birth_partial?.trim() ?? "")) return "month-year";
  if (/^\d{4}$/.test(fields.date_of_birth_partial?.trim() ?? "")) return "year";
  if (fields.age_years !== undefined && fields.age_years !== null && String(fields.age_years).trim()) return "unknown";
  return "exact";
}

//: Pages of 50 the edit walks to find a death in the caller's own registrations.
const OWN_LIST_PAGES = 20;

/**
 * One of the caller's own registrations, with the cursor of its page, from
 * GET /intake/deaths (the reporter's full registration, unlike a list row).
 * ponytail: walks at most OWN_LIST_PAGES pages (the 1000 most recently
 * updated); an additive `death_id` filter on that endpoint would make it one read.
 */
async function findOwnRegistration(csrf: Parameters<typeof getRegisteredDeaths>[0], registeredMine: boolean, deathId: string, training = false) {
  let cursor: string | undefined;
  for (let page = 0; page < OWN_LIST_PAGES; page += 1) {
    const result = await getRegisteredDeaths(csrf, registeredMine, cursor, training);
    const row = result.deaths.find((death) => death.death_id === deathId);
    if (row) return { row, cursor };
    if (!result.next_cursor) return undefined;
    cursor = result.next_cursor;
  }
  return undefined;
}

function draftIssueFor(key: keyof RegistrationInput, message: string): DraftIssue {
  const code = key === "date_of_death" || key === "date_of_birth" || key === "date_of_birth_partial"
    ? "errDate"
    : key === "age_years"
      ? "errAge"
      : undefined;
  return { code, message };
}

export default function DeathRegistrationScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ view?: string | string[]; preset?: string | string[]; deathId?: string | string[]; registered?: string | string[] }>();
  const { bootstrap } = useAppState();
  const styles = useUiStyles();
  // Inside the Training screens (training scope) this screen lives under /training and returns to the Training list.
  const training = bootstrap?.scope === "training";
  const registerPath = training ? TRAINING_REPORTING_ROUTE : "/death-registration";
  const collectionPath = training ? TRAINING_INTERVIEW_HOME : "/collection";
  const [intake, setIntake] = useState<IntakeBootstrap>();
  const [projectId, setProjectId] = useState("");
  const [siteId, setSiteId] = useState("");
  const [orgUnitId, setOrgUnitId] = useState("");
  const [sex, setSex] = useState("");
  const [fields, setFields] = useState<Partial<RegistrationInput>>({});
  const [location, setLocation] = useState<GpsFix | null>(null);
  const locationBase = useRef<GpsFix | null>(null);
  const [birthMode, setBirthMode] = useState<BirthMode>("exact");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [validationIssues, setValidationIssues] = useState<Partial<Record<keyof RegistrationInput, StringKey>>>({});
  const [draftIssues, setDraftIssues] = useState<Partial<Record<keyof RegistrationInput, DraftIssue>>>({});
  const [ageConfirmationPending, setAgeConfirmationPending] = useState(false);
  const [editingDeathId, setEditingDeathId] = useState<string>();
  const [editingReadOnly, setEditingReadOnly] = useState(false);
  const [privateBootstrap, setPrivateBootstrap] = useState(bootstrap);
  const [isVisible, setIsVisible] = useState(true);
  // True once the user typed or chose something not yet saved; cleared when the form resets or a save lands.
  const dirtyRef = useRef(false);
  const registrationBase = useRef<Partial<RegistrationInput> | undefined>(undefined);
  const registrationUpdatedAt = useRef<string | undefined>(undefined);
  const registrationSource = useRef<"mine" | "case" | undefined>(undefined);
  const registrationSourceCursor = useRef<string | undefined>(undefined);
  const registrationGeneration = useRef(0);
  const pendingSaveOnly = useRef(false);
  const bootstrapRef = useRef(bootstrap);
  const activeRef = useRef(true);
  bootstrapRef.current = bootstrap;
  const viewParam = Array.isArray(params.view) ? params.view[0] : params.view;
  const [listMode, setListMode] = useState(viewParam === "mine");
  const [notice, setNotice] = useState("");
  // Registration numbers: the project's types, the typed values, the stored ones (edit), server refusals and duplicate warnings.
  const [idTypes, setIdTypes] = useState<IdentifierType[]>([]);
  const [idValues, setIdValues] = useState<Record<string, string>>({});
  const [idErrors, setIdErrors] = useState<Record<string, string>>({});
  const [idWarnings, setIdWarnings] = useState<Record<string, string>>({});
  const [idEditable, setIdEditable] = useState(true);
  const [idTypesFailed, setIdTypesFailed] = useState(false);
  // The stored entries of the case being edited; those of a deactivated type show read-only.
  const [idStored, setIdStored] = useState<CaseIdentifier[]>([]);
  const idBase = useRef<Record<string, string>>({});
  // What Continue and Edit do once a saved registration's duplicate warning is shown (a warning never blocks, it pauses).
  const idHeld = useRef<{ onContinue: () => void; onEdit: () => void } | undefined>(undefined);
  // The shared deaths list (docs/policy/case-list-views.md) for anyone who interviews or reports deaths.
  const hasOwnDeaths = Boolean(bootstrap?.capabilities.intake || bootstrap?.capabilities.registeredDeaths);
  // Supervisors (SUPERVISION_ROLES) get the "Needs my attention" panel here (docs/policy/case-list-views.md, "Supervision preset").
  const canSupervise = bootstrap?.access.roles.some((role) => SUPERVISION_ROLES.includes(role)) === true;
  const canList = hasOwnDeaths || canSupervise;
  const presetParam = Array.isArray(params.preset) ? params.preset[0] : params.preset;
  // A supervisor with no deaths of their own has nothing else to show, so the panel is their default.
  const supervisionView = canSupervise && (presetParam === "supervision" || !hasOwnDeaths);
  const registeredDeathCursors = useRef<{
    owner: typeof bootstrap;
    byDeath: Record<string, string | undefined>;
  }>({ owner: bootstrap, byDeath: {} });

  useEffect(() => {
    const visibilityChanged = () => {
      if (typeof document === "undefined") return;
      activeRef.current = document.visibilityState === "visible";
      setIsVisible(activeRef.current);
      if (!activeRef.current) {
        // Typed work stays in memory (policy: "Leaving a form"); the private UI is simply not rendered while hidden.
        registrationGeneration.current += 1;
        setListMode(false);
        registeredDeathCursors.current = { owner: bootstrapRef.current, byDeath: {} };
        setMessage("");
        setNotice("");
        setBusy(false);
      }
    };
    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", visibilityChanged);
      visibilityChanged();
    }
    return () => {
      activeRef.current = false;
      registrationGeneration.current += 1;
      if (typeof document !== "undefined") document.removeEventListener("visibilitychange", visibilityChanged);
    };
  }, []);

  useEffect(() => {
    let active = true;
    registrationGeneration.current += 1;
    setIntake(undefined);
    setProjectId("");
    setSiteId("");
    setOrgUnitId("");
    setFields({}); setLocation(null); setWebConsent(null);
    setSex("");
    setEditingDeathId(undefined);
    setEditingReadOnly(false);
    registrationBase.current = undefined;
    registrationUpdatedAt.current = undefined;
    registrationSource.current = undefined;
    registrationSourceCursor.current = undefined;
    registeredDeathCursors.current = { owner: bootstrap, byDeath: {} };
    setMessage("");
    setNotice("");
    setValidationIssues({});
    setDraftIssues({});
    setIdTypes([]);
    clearIdentifiers();
    setPrivateBootstrap(bootstrap);
    if (!bootstrap) return () => { active = false; };
    const contexts = intakeContextFromAccess(bootstrap.access, "register_death")
      .filter((entry) => entry.web_intake_mode === "death_register" || entry.web_intake_mode === "both");
    const scoped = { user: bootstrap.user, context: contexts };
    setIntake(scoped);
    const first = scoped.context[0];
    if (first) {
      setProjectId(first.project_id);
      setSiteId(first.site_id);
    }
    return () => {
      active = false;
    };
  }, [bootstrap]);

  useEffect(() => {
    const deathId = Array.isArray(params.deathId) ? params.deathId[0] : params.deathId;
    if (!bootstrap || !deathId || bootstrapRef.current !== bootstrap || !activeRef.current) return undefined;
    const registered = Array.isArray(params.registered) ? params.registered[0] : params.registered;
    if (registered === "mine" && bootstrap.capabilities.registeredDeaths) {
      // A death reached only as its reporter: edit it from the reporter's own registrations, never the case detail.
      const generation = ++registrationGeneration.current;
      let active = true;
      const current = () => active && generation === registrationGeneration.current && bootstrapRef.current === bootstrap && activeRef.current;
      setBusy(true);
      setMessage("");
      void findOwnRegistration(bootstrap.csrf, bootstrap.capabilities.intake, deathId, training).then((found) => {
        if (!current()) return;
        if (!found) {
          setMessage(t("serverError"));
          return;
        }
        registeredDeathCursors.current = {
          owner: bootstrap,
          byDeath: { ...registeredDeathCursors.current.byDeath, [deathId]: found.cursor },
        };
        beginEdit(found.row);
      }).catch((error: unknown) => {
        if (current()) setMessage(browserErrorText(error));
      }).finally(() => {
        if (active && generation === registrationGeneration.current) setBusy(false);
      });
      return () => { active = false; };
    }
    if (!bootstrap.capabilities.intake && bootstrap.capabilities.registeredDeaths) {
      registrationGeneration.current += 1;
      setProjectId("");
      setSiteId("");
      setOrgUnitId("");
      setFields({}); setLocation(null); setWebConsent(null);
      setSex("");
      setEditingDeathId(undefined);
      setEditingReadOnly(false);
      registrationBase.current = undefined;
      registrationUpdatedAt.current = undefined;
      registrationSource.current = undefined;
      registrationSourceCursor.current = undefined;
      setValidationIssues({});
      setDraftIssues({});
      setAgeConfirmationPending(false);
      setBusy(false);
      setMessage("");
      setListMode(true);
      router.replace({ pathname: registerPath as never, params: { view: "mine" } });
      return undefined;
    }
    const generation = ++registrationGeneration.current;
    let active = true;
    setBusy(true);
    setMessage("");
    void getCaseDetail(bootstrap.links.intakeCases, deathId, bootstrap.csrf).then(({ case: detail }) => {
      if (!active || generation !== registrationGeneration.current || bootstrapRef.current !== bootstrap || !activeRef.current) return;
      const values = registrationValues(detail);
      registrationBase.current = values;
      locationBase.current = registrationLocation(detail);
      setLocation(locationBase.current);
      registrationUpdatedAt.current = detail.updated_at;
      registrationSource.current = "case";
      registrationSourceCursor.current = undefined;
      setEditingDeathId(deathId);
      setEditingReadOnly(detail.details_pending === true || detail.other_complete_interview === true || ["draft_identity", "completed", "submitted"].includes(typeof detail.state === "string" ? detail.state : ""));
      loadIdentifiersFrom(detail);
      setFields(values);
      setSex(String(values.deceased_sex ?? ""));
      setBirthMode(birthModeFor(values));
      setProjectId(detail.project_id ?? "");
      setSiteId(detail.site_id ?? "");
      setOrgUnitId(detail.org_unit_id ?? "");
      if (detail.details_pending === true || detail.other_complete_interview === true) setMessage(t("serverValidation"));
    }).catch((error: unknown) => {
      if (active && generation === registrationGeneration.current && bootstrapRef.current === bootstrap && activeRef.current) setMessage(browserErrorText(error));
    }).finally(() => {
      if (active && generation === registrationGeneration.current) setBusy(false);
    });
    return () => { active = false; };
  }, [bootstrap, params.deathId, params.registered]);

  useEffect(() => {
    setIdTypesFailed(false);
    if (!bootstrap || !projectId) {
      setIdTypes([]);
      return undefined;
    }
    let active = true;
    loadIdentifierTypes(projectId, bootstrap.csrf).then(
      (types) => { if (active) setIdTypes(types); },
      () => { if (active) { setIdTypes([]); setIdTypesFailed(true); } },
    );
    return () => { active = false; };
  }, [bootstrap, projectId]);

  // Browser back/forward between the form and the list moves the URL first;
  // only a change follows it, so the mount keeps the deep-link redirect's choice.
  const syncedView = useRef(viewParam);
  useEffect(() => {
    if (syncedView.current === viewParam) return;
    syncedView.current = viewParam;
    setListMode(viewParam === "mine");
  }, [viewParam]);

  /** Switch between the form and the deaths list; the URL carries it so the navigation highlights the right entry. */
  function showList(on: boolean) {
    setListMode(on);
    if (on) clearIdentifiers();
    router.setParams({ view: on ? "mine" : undefined });
  }

  useEffect(() => {
    // Only once the bootstrap is known: before it loads canList is false for everyone.
    if (bootstrap && listMode && !canList) setListMode(false);
  }, [bootstrap, listMode, canList]);

  const context = useMemo(
    () => intake?.context.find((entry) => entry.project_id === projectId && entry.site_id === siteId),
    [intake, projectId, siteId]
  );
  const showRegisteredDeaths = (listMode || (canSupervise && !hasOwnDeaths)) && canList;
  const privateUiReady = Boolean(bootstrap && privateBootstrap === bootstrap && isVisible && activeRef.current);

  const ageDisplay = calculateRegistrationAge({
    date_of_death: fields.date_of_death ?? "",
    date_of_birth: fields.date_of_birth,
    date_of_birth_partial: fields.date_of_birth_partial
  });

  useEffect(() => {
    if (!Object.keys(fields).length) dirtyRef.current = false;
  }, [fields]);
  useNavigationGuard(() => dirtyRef.current, async () => false);

  function updateField(key: keyof RegistrationInput, value: string) {
    dirtyRef.current = true;
    setFields((previous) => ({ ...previous, [key]: value }));
    setValidationIssues((previous) => (previous[key] ? { ...previous, [key]: undefined } : previous));
    setDraftIssues((previous) => (previous[key] ? { ...previous, [key]: undefined } : previous));
    setAgeConfirmationPending(false);
  }

  function updateFieldIssue(key: keyof RegistrationInput, issue?: string) {
    setDraftIssues((previous) => {
      if (!issue) {
        if (!previous[key]) return previous;
        return { ...previous, [key]: undefined };
      }
      return { ...previous, [key]: draftIssueFor(key, issue) };
    });
  }

  /** Prefill the number fields from a stored case; a badge-only viewer gets empty inputs, and only if the case says they may write. */
  function loadIdentifiersFrom(source: CaseDetail | CaseRow) {
    const values = isBadgeOnly(source.identifiers) ? {} : identifierValues(source.identifiers);
    idBase.current = values;
    setIdStored(source.identifiers ?? []);
    setIdValues(values);
    setIdErrors({});
    setIdWarnings({});
    idHeld.current = undefined;
    setIdEditable(!isBadgeOnly(source.identifiers) || source.can_edit_identifiers === true);
  }

  function clearIdentifiers() {
    idBase.current = {};
    idHeld.current = undefined;
    setIdStored([]);
    setIdValues({});
    setIdErrors({});
    setIdWarnings({});
    setIdEditable(true);
  }

  function beginEdit(death: CaseDetail | CaseRow) {
    let values: Partial<RegistrationInput>;
    try {
      values = registrationValues(death);
    } catch {
      setMessage(t("serverError"));
      return;
    }
    const state = typeof death.state === "string" ? death.state : typeof death.status === "string" ? death.status : "";
    registrationBase.current = values;
    setWebConsent(null);
    locationBase.current = registrationLocation(death);
    setLocation(locationBase.current);
    registrationUpdatedAt.current = typeof death.updated_at === "string" ? death.updated_at : undefined;
    registrationSource.current = "mine";
    registrationSourceCursor.current = registeredDeathCursors.current.owner === bootstrap
      ? registeredDeathCursors.current.byDeath[death.death_id]
      : undefined;
    setEditingDeathId(death.death_id);
    setEditingReadOnly(death.details_pending === true || death.other_complete_interview === true || ["draft_identity", "completed", "submitted"].includes(state));
    loadIdentifiersFrom(death);
    setFields(values);
    setSex(String(values.deceased_sex ?? ""));
    setBirthMode(birthModeFor(values));
    setProjectId(typeof death.project_id === "string" ? death.project_id : "");
    setSiteId(typeof death.site_id === "string" ? death.site_id : "");
    setOrgUnitId(typeof death.org_unit_id === "string" ? death.org_unit_id : "");
    setValidationIssues({});
    setDraftIssues({});
    setAgeConfirmationPending(false);
    setNotice("");
    showList(false);
    setMessage(death.details_pending === true || death.other_complete_interview === true ? t("serverValidation") : "");
  }

  async function refreshEditedRegistration(
    deathId: string,
    currentBootstrap: NonNullable<typeof bootstrap>,
    isCurrent: () => boolean,
  ) {
    const fresh = registrationSource.current === "case"
      ? (await getCaseDetail(currentBootstrap.links.intakeCases, deathId, currentBootstrap.csrf)).case
      : (await getRegisteredDeaths(
          currentBootstrap.csrf,
          currentBootstrap.capabilities.intake && currentBootstrap.capabilities.registeredDeaths,
          registrationSourceCursor.current,
          currentBootstrap.scope === "training",
        )).deaths.find((row) => row.death_id === deathId);
    if (!isCurrent()) return;
    if (!fresh) throw new Error("registration_unavailable");
    const values = registrationValues(fresh);
    registrationBase.current = values;
    locationBase.current = registrationLocation(fresh);
    setLocation(locationBase.current);
    registrationUpdatedAt.current = typeof fresh.updated_at === "string" ? fresh.updated_at : undefined;
    if (registrationSource.current === "mine" && registeredDeathCursors.current.owner === currentBootstrap) {
      registeredDeathCursors.current.byDeath[deathId] = registrationSourceCursor.current;
    }
    loadIdentifiersFrom(fresh);
    setFields(values);
    setSex(String(values.deceased_sex ?? ""));
    setBirthMode(birthModeFor(values));
    setEditingReadOnly(fresh.details_pending === true || fresh.other_complete_interview === true);
    setMessage("This registration changed. Review the latest values and make your correction again.");
  }

  function chooseBirthMode(next: BirthMode) {
    setAgeConfirmationPending(false);
    setBirthMode(next);
    setFields((previous) => {
      // A finer value is cut to the coarser precision (date to month to year); a coarser one is cleared.
      const current = birthMode === "exact" ? previous.date_of_birth : previous.date_of_birth_partial;
      const kept = next === "unknown" ? "" : convertPrecision(String(current ?? "").trim(), PRECISION_OF[next]);
      return {
        ...previous,
        date_of_birth: next === "exact" ? kept || undefined : undefined,
        date_of_birth_partial: next === "month-year" || next === "year" ? kept || undefined : undefined,
        age_years: next === "unknown" ? previous.age_years : undefined
      };
    });
    setValidationIssues((previous) => ({
      ...previous,
      date_of_birth: undefined,
      date_of_birth_partial: undefined,
      age_years: undefined
    }));
    setDraftIssues((previous) => ({
      ...previous,
      date_of_birth: undefined,
      date_of_birth_partial: undefined,
      age_years: undefined
    }));
  }

  // The age-information rule (a date of birth or an estimated age), against the opened values when editing.
  function missingAgeInfoIssue(values: RegistrationFields): Partial<Record<keyof RegistrationInput, StringKey>> {
    const stored = editingDeathId ? (registrationBase.current as Partial<RegistrationFields> | undefined) : undefined;
    if (!registrationAgeInfoIssue(values, stored)) return {};
    if (birthMode === "unknown") return { age_years: "errRequired" };
    return { [birthMode === "exact" ? "date_of_birth" : "date_of_birth_partial"]: "errBirthOrAge" };
  }

  // Focus leaving the birth-date block with no age information shows the same error as submit.
  function birthBlur(event: { currentTarget?: unknown; relatedTarget?: unknown }) {
    const block = event.currentTarget as { contains?: (node: unknown) => boolean } | undefined;
    if (event.relatedTarget && block?.contains?.(event.relatedTarget)) return;
    const issues = missingAgeInfoIssue({ ...fields, deceased_name: "", deceased_sex: "", date_of_death: "" } as RegistrationFields);
    if (Object.keys(issues).length) setValidationIssues((previous) => ({ ...previous, ...issues }));
  }

  function issueMessage(key: keyof RegistrationInput): string | undefined {
    const code = validationIssues[key] ?? draftIssues[key]?.code;
    return code ? t(code) : draftIssues[key]?.message;
  }

  // An older stored number left untouched in an edit is not an error: the server validates a phone only when it changes.
  const phoneUnchanged = (key: "informant_phone" | "informant_phone_2") =>
    Boolean(editingDeathId) && String(fields[key] ?? "") === String(registrationBase.current?.[key] ?? "");

  // The station (offline) always needs a granted consent to save informant details; on an edit, only
  // for informant details changed to something non-empty.
  const [consent, setConsent] = useState<ConsentRecordEnvelope | null>(null);
  const informantNeedsConsent = Boolean(getLocalStationLaunchToken()) && INFORMANT_PII_FIELDS.some((key) => {
    const next = String(fields[key] ?? "").trim();
    return next !== "" && (!editingDeathId || next !== String(registrationBase.current?.[key] ?? "").trim());
  });
  const consentBlocked = informantNeedsConsent && !consent;

  // Web (digitva-athy, owner 2026-10-22): where the project requires respondent consent, the decision
  // comes before the informant fields: closed until granted, closed and empty after a refusal (which
  // is still recorded). On an edit, a newly entered informant field needs a granted decision. The
  // station keeps its own always-required rule above, whatever the project says.
  const station = Boolean(getLocalStationLaunchToken());
  const [consentConfig, setConsentConfig] = useState<ProjectConsentConfig | null>(null);
  const [webConsent, setWebConsent] = useState<ConsentRecordEnvelope | null>(null);
  const refusalDraftId = useRef(randomUUID());
  const [refusalAge, setRefusalAge] = useState("");
  const [refusalSex, setRefusalSex] = useState("");
  const [consentCheck, setConsentCheck] = useState(0);
  useEffect(() => {
    setWebConsent(null);
    setConsentConfig(null);
    if (station || !projectId || !bootstrap) return undefined;
    let live = true;
    void fetchProjectConsentConfig(projectId, bootstrap.csrf).then((config) => { if (live) setConsentConfig(config); });
    return () => { live = false; };
  }, [station, projectId, bootstrap, consentCheck]);
  const webConsentRequired = !station && consentConfig?.consent_required === true;
  const informantChanged = INFORMANT_PII_FIELDS.some((key) => {
    const next = String(fields[key] ?? "").trim();
    return next !== "" && (!editingDeathId || next !== String(registrationBase.current?.[key] ?? "").trim());
  });
  const webConsentNeeded = webConsentRequired && (!editingDeathId || informantChanged || webConsent !== null);
  const informantClosed = webConsentRequired && !editingDeathId && webConsent?.decision !== "granted";
  const webConsentBlocked = webConsentNeeded && (!webConsent || (webConsent.decision === "refused" && informantChanged));
  const consentToSend = informantNeedsConsent && consent ? consent : webConsentNeeded ? webConsent : null;

  function recordWebConsent(envelope: ConsentRecordEnvelope) {
    setWebConsent(envelope);
    if (envelope.decision !== "refused") return;
    setFields({}); setSex(""); setLocation(null); setIdValues({});
    dirtyRef.current = false;
  }

  const renderField = (field: (typeof FIELD_DEFINITIONS)[number]) => field.key === "informant_phone" ? (
    <PhoneNumbers
      key={field.key}
      values={{ informant_phone: fields.informant_phone ?? "", informant_phone_2: fields.informant_phone_2 ?? "" }}
      errors={{ informant_phone: issueMessage("informant_phone"), informant_phone_2: issueMessage("informant_phone_2") }}
      onChange={updateField}
      onValidity={(key, valid) => updateFieldIssue(key, valid || phoneUnchanged(key) ? undefined : t("errPhone"))}
    />
  ) : (
    <View key={field.key}>
      <Text style={styles.fieldLabel}>{t(field.label)}</Text>
      <RegistrationFieldControl
        field={field.key}
        label={t(field.label)}
        value={String(fields[field.key] ?? "")}
        onChange={(value) => updateField(field.key, value)}
        issueMessage={issueMessage(field.key)}
        onIssue={(issue) => updateFieldIssue(field.key, issue)}
      />
      {field.help ? <Text style={styles.muted}>{t(field.help)}</Text> : null}
    </View>
  );

  const idShown = idTypes.length > 0 && (!editingDeathId || idEditable);
  const idHold = Object.keys(idWarnings).length > 0;
  const idInactive = editingDeathId && idTypes.length ? idStored.filter((entry) => entry.value && !idTypes.some((type) => type.code === entry.code)) : [];

  async function submit(confirmAge = false, saveOnly = false) {
    const editing = Boolean(editingDeathId);
    if (!bootstrap || (!editing && (!intake || !context)) || editingReadOnly) return;
    if (webConsent?.decision === "refused") return;
    pendingSaveOnly.current = saveOnly;
    setMessage("");
    setNotice("");
    if (consentBlocked) {
      setMessage(t("stationConsentBlocked"));
      return;
    }
    if (webConsentBlocked) {
      setMessage(t("consentRegistrationBlocked"));
      return;
    }
    const typed = Object.fromEntries(idTypes.map((type) => [type.code, idValues[type.code]]));
    const validationFields = {
      ...fields,
      deceased_name: fields.deceased_name ?? "",
      deceased_sex: sex,
      date_of_death: fields.date_of_death ?? ""
    } as RegistrationFields;
    const validation = validateRegistration(validationFields, localToday());
    for (const key of ["informant_phone", "informant_phone_2"] as const) if (phoneUnchanged(key)) delete validation[key];
    const nextIssues: Partial<Record<keyof RegistrationInput, StringKey>> = {};
    for (const [key, issue] of Object.entries(validation)) {
      nextIssues[key as keyof RegistrationInput] = issue as StringKey;
    }
    Object.assign(nextIssues, missingAgeInfoIssue(validationFields));
    setValidationIssues(nextIssues);
    // Advice from the type's own rules; a number the rules refuse would only come back as a 422.
    const idIssues = idShown ? identifierIssues(idTypes, typed, !editing) : {};
    setIdErrors(Object.fromEntries(idTypes.filter((type) => idIssues[type.code]).map((type) => [type.code, identifierIssueText(type, idIssues[type.code])])));
    if (Object.values(nextIssues).some(Boolean) || Object.values(draftIssues).some(Boolean) || Object.keys(idIssues).length) {
      setAgeConfirmationPending(false);
      setMessage(t("registerFixErrors"));
      return;
    }
    if (!confirmAge && registrationNeedsAgeConfirmation(validationFields)) {
      setAgeConfirmationPending(true);
      return;
    }
    setAgeConfirmationPending(false);
    const operation = ++registrationGeneration.current;
    const requestBootstrap = bootstrap;
    const current = () => operation === registrationGeneration.current && activeRef.current && bootstrapRef.current === requestBootstrap;
    setBusy(true);
    try {
      if (!current()) return;
      if (editing && editingDeathId) {
        const changes: Partial<RegistrationInput> = {};
        for (const field of REGISTRATION_FIELDS) {
          const nextValue = field === "deceased_sex" ? sex : fields[field];
          const previousValue = registrationBase.current?.[field];
          if (String(nextValue ?? "") !== String(previousValue ?? "")) {
            changes[field] = String(nextValue ?? "").trim();
          }
        }
        // Absent keeps the stored fix, null clears it, a fix replaces it.
        const locationChanges = sameFix(location, locationBase.current)
          ? {}
          : { latitude: location?.latitude ?? null, longitude: location?.longitude ?? null, accuracy_m: location?.accuracy_m ?? null };
        // Only active codes: the server refuses a change to a deactivated type (a stored value of one stays as it is).
        const idChanges = idShown ? identifierChanges(Object.fromEntries(idTypes.map((type) => [type.code, idBase.current[type.code]])), typed) : {};
        if (!Object.keys(changes).length && !Object.keys(locationChanges).length && !Object.keys(idChanges).length) {
          dirtyRef.current = false;
          if (bootstrap.capabilities.registeredDeaths) showList(true);
          else router.replace(collectionPath as never);
          return;
        }
        const result = await requestClientJson<unknown>(`${INTAKE_API}/deaths/${encodeURIComponent(editingDeathId)}`, {
          method: "PATCH",
          json: { ...changes, ...(consentToSend ? { consent: consentToSend } : {}), ...locationChanges, ...(Object.keys(idChanges).length ? { identifiers: idChanges } : {}), ...(registrationUpdatedAt.current ? { if_updated_at: registrationUpdatedAt.current } : {}) },
          csrf: bootstrap.csrf
        });
        if (!current()) return;
        dirtyRef.current = false;
        if (!record(result) || !record(result.case) || result.case.death_id !== editingDeathId || typeof result.case.updated_at !== "string") {
          throw new ApiError(200, "malformed_response");
        }
        registrationUpdatedAt.current = result.case.updated_at;
        const finishEdit = () => {
          if (bootstrap.capabilities.registeredDeaths) {
            setEditingDeathId(undefined);
            setFields({}); setLocation(null); setWebConsent(null);
            setSex("");
            showList(true);
            setNotice(t("savedDeath", { name: (fields.deceased_name ?? "").trim() }));
          } else {
            router.replace({ pathname: collectionPath as never, params: { saved: "1" } });
          }
        };
        const duplicates = identifierWarnings(result);
        if (Object.keys(duplicates).length) {
          // Saved: pause on the warning. Edit stays in the form against what is now stored.
          registrationBase.current = { ...registrationBase.current, ...fields, deceased_sex: sex };
          locationBase.current = location;
          idBase.current = Object.fromEntries(Object.entries(typed).filter(([, v]) => v)) as Record<string, string>;
          idHeld.current = { onContinue: finishEdit, onEdit: () => undefined };
          setIdWarnings(duplicates);
          return;
        }
        finishEdit();
        return;
      }
      const deathsLink = `${INTAKE_API}/deaths`;
      const registration = await registerDeath(
        deathsLink,
        {
          project_id: projectId,
          site_id: siteId,
          ...(orgUnitId ? { org_unit_id: orgUnitId } : {}),
          deceased_name: (fields.deceased_name ?? "").trim(),
          deceased_sex: sex,
          date_of_death: (fields.date_of_death ?? "").trim(),
          ...Object.fromEntries(
            Object.entries(fields).filter(
              ([key, value]) =>
                !["deceased_name", "date_of_death"].includes(key) && !(key === "age_years" && birthMode !== "unknown") && typeof value === "string" && value.trim() !== ""
            )
          ),
          ...(consentToSend ? { consent: consentToSend } : {}),
          ...(location ? { latitude: location.latitude, longitude: location.longitude, accuracy_m: location.accuracy_m } : {}),
          ...(idShown && identifiersToSend(typed) ? { identifiers: identifiersToSend(typed) } : {})
        } as RegistrationInput,
        bootstrap.csrf
      );
      if (!current()) return;
      dirtyRef.current = false;
      const finishCreate = async () => {
      const mayStartInterview = !saveOnly && bootstrap.capabilities.intake &&
        hasInterviewRegistrationAccess(bootstrap.access, projectId, siteId, orgUnitId || undefined) &&
        typeof registration.case.links?.start_interview === "string";
      if (!mayStartInterview) {
        // The name stays out of the URL: the collection page says only that a registration was saved.
        if (saveOnly && bootstrap.capabilities.intake) {
          router.replace({ pathname: collectionPath as never, params: { saved: "1" } });
        } else if (bootstrap.capabilities.registeredDeaths) {
          setFields({}); setLocation(null); setWebConsent(null);
          setSex("");
          showList(true);
          setNotice(t("savedDeath", { name: (fields.deceased_name ?? "").trim() }));
        } else {
          router.replace("/workspace");
        }
        return;
      }
      const draft = await startDraft(
        bootstrap.links.intakeDrafts,
        {
          project_id: projectId,
          site_id: siteId,
          ...(orgUnitId ? { org_unit_id: orgUnitId } : {}),
          death_id: registration.case.death_id
        },
        bootstrap.csrf
      );
      if (!current()) return;
      router.replace({ pathname: training ? TRAINING_INTERVIEW_FORM_ROUTE : "/interview", params: { draftId: draft.draft.draft_id } });
      };
      const duplicates = identifierWarnings(registration);
      if (Object.keys(duplicates).length) {
        // Saved: pause on the warning. Continue goes on as after any save; Edit reopens the new case in the edit form.
        idHeld.current = {
          onContinue: () => void finishCreate().catch((caught: unknown) => { if (current()) setMessage(browserErrorText(caught)); }),
          onEdit: () => router.replace({
            pathname: registerPath as never,
            params: { deathId: registration.case.death_id, ...(bootstrap.capabilities.intake ? {} : { registered: "mine" }) },
          }),
        };
        setIdWarnings(duplicates);
        return;
      }
      await finishCreate();
    } catch (error) {
      if (!current()) return;
      if (editingDeathId && error instanceof ApiError && error.status === 409 && error.code === "death_stale") {
        try {
          await refreshEditedRegistration(editingDeathId, bootstrap, current);
        } catch {
          if (current()) setMessage(t("serverError"));
        }
      } else if (editingDeathId && error instanceof ApiError && error.status === 409 && ["case_completed", "details_pending"].includes(error.code ?? "")) {
        setEditingReadOnly(true);
        setMessage(t("serverValidation"));
      } else {
        if (error instanceof ApiError && error.status === 422 && error.code === "consent_required_for_informant") {
          setMessage(t("stationConsentBlocked"));
          return;
        }
        if (error instanceof ApiError && error.status === 422 && error.code === "consent_notice_unavailable") {
          setMessage(t("stationConsentNoNotice"));
          return;
        }
        // Web: the server requires a decision this page did not know about (the config was not
        // loaded, or the project switched consent on): load it again so the consent screen shows.
        if (!station && error instanceof ApiError && error.status === 422 && ["consent_required", "consent_conflict"].includes(error.code ?? "")) {
          setMessage(t("consentRegistrationBlocked"));
          setConsentCheck((n) => n + 1);
          return;
        }
        const refused = identifierFieldErrors(error);
        if (Object.keys(refused).length) setIdErrors(refused);
        setMessage(error instanceof ApiError && error.status === 422 ? t("serverValidation") : browserErrorText(error));
      }
    } finally {
      if (current()) setBusy(false);
    }
  }

  if (webConsent?.decision === "refused") {
    const saveRefusal = async () => {
      if (!bootstrap || !projectId || !siteId) return;
      setBusy(true);
      try {
        const receipt = await requestClientJson<{ client_draft_id?: unknown }>(`${INTAKE_API}/refusals`, { method: "POST", csrf: bootstrap.csrf,
          json: { client_draft_id: refusalDraftId.current, project_id: projectId, site_id: siteId, ...(orgUnitId ? { org_unit_id: orgUnitId } : {}),
            ...(refusalAge ? { refusal_age_group: refusalAge } : {}), ...(refusalSex ? { refusal_sex: refusalSex } : {}), consent: webConsent } });
        if (receipt.client_draft_id !== refusalDraftId.current) throw new Error("invalid_refusal_receipt");
        router.replace(collectionPath as never);
      } catch (error) { setMessage(browserErrorText(error)); } finally { setBusy(false); }
    };
    return <WebShell title={t("interviewTitle")}><RefusalPanel locale={uiLocale()} age={refusalAge} sex={refusalSex} onAge={setRefusalAge} onSex={setRefusalSex} onSave={() => void saveRefusal()} onChangeConsent={() => setWebConsent(null)} onNew={() => router.replace(collectionPath as never)} />{message ? <Text style={styles.error}>{message}</Text> : null}</WebShell>;
  }

  return (
    <WebShell title={showRegisteredDeaths ? t("reportedDeaths") : editingDeathId ? t("editRegistration") : t("registrationTitle")}>
      {privateUiReady ? <>
      <ContextualHelpBanner screen={showRegisteredDeaths ? (supervisionView ? "supervision" : "myRegisteredDeaths") : "deathRegistration"} />
      {canList && !showRegisteredDeaths ? (
        <Button
          size="sm"
          kind="secondary"
          label={t("reportedDeaths")}
          onPress={() => {
            if (busy) return;
            setMessage("");
            setNotice("");
            if (editingDeathId) {
              setEditingDeathId(undefined);
              registrationBase.current = undefined;
              registrationUpdatedAt.current = undefined;
              registrationSource.current = undefined;
              registrationSourceCursor.current = undefined;
              setFields({}); setLocation(null); setWebConsent(null);
              setSex("");
            }
            showList(true);
          }}
          disabled={busy}
        />
      ) : null}
      {notice ? <Text style={styles.text} accessibilityRole="alert">{notice}</Text> : null}
      {showRegisteredDeaths ? (
        <>
          {message ? <Text style={styles.error}>{message}</Text> : null}
          {canSupervise && hasOwnDeaths ? (
            <View style={styles.row}>
              <Button
                size="sm"
                kind={supervisionView ? "primary" : "secondary"}
                label={t("supervisionViewAttention")}
                onPress={() => router.setParams({ preset: "supervision" })}
              />
              <Button
                size="sm"
                kind={supervisionView ? "secondary" : "primary"}
                label={t("supervisionViewAll")}
                onPress={() => router.setParams({ preset: undefined })}
              />
            </View>
          ) : null}
          {supervisionView ? (
            <SupervisionPanel />
          ) : (
            <DeathsListPanel
              headerAction={intake?.context.length ? (
                <Button label={t("registerDeath")} onPress={() => { setMessage(""); setNotice(""); showList(false); }} />
              ) : null}
            />
          )}
        </>
      ) : editingReadOnly ? (
        <>
          <Text style={styles.error} accessibilityRole="alert">{message || t("serverValidation")}</Text>
          <Button kind="secondary" label={t("cancel")} onPress={() => {
            if (bootstrap?.capabilities.registeredDeaths) showList(true);
            else router.back();
          }} />
        </>
      ) : intake?.context.length || editingDeathId ? (
        <>
          {editingDeathId ? (
            <Text style={styles.muted}>{/^sites_in_project_/i.test(siteId) ? projectId : `${projectId} · ${siteId}`}</Text>
          ) : (
            <>
              <Text style={styles.fieldLabel}>{t("chooseSite")}</Text>
              <View style={styles.row} accessibilityRole="radiogroup">
                {intake?.context.map((entry) => {
                  const rawSite = entry.site_name ?? entry.site_id;
                  const sitePart = /^sites_in_project_/i.test(rawSite) || /^sites_in_project_/i.test(entry.site_id) ? "" : ` · ${rawSite}`;
                  return (
                    <Button
                      key={`${entry.project_id}:${entry.site_id}`}
                      kind={entry.project_id === projectId && entry.site_id === siteId ? "primary" : "secondary"}
                      label={`${entry.project_name ?? entry.project_id}${sitePart}`}
                      onPress={() => {
                        setProjectId(entry.project_id);
                        setSiteId(entry.site_id);
                        setOrgUnitId("");
                      }}
                    />
                  );
                })}
              </View>
            </>
          )}
          {!editingDeathId && context?.org_units?.filter((unit) => unit.selectable !== false).length ? (
            <View>
              <Text style={styles.fieldLabel}>{t("chooseUnit")}</Text>
              <View style={styles.row} accessibilityRole="radiogroup">
                {context.org_units.filter((unit) => unit.is_active !== false && unit.selectable !== false).map((unit) => (
                  <Button
                    key={unit.org_unit_id}
                    kind={unit.org_unit_id === orgUnitId ? "primary" : "secondary"}
                    label={unit.unit_name ?? unit.unit_code ?? unit.org_unit_id}
                    onPress={() => setOrgUnitId(unit.org_unit_id)}
                  />
                ))}
              </View>
            </View>
          ) : null}
          {renderField(FIELD_DEFINITIONS[0])}
          {renderField(FIELD_DEFINITIONS[1])}
          <View onBlur={birthBlur}>
          <Text style={styles.fieldLabel}>{t("fieldDateOfBirth")}</Text>
          <Text style={styles.muted}>{t("dobPrecision")}</Text>
          <View style={styles.row} accessibilityRole="radiogroup">
            {(
              [
                ["exact", "dobExact"],
                ["month-year", "dobMonthYear"],
                ["year", "dobYear"],
                ["unknown", "dobUnknown"]
              ] as const
            ).map(([mode, label]) => (
              <Button
                key={mode}
                kind={birthMode === mode ? "primary" : "secondary"}
                label={t(label)}
                onPress={() => chooseBirthMode(mode)}
              />
            ))}
          </View>
          {birthMode === "exact" ? (
            <RegistrationFieldControl
              field="date_of_birth"
              label={t("fieldDateOfBirth")}
              value={String(fields.date_of_birth ?? "")}
              onChange={(value) => updateField("date_of_birth", value)}
              issueMessage={issueMessage("date_of_birth")}
              onIssue={(issue) => updateFieldIssue("date_of_birth", issue)}
              dateAppearance="exact"
            />
          ) : null}
          {birthMode === "month-year" || birthMode === "year" ? (
            <RegistrationFieldControl
              field="date_of_birth_partial"
              label={t("fieldDateOfBirth")}
              value={String(fields.date_of_birth_partial ?? "")}
              onChange={(value) => updateField("date_of_birth_partial", value)}
              issueMessage={issueMessage("date_of_birth_partial")}
              onIssue={(issue) => updateFieldIssue("date_of_birth_partial", issue)}
              dateAppearance={birthMode}
            />
          ) : null}
          <View>
            <Text style={styles.fieldLabel}>{t(birthMode === "unknown" ? "fieldEstimatedAgeRequired" : "fieldEstimatedAge")}</Text>
            {birthMode === "unknown" ? (
              <RegistrationFieldControl
                field="age_years"
                label={t("fieldEstimatedAgeRequired")}
                value={String(fields.age_years ?? "")}
                onChange={(value) => updateField("age_years", value)}
                issueMessage={issueMessage("age_years")}
                onIssue={(issue) => updateFieldIssue("age_years", issue)}
              />
            ) : ageDisplay ? (
              <Text style={styles.muted}>{formatRegistrationAge(ageDisplay)}</Text>
            ) : !fields.date_of_death?.trim() ? (
              <Text style={styles.muted}>{t("ageNeedsDeathDate")}</Text>
            ) : null}
          </View>
          </View>
          <Text style={styles.fieldLabel}>{t("fieldSex")}</Text>
          <View style={styles.row} accessibilityRole="radiogroup">
            {(["male", "female", "undetermined", "unknown"] as const).map((value) => (
              <Button
                key={value}
                kind={sex === value ? "primary" : "secondary"}
                label={t(`sex${value[0].toUpperCase()}${value.slice(1)}` as "sexMale")}
                onPress={() => {
                  dirtyRef.current = true;
                  setSex(value);
                  setValidationIssues((previous) => ({ ...previous, deceased_sex: undefined }));
                  setAgeConfirmationPending(false);
                }}
              />
            ))}
          </View>
          {issueMessage("deceased_sex") ? (
            <Text style={styles.error} accessibilityRole="alert">{issueMessage("deceased_sex")}</Text>
          ) : null}
          {webConsentNeeded && !webConsent ? (
            <RespondentConsentPanel config={consentConfig} language={uiLocale()} clientDraftId={null} busy={busy} onDecision={recordWebConsent} />
          ) : null}
          {webConsentNeeded && webConsent ? (
            <View style={styles.row} testID="respondent-consent-recorded">
              <Text style={styles.muted}>{t(webConsent.decision === "granted" ? "consentRecordedGranted" : "consentRecordedRefused")}</Text>
              <Button size="sm" kind="secondary" label={t("consentChange")} disabled={busy} onPress={() => setWebConsent(null)} />
            </View>
          ) : null}
          {informantClosed && !webConsent ? <Text style={styles.muted} testID="informant-closed">{t("consentInformantClosed")}</Text> : null}
          {FIELD_DEFINITIONS.slice(2).map((field) => {
            const closed = informantClosed && (INFORMANT_PII_FIELDS as readonly string[]).includes(field.key);
            if (field.key === "address") return (
              <View key={field.key}>
                {closed ? null : renderField(field)}
                <LocationCapture value={location} onChange={(fix) => { dirtyRef.current = true; setLocation(fix); }} />
              </View>
            );
            return closed ? null : renderField(field);
          })}
          {informantNeedsConsent && bootstrap ? (
            <StationConsentPanel projectId={projectId} csrf={bootstrap.csrf} onChange={setConsent} />
          ) : null}
          {informantNeedsConsent && !consent ? <Text style={styles.error} accessibilityRole="alert" testID="station-consent-blocked">{t("stationConsentBlocked")}</Text> : null}
          {idShown ? (
            <IdentifierFields
              types={idTypes}
              values={idValues}
              errors={idErrors}
              warnings={idWarnings}
              disabled={busy}
              onChange={(code, value) => {
                dirtyRef.current = true;
                setIdValues((previous) => ({ ...previous, [code]: value }));
                setIdErrors((previous) => (previous[code] ? { ...previous, [code]: "" } : previous));
                setAgeConfirmationPending(false);
              }}
              onContinue={(code) => {
                const rest = { ...idWarnings };
                delete rest[code];
                setIdWarnings(rest);
                if (!Object.keys(rest).length) {
                  const held = idHeld.current;
                  idHeld.current = undefined;
                  held?.onContinue();
                }
              }}
              onEdit={() => {
                const held = idHeld.current;
                idHeld.current = undefined;
                setIdWarnings({});
                held?.onEdit();
              }}
            />
          ) : null}
          {idTypesFailed ? <Text style={styles.error} accessibilityRole="alert" testID="identifier-types-error">{t("idTypesLoadFailed")}</Text> : null}
          {idInactive.length ? (
            <View style={{ gap: 4 }} testID="identifier-inactive">
              <IdentifierFacts identifiers={idInactive} variant="detail" />
              <Text style={styles.muted}>{t("idInactiveNote")}</Text>
            </View>
          ) : null}
          {message ? <Text style={styles.error} accessibilityRole="alert">{message}</Text> : null}
          {ageConfirmationPending ? (
            <View style={styles.card} accessibilityRole="alert">
              <Text style={styles.text}>{t("ageReviewConfirm")}</Text>
              <View style={styles.row}>
                <Button kind="secondary" label={t("cancel")} onPress={() => setAgeConfirmationPending(false)} />
                <Button loading={busy} disabled={busy} label={t("ageReviewSave")} onPress={() => void submit(true, pendingSaveOnly.current)} />
              </View>
            </View>
          ) : null}
          <Button loading={busy} disabled={busy || ageConfirmationPending || idHold || consentBlocked || webConsentBlocked} label={t(editingDeathId ? "save" : "registerSaveStart")} onPress={() => void submit(false, false)} />
          {!editingDeathId && bootstrap?.capabilities.intake ? (
            <Button kind="secondary" loading={busy} disabled={busy || ageConfirmationPending || idHold || consentBlocked || webConsentBlocked} label={t("save")} onPress={() => void submit(false, true)} />
          ) : null}
          <Button kind="secondary" label={t("cancel")} onPress={() => guardedNavigate(() => {
            if (editingDeathId && bootstrap?.capabilities.registeredDeaths) {
              setEditingDeathId(undefined);
              setFields({}); setLocation(null); setWebConsent(null);
              setSex("");
              showList(true);
            } else router.back();
          })} />
        </>
      ) : (
        <Text style={styles.muted}>{message || t("noSites")}</Text>
      )}
      </> : null}
    </WebShell>
  );
}
