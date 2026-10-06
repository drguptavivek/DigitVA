import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Text, View } from "react-native";

import { ApiError, getCaseDetail, getRegisteredDeaths, hasInterviewRegistrationAccess, intakeContextFromAccess, requestClientJson, type CaseDetail, type CaseRow, type IntakeBootstrap, type RegistrationInput } from "../api";
import { INTAKE_API, registerDeath, startDraft } from "../client/api";
import { useAppState } from "../AppState";
import { localToday, registrationNeedsAgeConfirmation, validateRegistration, type RegistrationFields } from "../cases";
import { t, type StringKey } from "../i18n";
import { calculateRegistrationAge } from "../registrationAgeDisplay";
import { formatRegistrationAge } from "../registrationAgeText";
import { Button, useUiStyles } from "../ui";
import { browserErrorText, WebShell } from "./common";
import { RegistrationFieldControl, type RegistrationDateAppearance } from "./registrationControls";

const FIELD_DEFINITIONS: Array<{ key: keyof RegistrationInput; label: StringKey; help?: StringKey }> = [
  { key: "deceased_name", label: "fieldDeceasedName" },
  { key: "date_of_death", label: "fieldDateOfDeath" },
  { key: "address", label: "fieldAddress" },
  { key: "informant_name", label: "fieldInformantName" },
  { key: "informant_phone", label: "fieldInformantPhone" },
  { key: "remarks", label: "fieldRemarks", help: "remarksHelp" }
];

type DraftIssue = { code?: StringKey; message: string };

