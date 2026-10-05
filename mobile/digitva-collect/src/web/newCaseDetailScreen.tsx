import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Linking, Text, View } from "react-native";

import {
  getCaseDetail,
  logContactAttempt,
  setCaseVisit,
  startDraft,
  type CaseDetail,
} from "../client/api";
import { useAppState } from "../AppState";
import {
  canFollowUpDeath,
  canStartDeathInterview,
  deathPhoneUrl,
} from "../deathWorkflow";
import { localToday, visitAt } from "../cases";
import { t, type StringKey } from "../i18n";
import { stateLabel, Button, useUiStyles } from "../ui";
import { browserErrorText, WebShell } from "./common";
import { RegistrationFieldControl } from "./registrationControls";

const CONTACT_OUTCOMES = [
  "reached",
  "no_answer",
  "wrong_number",
  "moved",
  "refused",
] as const;
type ContactOutcome = (typeof CONTACT_OUTCOMES)[number];
type ActionPanel = "attempt" | "visit" | undefined;

function paramValue(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString();
}

function otherDraftNotice(startedAt: string | null | undefined): string {
  if (typeof startedAt === "string") {
    const date = new Date(startedAt);
    if (!Number.isNaN(date.getTime())) {
      return t("otherDraftActiveAt", { date: date.toLocaleString() });
    }
  }
  return t("otherDraftActive");
}

function sexLabel(value: string | null | undefined): string {
  if (!value) return "";
  const normalized = value.toLowerCase();
  const key =
    `sex${normalized[0]?.toUpperCase() ?? ""}${normalized.slice(1)}` as StringKey;
  const label = t(key);
  return label === key ? value : label;
}

function detailLine(
  label: string,
  value: string | number | null | undefined,
): string | undefined {
  if (value === null || value === undefined || value === "") return undefined;
  return label + ": " + value;
}

