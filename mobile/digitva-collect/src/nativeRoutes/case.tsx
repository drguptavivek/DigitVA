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
import { useCallback, useRef, useState } from "react";
import { Linking, Text, TextInput, View } from "react-native";

import { useAppState } from "../AppState";
import {
  CONTACT_OUTCOMES,
  deleteAction,
  discardRegistration,
  getRegistration,
  listActions,
  queueAction,
  visitAt,
  type CaseAction,
  type CaseDetail,
  type ContactOutcome,
  type Registration,
} from "../cases";
import { draftForCase, type Db, type DraftRow } from "../drafts";
import { t, type StringKey } from "../i18n";
import { isUnlocked, openInterviewerDb } from "../interviewerDb";
import {
  canFollowUpDeath,
  canStartDeathInterview,
  deathPhoneUrl,
} from "../deathWorkflow";
import { fetchCaseDetail } from "../sync";
import { Button, errorText, Row, Screen, stateLabel, useUiStyles } from "../ui";

function displayDate(value: string | null | undefined): string | undefined {
  if (!value) return undefined;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? undefined : date.toLocaleDateString();
}

/** Format a server timestamp for the other-interviewer warning, if valid. */
function otherDraftDate(value: string | null | undefined): string | undefined {
  if (!value) return undefined;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? undefined : date.toLocaleString();
}

/** Show the server time when usable, otherwise the generic active warning. */
function otherDraftWarning(value: string | null | undefined): string {
  const date = otherDraftDate(value);
  return date ? t("otherDraftActiveAt", { date }) : t("otherDraftActive");
}

