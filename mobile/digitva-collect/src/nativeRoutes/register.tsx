/**
 * Register a death with the web form's validation. Interviewers may save it
 * offline and start its questionnaire; reporter-only targets post online.
 */
import { randomUUID } from "expo-crypto";
import { Redirect, useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { AppState, Text, TextInput, View } from "react-native";
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
  localToday,
  MAX_REGISTRATION_AGE,
  registrationNeedsAgeConfirmation,
  saveRegistration,
  SEX_VALUES,
  validateRegistration,
  type RegistrationFields,
} from "../cases";
import { type Db } from "../drafts";
import { t, uiLocale, type StringKey } from "../i18n";
import { isUnlocked, openInterviewerDb } from "../interviewerDb";
import { platformServices } from "../platform";
import { calculateRegistrationAge } from "../registrationAgeDisplay";
import { formatRegistrationAge } from "../registrationAgeText";
import {
  getCachedReferenceData,
  registersDeaths,
  targetsFrom,
  type ProjectSettings,
  type ReferenceData,
  type Target,
} from "../sync";
import { Button, Row, Screen, useUiStyles } from "../ui";

type Field = keyof RegistrationFields;
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
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

/** Text fields in the web form's order, with their label and keyboard. */
const TEXT_FIELDS: Array<{
  name: Field;
  label: StringKey;
  keyboard?: "numeric" | "phone-pad";
  help?: StringKey;
}> = [
  { name: "deceased_name", label: "fieldDeceasedName" },
  { name: "date_of_death", label: "fieldDateOfDeath" },
  { name: "address", label: "fieldAddress" },
  { name: "informant_name", label: "fieldInformantName" },
  {
    name: "informant_phone",
    label: "fieldInformantPhone",
    keyboard: "phone-pad",
    help: "phoneHelp",
  },
  { name: "abha_number", label: "fieldAbhaNumber" },
  { name: "abha_address", label: "fieldAbhaAddress" },
  { name: "place_of_death", label: "fieldPlaceOfDeath" },
  { name: "address_house_street", label: "fieldHouseStreet" },
  { name: "address_village_ward", label: "fieldVillageWard" },
  { name: "address_landmark", label: "fieldLandmark" },
  { name: "father_name", label: "fieldFatherName" },
  { name: "mother_name", label: "fieldMotherName" },
  {
    name: "informant_phone_2",
    label: "fieldInformantPhone2",
    keyboard: "phone-pad",
  },
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
  const { accounts, lockVersion } = useAppState();
  const account = accounts.find((a) => a.user_id === params.userId);
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
  const [ageConfirmationPending, setAgeConfirmationPending] = useState(false);
  const [ageConfirmationStartAfter, setAgeConfirmationStartAfter] =
    useState(false);
  const [busy, setBusy] = useState(false);
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

  useFocusEffect(useCallback(() => {
    focused.current = true;
    return () => {
      focused.current = false;
      operationGeneration.current += 1;
      serverBase.current = undefined;
      serverUpdatedAt.current = undefined;
      setFields({ deceased_name: "", deceased_sex: "", date_of_death: "" });
      setBusy(false);
    };
  }, []));

  useEffect(() => {
    const subscription = AppState.addEventListener("change", (next) => {
      appState.current = next;
      if (next !== "active") {
        operationGeneration.current += 1;
        serverBase.current = undefined;
        serverUpdatedAt.current = undefined;
        setFields({ deceased_name: "", deceased_sex: "", date_of_death: "" });
        setBusy(false);
      }
    });
    return () => {
      operationGeneration.current += 1;
      subscription.remove();
    };
  }, []);

  useEffect(() => {
    if (!account) return;
    operationGeneration.current += 1;
    const loadGeneration = operationGeneration.current;
    let active = true;
    setFields({ deceased_name: "", deceased_sex: "", date_of_death: "" });
    setServerReadOnly(false);
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
        if (!active || loadGeneration !== operationGeneration.current) return;
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
          if (pending || completed) setMessage(t("registerSaveFailed"));
          setFields(serverFields);
          setBirthMode(birthModeFor(serverFields));
        }
        const serverProjectId = serverExisting && typeof serverExisting.project_id === "string" ? serverExisting.project_id : undefined;
        const serverSiteId = serverExisting && typeof serverExisting.site_id === "string" ? serverExisting.site_id : undefined;
        const serverOrgUnitId = serverExisting && typeof serverExisting.org_unit_id === "string" ? serverExisting.org_unit_id : undefined;
        const nextProjectId =
          serverProjectId ??
          existing?.project_id ??
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
  }, [account, editing, registrationOnly, serverDeathId, ownRegistrationSource, params.registrationCursor, lockVersion]);

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
    setFields((current) => ({ ...current, [name]: value }));
    setAgeConfirmationPending(false);
    setAgeConfirmationStartAfter(false);
  };

  const setFieldIssue = (field: Field, issue?: StringKey) => {
    setErrors((current) =>
      current[field] === issue ? current : { ...current, [field]: issue },
    );
  };

  const chooseBirthMode = (next: BirthMode) => {
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

  const renderTextField = (field: (typeof TEXT_FIELDS)[number]) => (
    <View key={field.name} style={{ gap: 4 }}>
      <Text style={styles.muted}>{t(field.label)}</Text>
      {field.name === "informant_phone" ||
      field.name === "informant_phone_2" ? (
        <TextInput
          accessibilityLabel={t(field.label)}
          autoCorrect={false}
          inputMode="tel"
          keyboardType="phone-pad"
          style={styles.input}
          editable={!serverReadOnly}
          value={fields[field.name] ?? ""}
          onChangeText={(value) => {
            set(field.name)(value);
            setFieldIssue(field.name);
          }}
        />
      ) : (
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
      )}
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
    const selectedBirthField = requiredBirthField(birthMode, fields);
    const nextErrors = { ...found };
    if (selectedBirthField) nextErrors[selectedBirthField] = "errRequired";
    if (birthMode === "unknown" && !fields.age_years?.trim()) nextErrors.age_years = "errRequired";
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) {
      setAgeConfirmationPending(false);
      setAgeConfirmationStartAfter(false);
      setMessage(t("registerFixErrors"));
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
        if (!Object.keys(changes).length) {
          router.back();
          return;
        }
        const corrected = await patchNativeDeathRegistration(account.user_id, serverDeathId, changes, serverUpdatedAt.current);
        if (!current()) return;
        serverBase.current = registrationFieldsFromCase(corrected);
        serverUpdatedAt.current = corrected.updated_at;
        router.back();
        return;
      }
      if (!canStartInterview) {
        await postNativeDeathRegistration(account.user_id, {
          project_id: projectId,
          site_id: target.siteId,
          ...(target.orgUnitId ? { org_unit_id: target.orgUnitId } : {}),
          ...cleanRegistration(fields),
          client_death_id: clientDeathId,
        });
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
        fields: cleanRegistration(fields),
      });
      if (!current()) return;
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
        setMessage(error instanceof ApiError && error.status === 422 ? t("serverValidation") : t("registerSaveFailed"));
      }
    } finally {
      if (current()) setBusy(false);
    }
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
          <Text style={styles.muted}>{t("fieldAge")}</Text>
          <NativeRegistrationFieldControl
            field="age_years"
            label={t("fieldAge")}
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
      {renderTextField(TEXT_FIELDS[1])}
      {TEXT_FIELDS.slice(2).map(renderTextField)}
      {message ? (
        <Text style={styles.error} accessibilityRole="alert">
          {message}
        </Text>
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
      </Row>
    </Screen>
  );
}