const REGISTRATION_FIELDS: Array<keyof RegistrationInput> = [
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

type BirthMode = RegistrationDateAppearance | "unknown";

function birthModeFor(fields: Partial<RegistrationInput>): BirthMode {
  if (fields.date_of_birth?.trim()) return "exact";
  if (/^\d{4}-\d{2}$/.test(fields.date_of_birth_partial?.trim() ?? "")) return "month-year";
  if (/^\d{4}$/.test(fields.date_of_birth_partial?.trim() ?? "")) return "year";
  if (fields.age_years !== undefined && fields.age_years !== null && String(fields.age_years).trim()) return "unknown";
  return "exact";
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
  const params = useLocalSearchParams<{ view?: string | string[]; deathId?: string | string[] }>();
  const { bootstrap } = useAppState();
  const styles = useUiStyles();
  const [intake, setIntake] = useState<IntakeBootstrap>();
  const [projectId, setProjectId] = useState("");
  const [siteId, setSiteId] = useState("");
  const [orgUnitId, setOrgUnitId] = useState("");
  const [sex, setSex] = useState("");
  const [fields, setFields] = useState<Partial<RegistrationInput>>({});
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
  const registrationBase = useRef<Partial<RegistrationInput> | undefined>(undefined);
  const registrationUpdatedAt = useRef<string | undefined>(undefined);
  const registrationSource = useRef<"mine" | "case" | undefined>(undefined);
  const registrationSourceCursor = useRef<string | undefined>(undefined);
  const registrationGeneration = useRef(0);
  const bootstrapRef = useRef(bootstrap);
  const activeRef = useRef(true);
  bootstrapRef.current = bootstrap;
  const [listMode, setListMode] = useState(params.view === "mine");
  const [registeredDeaths, setRegisteredDeaths] = useState<CaseRow[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [listBusy, setListBusy] = useState(false);
  const listGeneration = useRef(0);
  const registeredDeathCursors = useRef<{
    owner: typeof bootstrap;
    byDeath: Record<string, string | undefined>;
  }>({ owner: bootstrap, byDeath: {} });

  const loadRegisteredDeaths = useCallback(async (cursor?: string | null) => {
    if (!bootstrap) return;
    const requestBootstrap = bootstrap;
    const generation = ++listGeneration.current;
    const current = () => generation === listGeneration.current && bootstrapRef.current === requestBootstrap && activeRef.current;
    if (registeredDeathCursors.current.owner !== requestBootstrap || !cursor) {
      registeredDeathCursors.current = { owner: requestBootstrap, byDeath: {} };
    }
    setListBusy(true);
    setMessage("");
    try {
      const page = await getRegisteredDeaths(requestBootstrap.csrf, requestBootstrap.capabilities.intake && requestBootstrap.capabilities.registeredDeaths, cursor);
      if (!current()) return;
      registeredDeathCursors.current = {
        owner: requestBootstrap,
        byDeath: {
          ...registeredDeathCursors.current.byDeath,
          ...Object.fromEntries(page.deaths.map((death) => [death.death_id, cursor ?? undefined]))
        }
      };
      setRegisteredDeaths((rows) => cursor ? [...rows, ...page.deaths] : page.deaths);
      setNextCursor(page.next_cursor);
    } catch (error) {
      if (current()) setMessage(browserErrorText(error));
    } finally {
      if (current()) setListBusy(false);
    }
  }, [bootstrap]);

  useEffect(() => {
    const visibilityChanged = () => {
      if (typeof document === "undefined") return;
      activeRef.current = document.visibilityState === "visible";
      setIsVisible(activeRef.current);
      if (!activeRef.current) {
        registrationGeneration.current += 1;
        listGeneration.current += 1;
        setFields({});
        setSex("");
        setRegisteredDeaths([]);
        setNextCursor(null);
        setListMode(false);
        setEditingDeathId(undefined);
        registrationBase.current = undefined;
        registrationUpdatedAt.current = undefined;
        registrationSource.current = undefined;
        registrationSourceCursor.current = undefined;
        registeredDeathCursors.current = { owner: bootstrapRef.current, byDeath: {} };
        setListBusy(false);
        setMessage("");
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
      listGeneration.current += 1;
      if (typeof document !== "undefined") document.removeEventListener("visibilitychange", visibilityChanged);
    };
  }, []);

  useEffect(() => {
    let active = true;
    registrationGeneration.current += 1;
    listGeneration.current += 1;
    setRegisteredDeaths([]);
    setNextCursor(null);
    setIntake(undefined);
    setProjectId("");
    setSiteId("");
    setOrgUnitId("");
    setFields({});
    setSex("");
    setEditingDeathId(undefined);
    setEditingReadOnly(false);
    registrationBase.current = undefined;
    registrationUpdatedAt.current = undefined;
    registrationSource.current = undefined;
    registrationSourceCursor.current = undefined;
    registeredDeathCursors.current = { owner: bootstrap, byDeath: {} };
    setListBusy(false);
    setMessage("");
    setValidationIssues({});
    setDraftIssues({});
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
    if (!bootstrap.capabilities.intake && bootstrap.capabilities.registeredDeaths) {
      registrationGeneration.current += 1;
      listGeneration.current += 1;
      setProjectId("");
      setSiteId("");
      setOrgUnitId("");
      setFields({});
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
      setRegisteredDeaths([]);
      setNextCursor(null);
      setListBusy(false);
      setBusy(false);
      setMessage("");
      setListMode(true);
      router.replace({ pathname: "/death-registration", params: { view: "mine" } });
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
      registrationUpdatedAt.current = detail.updated_at;
      registrationSource.current = "case";
      registrationSourceCursor.current = undefined;
      setEditingDeathId(deathId);
      setEditingReadOnly(detail.details_pending === true || detail.other_complete_interview === true || ["draft_identity", "completed", "submitted"].includes(typeof detail.state === "string" ? detail.state : ""));
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
  }, [bootstrap, params.deathId]);

  useEffect(() => {
    if (listMode && bootstrap?.capabilities.registeredDeaths) void loadRegisteredDeaths();
    else if (listMode) setListMode(false);
    return () => { listGeneration.current += 1; };
  }, [listMode, loadRegisteredDeaths]);

  const context = useMemo(
    () => intake?.context.find((entry) => entry.project_id === projectId && entry.site_id === siteId),
    [intake, projectId, siteId]
  );
  const showRegisteredDeaths = listMode && Boolean(bootstrap?.capabilities.registeredDeaths);
  const privateUiReady = Boolean(bootstrap && privateBootstrap === bootstrap && isVisible && activeRef.current);

  const ageDisplay = calculateRegistrationAge({
    date_of_death: fields.date_of_death ?? "",
    date_of_birth: fields.date_of_birth,
    date_of_birth_partial: fields.date_of_birth_partial
  });

  function updateField(key: keyof RegistrationInput, value: string) {
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
    registrationUpdatedAt.current = typeof death.updated_at === "string" ? death.updated_at : undefined;
    registrationSource.current = "mine";
    registrationSourceCursor.current = registeredDeathCursors.current.owner === bootstrap
      ? registeredDeathCursors.current.byDeath[death.death_id]
      : undefined;
    setEditingDeathId(death.death_id);
    setEditingReadOnly(death.details_pending === true || death.other_complete_interview === true || ["draft_identity", "completed", "submitted"].includes(state));
    setFields(values);
    setSex(String(values.deceased_sex ?? ""));
    setBirthMode(birthModeFor(values));
    setProjectId(typeof death.project_id === "string" ? death.project_id : "");
    setSiteId(typeof death.site_id === "string" ? death.site_id : "");
    setOrgUnitId(typeof death.org_unit_id === "string" ? death.org_unit_id : "");
    setValidationIssues({});
    setDraftIssues({});
    setAgeConfirmationPending(false);
    setListMode(false);
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
          registrationSourceCursor.current
        )).deaths.find((row) => row.death_id === deathId);
    if (!isCurrent()) return;
    if (!fresh) throw new Error("registration_unavailable");
    const values = registrationValues(fresh);
    registrationBase.current = values;
    registrationUpdatedAt.current = typeof fresh.updated_at === "string" ? fresh.updated_at : undefined;
    if (registrationSource.current === "mine" && registeredDeathCursors.current.owner === currentBootstrap) {
      registeredDeathCursors.current.byDeath[deathId] = registrationSourceCursor.current;
    }
    setFields(values);
    setSex(String(values.deceased_sex ?? ""));
    setBirthMode(birthModeFor(values));
    setEditingReadOnly(fresh.details_pending === true || fresh.other_complete_interview === true);
    setMessage("This registration changed. Review the latest values and make your correction again.");
  }

  function chooseBirthMode(next: BirthMode) {
    setAgeConfirmationPending(false);
    setBirthMode(next);
    setFields((previous) => ({
      ...previous,
      date_of_birth: next === "exact" && birthMode === "exact" ? previous.date_of_birth : undefined,
      date_of_birth_partial: next === birthMode ? previous.date_of_birth_partial : undefined,
      age_years: next === "exact" ? undefined : previous.age_years
    }));
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

  function issueMessage(key: keyof RegistrationInput): string | undefined {
    const code = validationIssues[key] ?? draftIssues[key]?.code;
    return code ? t(code) : draftIssues[key]?.message;
  }

  const renderField = (field: (typeof FIELD_DEFINITIONS)[number]) => (
    <View key={field.key}>
      <Text style={styles.muted}>{t(field.label)}</Text>
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

  async function submit(confirmAge = false) {
    const editing = Boolean(editingDeathId);
    if (!bootstrap || (!editing && (!intake || !context)) || editingReadOnly) return;
    setMessage("");
    const validationFields = {
      ...fields,
      deceased_name: fields.deceased_name ?? "",
      deceased_sex: sex,
      date_of_death: fields.date_of_death ?? ""
    } as RegistrationFields;
    const validation = validateRegistration(validationFields, localToday());
    const nextIssues: Partial<Record<keyof RegistrationInput, StringKey>> = {};
    for (const [key, issue] of Object.entries(validation)) {
      nextIssues[key as keyof RegistrationInput] = issue as StringKey;
    }
    const birthField = birthMode === "exact" ? "date_of_birth" : "date_of_birth_partial";
    const birthValue = validationFields[birthField];
    if (birthMode !== "unknown" && !birthValue?.trim()) nextIssues[birthField] = "errRequired";
    if (birthMode === "unknown" && !validationFields.age_years?.trim()) nextIssues.age_years = "errRequired";
    setValidationIssues(nextIssues);
    if (Object.values(nextIssues).some(Boolean) || Object.values(draftIssues).some(Boolean)) {
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
        if (!Object.keys(changes).length) {
          if (bootstrap.capabilities.registeredDeaths) setListMode(true);
          else router.replace("/collection");
          return;
        }
        const result = await requestClientJson<unknown>(`${INTAKE_API}/deaths/${encodeURIComponent(editingDeathId)}`, {
          method: "PATCH",
          json: { ...changes, ...(registrationUpdatedAt.current ? { if_updated_at: registrationUpdatedAt.current } : {}) },
          csrf: bootstrap.csrf
        });
        if (!current()) return;
        if (!record(result) || !record(result.case) || result.case.death_id !== editingDeathId || typeof result.case.updated_at !== "string") {
          throw new ApiError(200, "malformed_response");
        }
        registrationUpdatedAt.current = result.case.updated_at;
        if (bootstrap.capabilities.registeredDeaths) {
          setEditingDeathId(undefined);
          setFields({});
          setSex("");
          setListMode(true);
          setRegisteredDeaths([]);
          void loadRegisteredDeaths();
        } else {
          router.replace("/collection");
        }
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
                !["deceased_name", "date_of_death"].includes(key) && typeof value === "string" && value.trim() !== ""
            )
          )
        } as RegistrationInput,
        bootstrap.csrf
      );
      if (!current()) return;
      const mayStartInterview = bootstrap.capabilities.intake &&
        hasInterviewRegistrationAccess(bootstrap.access, projectId, siteId, orgUnitId || undefined) &&
        typeof registration.case.links?.start_interview === "string";
      if (!mayStartInterview) {
        if (bootstrap.capabilities.registeredDeaths) {
          setListMode(true);
          setRegisteredDeaths([]);
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
      router.replace({ pathname: "/interview", params: { draftId: draft.draft.draft_id } });
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
        setMessage(error instanceof ApiError && error.status === 422 ? t("serverValidation") : browserErrorText(error));
      }
    } finally {
      if (current()) setBusy(false);
    }
  }

  return (
    <WebShell title={t("registrationTitle")}>
      {privateUiReady ? <>
      {bootstrap?.capabilities.registeredDeaths ? (
        <Button
          kind="secondary"
          label={listMode ? t("registerDeath") : t("myRegisteredDeaths")}
          onPress={() => {
            if (busy) return;
            setMessage("");
            if (editingDeathId) {
              setEditingDeathId(undefined);
              registrationBase.current = undefined;
              registrationUpdatedAt.current = undefined;
              registrationSource.current = undefined;
              registrationSourceCursor.current = undefined;
              setFields({});
              setSex("");
              setListMode(true);
            } else setListMode((current) => !current);
          }}
          disabled={busy}
        />
      ) : null}
      {showRegisteredDeaths ? (
        <>
          {message ? <Text style={styles.error}>{message}</Text> : null}
          {registeredDeaths.map((death) => (
            <View key={death.death_id} style={styles.card}>
              <Text style={styles.text}>{death.deceased_name ?? death.unique_id}</Text>
              <Text style={styles.muted}>
                {death.unique_id}{death.date_of_death ? ` · ${death.date_of_death}` : ""}
                {death.unit_name || death.org_unit_name ? ` · ${death.unit_name ?? death.org_unit_name}` : ""}
              </Text>
              {death.details_pending !== true && death.other_complete_interview !== true && !["draft_identity", "completed", "submitted"].includes(String(death.status ?? "")) ? (
                <Button kind="secondary" label={t("editRegistration")} onPress={() => beginEdit(death)} />
              ) : null}
            </View>
          ))}
          {!registeredDeaths.length && !listBusy && !message ? <Text style={styles.muted}>{t("noReportedDeaths")}</Text> : null}
          {nextCursor ? <Button kind="secondary" loading={listBusy} label={t("loadMore")} onPress={() => void loadRegisteredDeaths(nextCursor)} /> : null}
        </>
      ) : editingReadOnly ? (
        <>
          <Text style={styles.error} accessibilityRole="alert">{message || t("serverValidation")}</Text>
          <Button kind="secondary" label={t("cancel")} onPress={() => {
            if (bootstrap?.capabilities.registeredDeaths) setListMode(true);
            else router.back();
          }} />
        </>
      ) : intake?.context.length || editingDeathId ? (
        <>
          {editingDeathId ? (
            <Text style={styles.muted}>{projectId} · {siteId}</Text>
          ) : (
            <>
              <Text style={styles.muted}>{t("chooseSite")}</Text>
              <View style={styles.row} accessibilityRole="radiogroup">
                {intake?.context.map((entry) => (
                  <Button
                    key={`${entry.project_id}:${entry.site_id}`}
                    kind={entry.project_id === projectId && entry.site_id === siteId ? "primary" : "secondary"}
                    label={`${entry.project_name ?? entry.project_id} · ${entry.site_name ?? entry.site_id}`}
                    onPress={() => {
                      setProjectId(entry.project_id);
                      setSiteId(entry.site_id);
                      setOrgUnitId("");
                    }}
                  />
                ))}
              </View>
            </>
          )}
          {!editingDeathId && context?.org_units?.filter((unit) => unit.selectable !== false).length ? (
            <View>
              <Text style={styles.muted}>{t("chooseUnit")}</Text>
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
          <Text style={styles.muted}>{t("fieldDateOfBirth")}</Text>
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
          {ageDisplay ? <Text style={styles.muted}>{formatRegistrationAge(ageDisplay)}</Text> : null}
          {birthMode !== "exact" ? (
            <View>
              <Text style={styles.muted}>{t("fieldAge")}</Text>
              <RegistrationFieldControl
                field="age_years"
                label={t("fieldAge")}
                value={String(fields.age_years ?? "")}
                onChange={(value) => updateField("age_years", value)}
                issueMessage={issueMessage("age_years")}
                onIssue={(issue) => updateFieldIssue("age_years", issue)}
              />
            </View>
          ) : null}
          <Text style={styles.muted}>{t("fieldSex")}</Text>
          <View style={styles.row} accessibilityRole="radiogroup">
            {(["male", "female", "undetermined", "unknown"] as const).map((value) => (
              <Button
                key={value}
                kind={sex === value ? "primary" : "secondary"}
                label={t(`sex${value[0].toUpperCase()}${value.slice(1)}` as "sexMale")}
                onPress={() => {
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
          {FIELD_DEFINITIONS.slice(1).map(renderField)}
          {message ? <Text style={styles.error} accessibilityRole="alert">{message}</Text> : null}
          {ageConfirmationPending ? (
            <View style={styles.card} accessibilityRole="alert">
              <Text style={styles.text}>{t("ageReviewConfirm")}</Text>
              <View style={styles.row}>
                <Button kind="secondary" label={t("cancel")} onPress={() => setAgeConfirmationPending(false)} />
                <Button loading={busy} disabled={busy} label={t("ageReviewSave")} onPress={() => void submit(true)} />
              </View>
            </View>
          ) : null}
          <Button loading={busy} disabled={busy || ageConfirmationPending} label={t(editingDeathId ? "save" : "registerSaveStart")} onPress={() => void submit()} />
          <Button kind="secondary" label={t("cancel")} onPress={() => {
            if (editingDeathId && bootstrap?.capabilities.registeredDeaths) {
              setEditingDeathId(undefined);
              setFields({});
              setSex("");
              setListMode(true);
            } else router.back();
          }} />
        </>
      ) : (
        <Text style={styles.muted}>{message || t("noSites")}</Text>
      )}
      </> : null}
    </WebShell>
  );
}