function detailLine(
  label: string,
  value: string | number | null | undefined,
): string | undefined {
  if (value === null || value === undefined || value === "") return undefined;
  return `${label}: ${value}`;
}

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
  const params = useLocalSearchParams<{
    userId: string;
    projectId?: string;
    deathId?: string;
    clientDeathId?: string;
  }>();
  const { accounts } = useAppState();
  const account = accounts.find((a) => a.user_id === params.userId);
  const accountId = account?.user_id;
  const [db, setDb] = useState<Db | undefined>();
  const [found, setFound] = useState<CaseDetail | undefined>();
  const [registration, setRegistration] = useState<Registration | undefined>();
  const [draft, setDraft] = useState<DraftRow | null>(null);
  const [actions, setActions] = useState<CaseAction[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [mode, setMode] = useState<"attempt" | "visit" | undefined>();
  const [editingId, setEditingId] = useState<string | undefined>();
  const [outcome, setOutcome] = useState<ContactOutcome | undefined>();
  const [date, setDate] = useState("");
  const [message, setMessage] = useState("");
  const [actionBusy, setActionBusy] = useState(false);
  const { deathId, clientDeathId } = params;
  const requestGeneration = useRef(0);
  const routeIdentityRef = useRef("");
  const routeIdentity = `${account?.user_id ?? ""}|${deathId ?? ""}|${clientDeathId ?? ""}`;

  const load = useCallback(
    async (handle: Db, isCurrent: () => boolean = () => true) => {
      const [row, reg, local, queued] = await Promise.all([
        deathId
          ? fetchCaseDetail(accountId ?? "", handle, deathId)
          : Promise.resolve(undefined),
        clientDeathId
          ? getRegistration(handle, clientDeathId)
          : Promise.resolve(undefined),
        draftForCase(handle, { deathId, clientDeathId }),
        listActions(handle),
      ]);
      if (!isCurrent()) return;
      setFound(row);
      setRegistration(reg);
      setDraft(local);
      setActions(
        queued.filter(
          (a) =>
            (deathId && a.death_id === deathId) ||
            (clientDeathId && a.client_death_id === clientDeathId),
        ),
      );
      setLoaded(true);
    },
    [accountId, deathId, clientDeathId],
  );

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
      setDb(undefined);
      setFound(undefined);
      setRegistration(undefined);
      setDraft(null);
      setActions([]);
      setLoaded(false);
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
        if (
          requestGeneration.current !== generation ||
          routeIdentityRef.current !== routeIdentity
        )
          return;
        requestGeneration.current += 1;
        routeIdentityRef.current = "";
        setDb(undefined);
        setFound(undefined);
        setRegistration(undefined);
        setDraft(null);
        setActions([]);
        setLoaded(false);
        setMode(undefined);
        setActionBusy(false);
      };
    }, [account, load, routeIdentity]),
  );

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
        <Text style={styles.text}>{t("deathNotFound")}</Text>
        {message ? <Text style={styles.error}>{message}</Text> : null}
        <Button
          kind="secondary"
          label={t("backToDeaths")}
          onPress={() => router.back()}
        />
      </Screen>
    );
  }

  const name = found?.deceased.name ?? registration?.fields.deceased_name ?? "";
  const followUpAllowed = found
    ? canFollowUpDeath(found.state)
    : registration?.state === "pending";
  const startAllowed = found
    ? !TERMINAL_DEATH_STATES.has(found.state) &&
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

  async function saveAction() {
    if (!db || !mode || actionBusy) return;
    if (
      !(found
        ? canFollowUpDeath(found.state)
        : registration?.state === "pending")
    ) {
      setMessage(t("caseActionsUnavailable"));
      return;
    }
    const generation = requestGeneration.current;
    const identity = routeIdentity;
    const isCurrent = () =>
      requestGeneration.current === generation &&
      routeIdentityRef.current === identity;
    setActionBusy(true);
    setMessage("");
    const at = date.trim() ? visitAt(date.trim()) : null;
    const day = 86_400_000;
    const time = at ? new Date(at).getTime() : 0;
    // The server takes yesterday to 366 days ahead (web_intake_service._clean_visit_at).
    if (
      (date.trim() && !at) ||
      (mode === "visit" && !at) ||
      (at && (time < Date.now() - day || time > Date.now() + 366 * day))
    ) {
      setMessage(t("errVisitDate"));
      setActionBusy(false);
      return;
    }
    if (mode === "attempt" && !outcome) {
      setMessage(t("errRequired"));
      setActionBusy(false);
      return;
    }
    try {
      await queueAction(db, {
        project_id:
          found?.project_id ??
          registration?.project_id ??
          params.projectId ??
          "",
        client_id: editingId ?? randomUUID(),
        kind: mode,
        death_id: deathId ?? null,
        client_death_id: clientDeathId ?? null,
        body:
          mode === "attempt"
            ? {
                outcome,
                ...(at && outcome !== "refused" ? { next_visit_at: at } : {}),
              }
            : { next_visit_at: at },
      });
      if (!isCurrent()) return;
      setMode(undefined);
      setMessage(t("queued"));
      await load(db, isCurrent);
    } catch (error) {
      if (isCurrent()) setMessage(errorText(error));
    } finally {
      if (isCurrent()) setActionBusy(false);
    }
  }

  async function discard(action: CaseAction) {
    if (!db || actionBusy) return;
    const generation = requestGeneration.current;
    const identity = routeIdentity;
    const isCurrent = () =>
      requestGeneration.current === generation &&
      routeIdentityRef.current === identity;
    setActionBusy(true);
    setMessage("");
    try {
      await deleteAction(db, action.client_id);
      if (!isCurrent()) return;
      await load(db, isCurrent);
    } catch (error) {
      if (isCurrent()) setMessage(errorText(error));
    } finally {
      if (isCurrent()) setActionBusy(false);
    }
  }

  async function discardThisRegistration() {
    if (!db || !clientDeathId || actionBusy) return;
    const generation = requestGeneration.current;
    const identity = routeIdentity;
    const isCurrent = () =>
      requestGeneration.current === generation &&
      routeIdentityRef.current === identity;
    setActionBusy(true);
    setMessage("");
    try {
      await discardRegistration(db, clientDeathId);
      if (isCurrent()) router.back();
    } catch (error) {
      if (isCurrent()) setMessage(errorText(error));
    } finally {
      if (isCurrent()) setActionBusy(false);
    }
  }

  async function callPhone(phone: string) {
    const url = deathPhoneUrl(phone);
    if (!url || actionBusy) return;
    const generation = requestGeneration.current;
    const identity = routeIdentity;
    const isCurrent = () =>
      requestGeneration.current === generation &&
      routeIdentityRef.current === identity;
    setActionBusy(true);
    setMessage("");
    try {
      await Linking.openURL(url);
    } catch (error) {
      if (isCurrent()) setMessage(errorText(error));
    } finally {
      if (isCurrent()) setActionBusy(false);
    }
  }

  return (
    <Screen title={t("deathDetails")}>
      {name ? <Text style={styles.headline}>{name}</Text> : null}
      {found ? (
        <View style={{ gap: 4 }}>
          <Text style={styles.muted}>{found.unique_id}</Text>
          {found.other_draft_active === true ? (
            <>
              <Text style={styles.muted}>
                {otherDraftWarning(found.other_draft_started_at)}
              </Text>
              <Text style={styles.muted}>{t("otherDraftSyncNotice")}</Text>
            </>
          ) : null}
          {[
            detailLine(
              t("fieldAge").replace(/\s*\*\s*$/, ""),
              found.deceased.age_years,
            ),
            detailLine(
              t("fieldSex").replace(/\s*\*\s*$/, ""),
              found.deceased.sex,
            ),
            detailLine(
              t("fieldDateOfDeath").replace(/\s*\*\s*$/, ""),
              displayDate(found.deceased.date_of_death),
            ),
            detailLine(t("fieldPlaceOfDeath"), found.deceased.place_of_death),
            detailLine(t("chooseUnit"), found.unit_name),
            detailLine(t("deathStatus"), stateLabel(found.state)),
            found.last_contact_at
              ? `${t("lastContact")}: ${displayDate(found.last_contact_at) ?? found.last_contact_at}`
              : undefined,
            found.next_visit_at
              ? t("nextVisit", {
                  date: displayDate(found.next_visit_at) ?? found.next_visit_at,
                })
              : undefined,
          ]
            .filter((value): value is string => Boolean(value))
            .map((value) => (
              <Text key={value} style={styles.muted}>
                {value}
              </Text>
            ))}
          {[
            detailLine(t("fieldInformantName"), found.informant.name),
            detailLine(t("fieldAddress"), found.household_address.address),
            detailLine(
              t("fieldHouseStreet"),
              found.household_address.house_street,
            ),
            detailLine(
              t("fieldVillageWard"),
              found.household_address.village_ward,
            ),
            detailLine(t("fieldLandmark"), found.household_address.landmark),
            detailLine(t("fieldRemarks"), found.remarks),
          ]
            .filter((value): value is string => Boolean(value))
            .map((value) => (
              <Text key={value} style={styles.text}>
                {value}
              </Text>
            ))}
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
        </View>
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
          <Text style={styles.headline}>{t("contactDetailsHeading")}</Text>
          {[
            detailLine(
              t("fieldAge").replace(/\s*\*\s*$/, ""),
              registration.fields.age_years,
            ),
            detailLine(
              t("fieldSex").replace(/\s*\*\s*$/, ""),
              registration.fields.deceased_sex,
            ),
            detailLine(
              t("fieldDateOfDeath").replace(/\s*\*\s*$/, ""),
              displayDate(registration.fields.date_of_death),
            ),
            detailLine(
              t("dobPrecision"),
              registration.fields.date_of_birth ??
                registration.fields.date_of_birth_partial,
            ),
            detailLine(t("fieldAddress"), registration.fields.address),
            detailLine(
              t("fieldHouseStreet"),
              registration.fields.address_house_street,
            ),
            detailLine(
              t("fieldVillageWard"),
              registration.fields.address_village_ward,
            ),
            detailLine(
              t("fieldLandmark"),
              registration.fields.address_landmark,
            ),
            detailLine(
              t("fieldInformantName"),
              registration.fields.informant_name,
            ),
            detailLine(t("fieldRemarks"), registration.fields.remarks),
          ]
            .filter((value): value is string => Boolean(value))
            .map((value) => (
              <Text key={value} style={styles.text}>
                {value}
              </Text>
            ))}
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
            <Text style={styles.muted}>{t("contactDetailsUnavailable")}</Text>
          )}
          {!followUpAllowed ? (
            <Text style={styles.muted}>{t("caseActionsUnavailable")}</Text>
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
        <Text style={styles.muted}>{t("caseActionsUnavailable")}</Text>
      ) : null}
      {mode ? (
        <View style={{ gap: 8 }}>
          {mode === "attempt" ? (
            <Row>
              {CONTACT_OUTCOMES.map((value) => (
                <Button
                  key={value}
                  kind={outcome === value ? "primary" : "secondary"}
                  label={t(`outcome_${value}` as StringKey)}
                  disabled={actionBusy}
                  onPress={() => setOutcome(value)}
                />
              ))}
            </Row>
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
      ) : (
        <Row>
          <Button
            kind="secondary"
            label={t("logAttempt")}
            disabled={!db || !followUpAllowed || actionBusy}
            onPress={() => openForm("attempt")}
          />
          <Button
            kind="secondary"
            label={t("setVisit")}
            disabled={!db || !followUpAllowed || actionBusy}
            onPress={() => openForm("visit")}
          />
        </Row>
      )}
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
      <Button
        kind="secondary"
        label={t("backToDeaths")}
        onPress={() => router.back()}
      />
    </Screen>
  );
}
