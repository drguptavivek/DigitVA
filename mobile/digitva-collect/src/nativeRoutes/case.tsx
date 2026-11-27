/**
 * One case on the phone: a downloaded case (`deathId`) or a death registered
 * here and not yet sent (`clientDeathId`). Start (or resume) its interview,
 * log a contact attempt or set the next visit (queued with a client id and
 * sent on the next sync), and edit or discard what the server refused.
 * Shows full contact details only on this authorized single-case screen.
 */
import { randomUUID } from "expo-crypto";
import {
  Redirect,
  useFocusEffect,
  useLocalSearchParams,
  useRouter,
} from "expo-router";
import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { Text, TextInput, View } from "react-native";

import { useAppState } from "../AppState";
import {
  CONTACT_OUTCOMES,
  getCase,
  getRegistration,
  listActions,
  type CaseAction,
  type CaseDetail,
  type ContactOutcome,
  type Registration,
} from "../cases";
import { draftForCase, type Db, type DraftRow } from "../drafts";
import { t, type StringKey } from "../i18n";
import { isUnlocked, openInterviewerDb } from "../interviewerDb";
import { sendRefusal } from "../unsentWork";
import {
  canFollowUpDeath,
  canStartDeathInterview,
  deathFix,
  deathPhoneUrl,
} from "../deathWorkflow";
import { draftSyncDefaults, fetchCaseDetail, getCachedReferenceData } from "../sync";
import { reconcileCaseDraft } from "../draftSync";
import { fetchSubmittedRevisions } from "../revisions";
import { Button, Card, ChoiceRow, errorText, Notice, Row, Screen, Separator, stateLabel, useUiStyles } from "../ui";
import { otherDraftWarning } from "../ui/CaseCard";
import { useCaseActions } from "./useCaseActions";
import { useShell } from "../nativeShell/shellContext";

function displayDate(value: string | null | undefined): string | undefined {
  if (!value) return undefined;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? undefined : date.toLocaleDateString();
}


type Detail = [label: string, value: string | number | null | undefined];

/** Label over value, one pair per line, empty values left out (the case card's facts and contacts). */
function DetailList({ items }: { items: Detail[] }) {
  const styles = useUiStyles();
  return (
    <>
      {items
        .filter(([, value]) => value !== null && value !== undefined && value !== "")
        .map(([label, value]) => (
          <View key={label} accessible accessibilityLabel={`${label}: ${value}`}>
            <Text style={styles.muted}>{label}</Text>
            <Text style={styles.text}>{String(value)}</Text>
          </View>
        ))}
    </>
  );
}

const plainLabel = (label: string) => label.replace(/\s*\*\s*$/, "");

const TERMINAL_DEATH_STATES = new Set([
  "submitted",
  "completed",
  "closed",
  "duplicate",
  "cancelled",
]);