export default function NewCaseDetailScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ deathId?: string | string[] }>();
  const deathId = paramValue(params.deathId);
  const { bootstrap } = useAppState();
  const styles = useUiStyles();
  const [row, setRow] = useState<CaseDetail>();
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [panel, setPanel] = useState<ActionPanel>();
  const [outcome, setOutcome] = useState<ContactOutcome>();
  const [visitDate, setVisitDate] = useState("");
  const bootstrapRef = useRef(bootstrap);
  const requestRef = useRef(0);
  const busyRef = useRef(false);
  const actionRef = useRef(0);
  if (bootstrapRef.current !== bootstrap) bootstrapRef.current = bootstrap;

  const load = useCallback(async (): Promise<boolean> => {
    const request = ++requestRef.current;
    const isCurrent = () =>
      requestRef.current === request && bootstrapRef.current === bootstrap;
    if (!bootstrap || !deathId) {
      if (isCurrent()) setLoading(false);
      return false;
    }
    setLoading(true);
    setMessage("");
    try {
      const result = await getCaseDetail(
        bootstrap.links.intakeCases,
        deathId,
        bootstrap.csrf,
      );
      if (!isCurrent()) return false;
      setRow(result.case);
      return true;
    } catch (error) {
      if (isCurrent()) setMessage(browserErrorText(error));
      return false;
    } finally {
      if (isCurrent()) setLoading(false);
    }
  }, [bootstrap, deathId]);

  useEffect(() => {
    requestRef.current += 1;
    actionRef.current += 1;
    busyRef.current = false;
    setBusy(false);
    setRow(undefined);
    setPanel(undefined);
    setOutcome(undefined);
    setVisitDate("");
    setMessage("");
    setLoading(true);
    void load();
    return () => {
      requestRef.current += 1;
      actionRef.current += 1;
    };
  }, [load]);

  function openAttempt() {
    if (busyRef.current) return;
    setPanel("attempt");
    setOutcome(undefined);
    setVisitDate("");
    setMessage("");
  }

  function openVisit() {
    if (busyRef.current) return;
    setPanel("visit");
    setOutcome(undefined);
    setVisitDate(
      row?.next_visit_at ? row.next_visit_at.slice(0, 10) : localToday(),
    );
    setMessage("");
  }

  async function saveAction() {
    if (busyRef.current || !bootstrap || !row || !panel) return;
    const currentState = row.state ?? row.status ?? "";
    if (!canFollowUpDeath(currentState)) {
      setMessage(t("caseActionsUnavailable"));
      return;
    }
    const request = requestRef.current;
    const actionToken = ++actionRef.current;
    const actionBootstrap = bootstrap;
    const actionDeathId = row.death_id;
    const isCurrent = () =>
      requestRef.current === request &&
      bootstrapRef.current === actionBootstrap &&
      actionDeathId === row.death_id;
    if (panel === "attempt" && !outcome) {
      setMessage(t("errRequired"));
      return;
    }
    const date = visitDate.trim();
    const at = date ? visitAt(date) : null;
    const day = 86_400_000;
    const timestamp = at ? new Date(at).getTime() : 0;
    if (
      (date && !at) ||
      (panel === "visit" && !at) ||
      (at &&
        (timestamp < Date.now() - day || timestamp > Date.now() + 366 * day))
    ) {
      setMessage(t("errVisitDate"));
      return;
    }
    busyRef.current = true;
    setBusy(true);
    setMessage("");
    try {
      if (panel === "attempt") {
        await logContactAttempt(
          bootstrap.links.intakeCases,
          row.death_id,
          {
            outcome: outcome!,
            ...(at && outcome !== "refused" ? { next_visit_at: at } : {}),
          },
          bootstrap.csrf,
        );
      } else {
        await setCaseVisit(
          bootstrap.links.intakeCases,
          row.death_id,
          { next_visit_at: at },
          bootstrap.csrf,
        );
      }
      if (!isCurrent()) return;
      setPanel(undefined);
      setOutcome(undefined);
      setVisitDate("");
      const refreshed = await load();
      if (
        actionRef.current === actionToken &&
        bootstrapRef.current === actionBootstrap &&
        refreshed
      ) {
        setMessage(t("registrationSaved"));
      }
    } catch (error) {
      if (isCurrent()) setMessage(browserErrorText(error));
    } finally {
      if (actionRef.current === actionToken) {
        busyRef.current = false;
        setBusy(false);
      }
    }
  }

  async function startOrResume() {
    if (busyRef.current || !bootstrap || !row) return;
    const request = requestRef.current;
    const actionToken = ++actionRef.current;
    const actionBootstrap = bootstrap;
    const actionDeathId = row.death_id;
    const isCurrent = () =>
      requestRef.current === request &&
      bootstrapRef.current === actionBootstrap &&
      actionDeathId === row.death_id;
    const currentState = row.state ?? row.status ?? "";
    const canResume =
      Boolean(row.my_draft_id) &&
      ![
        "completed",
        "submitted",
        "cancelled",
        "closed",
        "duplicate",
        "not_codeable",
      ].includes(currentState);
    if (canResume && row.my_draft_id) {
      router.push({
        pathname: "/interview",
        params: { draftId: row.my_draft_id },
      });
      return;
    }
    if (
      !row.prefill ||
      !canStartDeathInterview(currentState) ||
      !row.project_id ||
      !row.site_id
    ) {
      setMessage(t("caseActionsUnavailable"));
      return;
    }
    busyRef.current = true;
    setBusy(true);
    setMessage("");
    try {
      const result = await startDraft(
        bootstrap.links.intakeDrafts,
        {
          project_id: row.project_id,
          site_id: row.site_id,
          ...(row.org_unit_id ? { org_unit_id: row.org_unit_id } : {}),
          death_id: row.death_id,
        },
        bootstrap.csrf,
      );
      if (isCurrent())
        router.push({
          pathname: "/interview",
          params: { draftId: result.draft.draft_id },
        });
    } catch (error) {
      if (isCurrent()) setMessage(browserErrorText(error));
    } finally {
      if (actionRef.current === actionToken) {
        busyRef.current = false;
        setBusy(false);
      }
    }
  }

  const state = row?.state ?? row?.status ?? "";
  const canAct = row ? canFollowUpDeath(state) : false;
  const canResume = row
    ? Boolean(row.my_draft_id) &&
      ![
        "completed",
        "submitted",
        "cancelled",
        "closed",
        "duplicate",
        "not_codeable",
      ].includes(state)
    : false;
  const canInterview =
    canResume || (row ? Boolean(row.prefill) && canStartDeathInterview(state) : false);
  const deceased = row?.deceased;
  const address = row?.household_address;
  const informant = row?.informant;
  const phones = [informant?.phone, informant?.phone_2].filter(
    (phone): phone is string => Boolean(phone?.trim()),
  );

  return (
    <WebShell title={t("deathDetails")}>
      <Button
        kind="secondary"
        label={t("backToDeaths")}
        onPress={() => router.push("/collection")}
      />
      {loading ? <Text style={styles.muted}>{t("loading")}</Text> : null}
      {!loading && !row ? (
        <Text style={styles.error} accessibilityRole="alert">
          {message || t("deathNotFound")}
        </Text>
      ) : null}
      {row ? (
        <>
          <View style={styles.card}>
            <Text style={styles.headline}>
              {deceased?.name ?? row.deceased_name ?? row.unique_id}
            </Text>
            <Text style={styles.muted}>
              {row.unique_id} · {stateLabel(state)}
            </Text>
            {row.other_draft_active === true ? (
              <Text style={styles.error} accessibilityRole="alert">
                {otherDraftNotice(row.other_draft_started_at)}
              </Text>
            ) : null}
            {row.other_complete_interview === true ? (
              <Text style={styles.muted}>{t("otherCompleteInterviewNotice")}</Text>
            ) : null}
            {[
              detailLine(
                t("fieldSex").replace(/\s*\*\s*$/, ""),
                sexLabel(deceased?.sex ?? row.deceased_sex),
              ),
              detailLine(
                t("fieldAge").replace(/\s*\*\s*$/, ""),
                deceased?.age_years ?? row.age_years,
              ),
              detailLine(
                t("fieldDateOfDeath").replace(/\s*\*\s*$/, ""),
                formatDate(deceased?.date_of_death ?? row.date_of_death),
              ),
              detailLine(
                t("dobPrecision"),
                deceased?.date_of_birth ?? deceased?.date_of_birth_partial,
              ),
              detailLine(t("fieldPlaceOfDeath"), deceased?.place_of_death),
              detailLine(t("chooseUnit"), row.unit_name ?? row.org_unit_name),
              detailLine(t("deathStatus"), stateLabel(state)),
              row.next_visit_at
                ? t("nextVisit", { date: formatDate(row.next_visit_at) })
                : undefined,
              row.last_contact_at
                ? t("lastContact") + ": " + formatDate(row.last_contact_at)
                : undefined,
            ]
              .filter((value): value is string => Boolean(value))
              .map((value, index) => (
                <Text key={value + "-" + index} style={styles.muted}>
                  {value}
                </Text>
              ))}
          </View>
          <View style={styles.card}>
            <Text style={styles.headline}>{t("contactDetailsHeading")}</Text>
            {detailLine(t("fieldInformantName"), informant?.name) ? (
              <Text style={styles.text}>
                {detailLine(t("fieldInformantName"), informant?.name)}
              </Text>
            ) : null}
            {phones.map((phone) => {
              const url = deathPhoneUrl(phone);
              return (
                <View key={phone} style={styles.row}>
                  <Text style={styles.text}>{phone}</Text>
                  {url ? (
                    <Button
                      kind="secondary"
                      label={t("callInformant")}
                      onPress={() => void Linking.openURL(url).catch((error) => setMessage(browserErrorText(error)))}
                    />
                  ) : null}
                </View>
              );
            })}
            {[
              detailLine(t("fieldAddress"), address?.address),
              detailLine(t("fieldHouseStreet"), address?.house_street),
              detailLine(t("fieldVillageWard"), address?.village_ward),
              detailLine(t("fieldLandmark"), address?.landmark),
              detailLine(t("fieldRemarks"), row.remarks),
            ]
              .filter((value): value is string => Boolean(value))
              .map((value, index) => (
                <Text key={value + "-" + index} style={styles.text}>
                  {value}
                </Text>
              ))}
            {!informant?.name &&
            phones.length === 0 &&
            !address?.address &&
            !address?.house_street &&
            !address?.village_ward &&
            !address?.landmark &&
            !row.remarks ? (
              <Text style={styles.muted}>{t("contactDetailsUnavailable")}</Text>
            ) : null}
          </View>
          <View style={styles.row}>
            <Button
              label={
                row.my_draft_id ? t("resumeInterview") : t("startInterview")
              }
              disabled={busy || !canInterview}
              loading={busy}
              onPress={() => void startOrResume()}
            />
            {canAct ? (
              <>
                <Button
                  kind="secondary"
                  label={t("logAttempt")}
                  disabled={busy}
                  onPress={openAttempt}
                />
                <Button
                  kind="secondary"
                  label={t("setVisit")}
                  disabled={busy}
                  onPress={openVisit}
                />
              </>
            ) : (
              <Text style={styles.muted}>{t("caseActionsUnavailable")}</Text>
            )}
          </View>
          {panel ? (
            <View style={styles.card}>
              {panel === "attempt" ? (
                <View style={styles.row} accessibilityRole="radiogroup">
                  {CONTACT_OUTCOMES.map((value) => (
                    <Button
                      key={value}
                      kind={outcome === value ? "primary" : "secondary"}
                      label={t(`outcome_${value}` as StringKey)}
                      disabled={busy}
                      onPress={() => setOutcome(value)}
                    />
                  ))}
                </View>
              ) : null}
              {panel === "visit" || outcome !== "refused" ? (
                <RegistrationFieldControl
                  field="date_of_death"
                  label={t("visitDate")}
                  value={visitDate}
                  onChange={setVisitDate}
                  dateAppearance="exact"
                />
              ) : null}
              <View style={styles.row}>
                <Button
                  label={t("save")}
                  loading={busy}
                  disabled={busy}
                  onPress={() => void saveAction()}
                />
                <Button
                  kind="secondary"
                  label={t("cancel")}
                  disabled={busy}
                  onPress={() => setPanel(undefined)}
                />
              </View>
            </View>
          ) : null}
          {message ? (
            <Text style={styles.error} accessibilityRole="alert">
              {message}
            </Text>
          ) : null}
        </>
      ) : null}
    </WebShell>
  );
}