export default function Case() {
  const styles = useUiStyles();
  const router = useRouter();
  const shell = useShell();
  const params = useLocalSearchParams<{
    userId: string;
    projectId?: string;
    deathId?: string;
    clientDeathId?: string;
  }>();
  const { accounts, lockVersion } = useAppState();
  const account = accounts.find((a) => a.user_id === params.userId);
  const accountId = account?.user_id;
  const [db, setDb] = useState<Db | undefined>();
  const [found, setFound] = useState<CaseDetail | undefined>();
  const [registration, setRegistration] = useState<Registration | undefined>();
  // The server's reason a queued registration was refused (422), so the interviewer sees why it needs editing.
  const [registrationRefusal, setRegistrationRefusal] = useState("");
  const [draft, setDraft] = useState<DraftRow | null>(null);
  const [actions, setActions] = useState<CaseAction[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [mode, setMode] = useState<"attempt" | "visit" | undefined>();
  const [editingId, setEditingId] = useState<string | undefined>();
  const [outcome, setOutcome] = useState<ContactOutcome | undefined>();
  const [date, setDate] = useState("");
  const [message, setMessage] = useState("");
  const [actionBusy, setActionBusy] = useState(false);
  // The server records no submission id on a refused case, so a refusal sent from this device is known only by the
  // submitted-interview list (same rule as the interviews list).
  const [refusalSent, setRefusalSent] = useState(false);
  const { deathId, clientDeathId } = params;
  const requestGeneration = useRef(0);
  const routeIdentityRef = useRef("");
  const loadedIdentityRef = useRef("");
  const routeIdentity = `${account?.user_id ?? ""}|${deathId ?? ""}|${clientDeathId ?? ""}`;

  const load = useCallback(
    async (handle: Db, isCurrent: () => boolean = () => true) => {
      const [row, reg, local, queued, referenceData] = await Promise.all([
        deathId
          ? fetchCaseDetail(accountId ?? "", handle, deathId).catch(async (error) => {
              // Offline and never downloaded: say the network is down, not that the case is gone.
              if (error instanceof TypeError) return (await getCase(handle, deathId)) ?? Promise.reject(error);
              throw error;
            })
          : Promise.resolve(undefined),
        clientDeathId
          ? getRegistration(handle, clientDeathId)
          : Promise.resolve(undefined),
        draftForCase(handle, { deathId, clientDeathId }),
        listActions(handle),
        deathId ? getCachedReferenceData(handle) : Promise.resolve(undefined),
      ]);
      let currentDraft = local;
      let conflict = false;
      if (row && deathId) {
        try {
          const project = referenceData?.projects.find(
            ({ project: candidate }) => candidate.project_id === row.project_id,
          )?.project;
          const reconciled = await reconcileCaseDraft(
            accountId ?? "",
            handle,
            row,
            local,
            local?.id ?? randomUUID(),
            project ? draftSyncDefaults(project) : undefined,
          );
          currentDraft = reconciled.draft;
          conflict = reconciled.conflict;
        } catch (error) {
          // Existing encrypted work remains resumable when the network alone is unavailable.
          if (!(error instanceof TypeError) || !local) throw error;
        }
      }
      let sentRefusal = false;
      if (row?.state === "refused" && row.other_complete_interview !== true) {
        try {
          sentRefusal = (await fetchSubmittedRevisions(accountId ?? "")).some((r) => r.death_id === row.death_id);
        } catch {
          // Offline: the case stays as the server last described it.
        }
      }
      const refusalMessage =
        reg?.state === "needs_edit" && clientDeathId ? ((await sendRefusal(handle, clientDeathId))?.message ?? "") : "";
      if (!isCurrent()) return;
      setFound(row);
      setRefusalSent(sentRefusal);
      setRegistration(reg);
      setRegistrationRefusal(refusalMessage);
      setDraft(currentDraft);
      setActions(
        queued.filter(
          (a) =>
            (deathId && a.death_id === deathId) ||
            (clientDeathId && a.client_death_id === clientDeathId),
        ),
      );
      if (conflict) setMessage(t("draftConflictNotice"));
      setLoaded(true);
    },
    [accountId, deathId, clientDeathId],
  );

  // A lock drops the decrypted rows held here; the next focus then starts blank.
  useEffect(() => {
    if (!account || isUnlocked(account.user_id)) return;
    loadedIdentityRef.current = "";
    setDb(undefined);
    setFound(undefined);
    setRefusalSent(false);
    setRegistration(undefined);
    setRegistrationRefusal("");
    setDraft(null);
    setActions([]);
    setLoaded(false);
  }, [account, lockVersion]);

  useFocusEffect(
    useCallback(() => {
      if (!account) return;
      const generation = requestGeneration.current + 1;
      requestGeneration.current = generation;
      routeIdentityRef.current = routeIdentity;
      let active = true;
      const isCurrent = () =>
        active &&
        requestGeneration.current === generation &&
        routeIdentityRef.current === routeIdentity;
      // Coming back to the case already on screen reloads it in place; only another case or account starts blank.
      if (loadedIdentityRef.current !== routeIdentity) {
        loadedIdentityRef.current = routeIdentity;
        setDb(undefined);
        setFound(undefined);
        setRefusalSent(false);
        setRegistration(undefined);
        setRegistrationRefusal("");
        setDraft(null);
        setActions([]);
        setLoaded(false);
      }
      setMode(undefined);
      setMessage("");
      setActionBusy(false);
      void (async () => {
        try {
          const handle = await openInterviewerDb(account.user_id);
          if (!isCurrent()) return;
          setDb(handle);
          await load(handle, isCurrent);
        } catch (error) {
          if (isCurrent()) {
            setMessage(errorText(error));
            setLoaded(true);
          }
        }
      })();
      return () => {
        active = false;
      };
    }, [account, load, routeIdentity]),
  );

  const { saveAction, discard, discardThisRegistration, callPhone, openDirections, shareLocation } = useCaseActions({
    db, found, registration, mode, editingId, outcome, date, actionBusy, params, deathId, clientDeathId,
    requestGeneration, routeIdentityRef, routeIdentity, router, load, setActionBusy, setMessage, setMode,
  });

  if (!account) return <Redirect href="/" />;
  if (!isUnlocked(account.user_id)) {
    return (
      <Redirect
        href={{ pathname: "/unlock", params: { userId: account.user_id } }}
      />
    );
  }
  if (loaded && !found && !registration) {
    return (
      <Screen title={t("deathDetails")}>
        {message ? <Notice tone="error">{message}</Notice> : <Text style={styles.text}>{t("deathNotFound")}</Text>}
      </Screen>
    );
  }

  const name = found?.deceased.name ?? registration?.fields.deceased_name ?? "";
  const followUpAllowed = found
    ? canFollowUpDeath(found.state)
    : registration?.state === "pending";
  const refusedAndSent =
    found?.state === "refused" && (found.other_complete_interview === true || refusalSent);
  const startAllowed = found
    ? !TERMINAL_DEATH_STATES.has(found.state) &&
      // A refused case whose interview is submitted is Sent, not restartable.
      !refusedAndSent &&
      ((Boolean(found.prefill) && canStartDeathInterview(found.state)) || Boolean(draft))
    : registration?.state === "pending";

  const localPhones = registration
    ? [
        registration.fields.informant_phone,
        registration.fields.informant_phone_2,
      ].filter((phone): phone is string => Boolean(phone?.trim()))
    : [];
  const foundPhones = found
    ? [found.informant.phone, found.informant.phone_2].filter(
        (phone): phone is string => Boolean(phone?.trim()),
      )
    : [];

  function startInterview() {
    if (!account) return;
    if (!startAllowed) {
      setMessage(t("caseActionsUnavailable"));
      return;
    }
    router.push({
      pathname: "/form",
      params: {
        userId: account.user_id,
        draftId: draft?.id ?? randomUUID(),
        projectId:
          found?.project_id ??
          registration?.project_id ??
          params.projectId ??
          "",
        ...(found
          ? {
              siteId: found.site_id,
              ...(found.org_unit_id ? { orgUnitId: found.org_unit_id } : {}),
            }
          : {
              ...(registration?.site_id
                ? { siteId: registration.site_id }
                : {}),
              ...(registration?.org_unit_id
                ? { orgUnitId: registration.org_unit_id }
                : {}),
            }),
        ...(deathId ? { deathId } : { clientDeathId: clientDeathId ?? "" }),
      },
    });
  }

  function openForm(kind: "attempt" | "visit", action?: CaseAction) {
    if (
      !(found
        ? canFollowUpDeath(found.state)
        : registration?.state === "pending")
    ) {
      setMessage(t("caseActionsUnavailable"));
      return;
    }
    setMode(kind);
    setEditingId(action?.client_id);
    setOutcome(action?.body.outcome);
    setDate(
      action?.body.next_visit_at ? action.body.next_visit_at.slice(0, 10) : "",
    );
    setMessage("");
  }

  const foundFix = deathFix(found?.household_address);
  // A registration not yet sent keeps its fix flat in its fields.
  const localFix = registration ? deathFix(registration.fields as { latitude?: unknown; longitude?: unknown; accuracy_m?: unknown }) : null;

  // Directions and Share for a fix from the server case or this phone's queued registration.
  function locationActions(fix: NonNullable<typeof foundFix>) {
    return (
            <View style={{ gap: 4 }}>
              <Row>
                <Button
                  kind="secondary"
                  label={t("directions")}
                  disabled={actionBusy}
                  onPress={() => void openDirections(fix)}
                />
                <Button
                  kind="secondary"
                  label={t("shareLocation")}
                  disabled={actionBusy}
                  onPress={() => void shareLocation(fix)}
                />
              </Row>
              {fix.accuracy_m !== null ? (
                <Text style={styles.muted}>
                  {t("locationAccuracyAbout", {
                    meters: Math.round(fix.accuracy_m),
                  })}
                </Text>
              ) : null}
            </View>
    );
  }

  return (
    <Screen title={t("deathDetails")}>
      {name || found ? (
        <View style={{ gap: 2 }}>
          {name ? <Text style={styles.headline}>{name}</Text> : null}
          {found ? <Text style={styles.muted}>{found.unique_id}</Text> : null}
        </View>
      ) : null}
      {found ? (
        <>
          {found.code_now === true ? (
            <Text style={styles.muted}>{t("readyForCodeOnWeb")}</Text>
          ) : null}
          {found.other_draft_active === true ? (
            <Text style={styles.muted}>
              {otherDraftWarning(found.other_draft_started_at, found.other_draft_started_by, shell.sync)}
            </Text>
          ) : null}
          {found.other_complete_interview === true ? (
            <Notice tone="warning">{t("otherCompleteInterviewNotice")}</Notice>
          ) : null}
          <Card label={t("registerSectionDeceased")}>
            <DetailList
              items={[
                [t("deathStatus"), refusedAndSent ? t("badgeSent") : stateLabel(found.state)],
                [plainLabel(t("fieldAge")), found.deceased.age_years],
                [plainLabel(t("fieldSex")), found.deceased.sex],
                [plainLabel(t("fieldDateOfDeath")), displayDate(found.deceased.date_of_death)],
                [t("fieldPlaceOfDeath"), found.deceased.place_of_death],
                [t("chooseUnit"), found.unit_name],
                [t("lastContact"), found.last_contact_at ? (displayDate(found.last_contact_at) ?? found.last_contact_at) : undefined],
              ]}
            />
            {found.next_visit_at ? (
              <Text style={styles.text}>
                {t("nextVisit", { date: displayDate(found.next_visit_at) ?? found.next_visit_at })}
              </Text>
            ) : null}
          </Card>
          <Card label={t("contactDetailsHeading")}>
            <DetailList
              items={[
                [t("fieldInformantName"), found.informant.name],
                [t("fieldAddress"), found.household_address.address],
                [t("fieldHouseStreet"), found.household_address.house_street],
                [t("fieldVillageWard"), found.household_address.village_ward],
                [t("fieldLandmark"), found.household_address.landmark],
                [t("fieldRemarks"), found.remarks],
              ]}
            />
            {foundPhones.map((phone) => (
              <Row key={phone}>
                <Text style={styles.text}>{phone}</Text>
                {deathPhoneUrl(phone) ? (
                  <Button
                    kind="secondary"
                    label={t("callInformant")}
                    disabled={actionBusy}
                    onPress={() => void callPhone(phone)}
                  />
                ) : null}
              </Row>
            ))}
            {foundFix ? locationActions(foundFix) : null}
          </Card>
        </>
      ) : null}
      {registration ? (
        <View style={{ gap: 4 }}>
          <Text
            style={
              registration.state === "needs_edit" ? styles.error : styles.muted
            }
          >
            {registration.state === "needs_edit"
              ? t("needsEdit")
              : t("pendingSend")}
          </Text>
          {registration.state === "needs_edit" && registrationRefusal ? (
            <Text style={styles.error} accessibilityRole="alert">
              {t("refusalNotAccepted", { reason: registrationRefusal })}
            </Text>
          ) : null}
          <Row>
            <Button
              kind="secondary"
              label={t("editRegistration")}
              onPress={() =>
                router.push({
                  pathname: "/register",
                  params: {
                    userId: account.user_id,
                    clientDeathId: clientDeathId ?? "",
                  },
                })
              }
            />
            {registration.state === "needs_edit" ? (
              <Button
                kind="danger"
                label={t("discard")}
                disabled={actionBusy}
                onPress={() => void discardThisRegistration()}
              />
            ) : null}
          </Row>
          <Card label={t("contactDetailsHeading")}>
            <DetailList
              items={[
                [plainLabel(t("fieldAge")), registration.fields.age_years],
                [plainLabel(t("fieldSex")), registration.fields.deceased_sex],
                [plainLabel(t("fieldDateOfDeath")), displayDate(registration.fields.date_of_death)],
                [t("dobPrecision"), registration.fields.date_of_birth ?? registration.fields.date_of_birth_partial],
                [t("fieldAddress"), registration.fields.address],
                [t("fieldHouseStreet"), registration.fields.address_house_street],
                [t("fieldVillageWard"), registration.fields.address_village_ward],
                [t("fieldLandmark"), registration.fields.address_landmark],
                [t("fieldInformantName"), registration.fields.informant_name],
                [t("fieldRemarks"), registration.fields.remarks],
              ]}
            />
            {localPhones.length ? (
              localPhones.map((phone) => (
                <Row key={phone}>
                  <Text style={styles.text}>{phone}</Text>
                  {deathPhoneUrl(phone) ? (
                    <Button
                      kind="secondary"
                      label={t("callInformant")}
                      disabled={actionBusy}
                      onPress={() => void callPhone(phone)}
                    />
                  ) : null}
                </Row>
              ))
            ) : (
              <Notice tone="info">{t("contactDetailsUnavailable")}</Notice>
            )}
            {localFix ? locationActions(localFix) : null}
          </Card>
          {!followUpAllowed ? (
            <Notice tone="info">{t("caseActionsUnavailable")}</Notice>
          ) : null}
        </View>
      ) : null}
      {startAllowed && draft?.completed !== 1 ? (
        <Button
          label={draft ? t("resumeInterview") : t("startInterview")}
          disabled={!db || actionBusy}
          onPress={startInterview}
        />
      ) : found ? (
        <Notice tone="info">{t("caseActionsUnavailable")}</Notice>
      ) : null}
      {mode ? (
        <View style={{ gap: 8 }}>
          {mode === "attempt" ? (
            <Card grouped>
              {CONTACT_OUTCOMES.map((value, index) => (
                <Fragment key={value}>
                  {index ? <Separator /> : null}
                  <ChoiceRow
                    label={t(`outcome_${value}` as StringKey)}
                    selected={outcome === value}
                    disabled={actionBusy}
                    onPress={() => setOutcome(value)}
                  />
                </Fragment>
              ))}
            </Card>
          ) : null}
          {mode === "visit" || outcome !== "refused" ? (
            <>
              <Text style={styles.muted}>{t("visitDate")}</Text>
              <TextInput
                style={styles.input}
                editable={!actionBusy}
                autoCorrect={false}
                value={date}
                onChangeText={setDate}
              />
            </>
          ) : null}
          <Row>
            <Button
              label={t("save")}
              disabled={actionBusy}
              onPress={() => void saveAction()}
            />
            <Button
              kind="secondary"
              label={t("cancel")}
              disabled={actionBusy}
              onPress={() => setMode(undefined)}
            />
          </Row>
        </View>
      ) : followUpAllowed ? (
        // The server takes a contact attempt or visit only on a case waiting for a visit (409 otherwise), so none are offered elsewhere.
        <View style={{ flexDirection: "row", gap: 8 }}>
          <Button
            kind="secondary"
            style={{ flex: 1 }}
            label={t("logAttempt")}
            disabled={!db || !followUpAllowed || actionBusy}
            onPress={() => openForm("attempt")}
          />
          <Button
            kind="secondary"
            style={{ flex: 1 }}
            label={t("setVisit")}
            disabled={!db || !followUpAllowed || actionBusy}
            onPress={() => openForm("visit")}
          />
        </View>
      ) : null}
      {message ? <Text style={styles.text}>{message}</Text> : null}
      {actions.map((action) => (
        <View key={action.client_id} style={styles.card}>
          <Text style={styles.text}>
            {action.kind === "attempt"
              ? t("actionAttempt", {
                  outcome: t(`outcome_${action.body.outcome}` as StringKey),
                })
              : t("actionVisit", {
                  date: action.body.next_visit_at
                    ? new Date(action.body.next_visit_at).toLocaleDateString()
                    : "-",
                })}
          </Text>
          <Text
            style={action.state === "needs_edit" ? styles.error : styles.muted}
          >
            {action.state === "needs_edit" ? t("needsEdit") : t("pendingSend")}
          </Text>
          {action.state === "needs_edit" ? (
            <Row>
              <Button
                kind="secondary"
                label={t("edit")}
                onPress={() => openForm(action.kind, action)}
              />
              <Button
                kind="danger"
                label={t("discard")}
                onPress={() => void discard(action)}
              />
            </Row>
          ) : null}
        </View>
      ))}
    </Screen>
  );
}
