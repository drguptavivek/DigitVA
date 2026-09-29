/**
 * One case on the phone: a downloaded case (`deathId`) or a death registered
 * here and not yet sent (`clientDeathId`). Start (or resume) its interview,
 * log a contact attempt or set the next visit (queued with a client id and
 * sent on the next sync), and edit or discard what the server refused.
 * Shows the masked phone only, as the list does.
 */
import { randomUUID } from "expo-crypto";
import { Redirect, useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { Text, TextInput, View } from "react-native";

import { useAppState } from "../src/AppState";
import {
  CONTACT_OUTCOMES,
  deleteAction,
  discardRegistration,
  getCase,
  getRegistration,
  listActions,
  queueAction,
  visitAt,
  type CaseAction,
  type CaseRow,
  type ContactOutcome,
  type Registration
} from "../src/cases";
import { draftForCase, type Db, type DraftRow } from "../src/drafts";
import { t, type StringKey } from "../src/i18n";
import { isUnlocked, openInterviewerDb } from "../src/interviewerDb";
import { Button, Row, Screen, stateLabel, styles } from "../src/ui";

export default function Case() {
  const router = useRouter();
  const params = useLocalSearchParams<{ userId: string; deathId?: string; clientDeathId?: string }>();
  const { accounts } = useAppState();
  const account = accounts.find((a) => a.user_id === params.userId);
  const [db, setDb] = useState<Db | undefined>();
  const [found, setFound] = useState<CaseRow | undefined>();
  const [registration, setRegistration] = useState<Registration | undefined>();
  const [draft, setDraft] = useState<DraftRow | null>(null);
  const [actions, setActions] = useState<CaseAction[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [mode, setMode] = useState<"attempt" | "visit" | undefined>();
  const [editingId, setEditingId] = useState<string | undefined>();
  const [outcome, setOutcome] = useState<ContactOutcome | undefined>();
  const [date, setDate] = useState("");
  const [message, setMessage] = useState("");
  const { deathId, clientDeathId } = params;

  const load = useCallback(
    async (handle: Db) => {
      const [row, reg, local, queued] = await Promise.all([
        deathId ? getCase(handle, deathId) : Promise.resolve(undefined),
        clientDeathId ? getRegistration(handle, clientDeathId) : Promise.resolve(undefined),
        draftForCase(handle, { deathId, clientDeathId }),
        listActions(handle)
      ]);
      setFound(row);
      setRegistration(reg);
      setDraft(local);
      setActions(
        queued.filter((a) => (deathId && a.death_id === deathId) || (clientDeathId && a.client_death_id === clientDeathId))
      );
      setLoaded(true);
    },
    [deathId, clientDeathId]
  );

  useFocusEffect(
    useCallback(() => {
      if (!account) return;
      void (async () => {
        const handle = await openInterviewerDb(account.user_id).catch(() => undefined);
        if (!handle) return;
        setDb(handle);
        await load(handle);
      })();
    }, [account, load])
  );

  if (!account) return <Redirect href="/" />;
  if (!isUnlocked(account.user_id)) {
    return <Redirect href={{ pathname: "/unlock", params: { userId: account.user_id } }} />;
  }
  if (loaded && !found && !registration) {
    return (
      <Screen title={t("caseTitle")}>
        <Text style={styles.text}>{t("caseMissing")}</Text>
        <Button kind="secondary" label={t("home")} onPress={() => router.back()} />
      </Screen>
    );
  }

  const name = found?.deceased_name ?? registration?.fields.deceased_name ?? "";

  function startInterview() {
    if (!account) return;
    router.push({
      pathname: "/form",
      params: {
        userId: account.user_id,
        draftId: draft?.id ?? randomUUID(),
        ...(deathId ? { deathId } : { clientDeathId: clientDeathId ?? "" })
      }
    });
  }

  function openForm(kind: "attempt" | "visit", action?: CaseAction) {
    setMode(kind);
    setEditingId(action?.client_id);
    setOutcome(action?.body.outcome);
    setDate(action?.body.next_visit_at ? action.body.next_visit_at.slice(0, 10) : "");
    setMessage("");
  }

  async function saveAction() {
    if (!db || !mode) return;
    const at = date.trim() ? visitAt(date.trim()) : null;
    const day = 86_400_000;
    const time = at ? new Date(at).getTime() : 0;
    // The server takes yesterday to a year ahead (web_intake_service._clean_visit_at).
    if ((date.trim() && !at) || (mode === "visit" && !at) || (at && (time < Date.now() - day || time > Date.now() + 365 * day))) {
      setMessage(t("errVisitDate"));
      return;
    }
    if (mode === "attempt" && !outcome) {
      setMessage(t("errRequired"));
      return;
    }
    await queueAction(db, {
      client_id: editingId ?? randomUUID(),
      kind: mode,
      death_id: deathId ?? null,
      client_death_id: clientDeathId ?? null,
      body: mode === "attempt" ? { outcome, ...(at && outcome !== "refused" ? { next_visit_at: at } : {}) } : { next_visit_at: at }
    });
    setMode(undefined);
    setMessage(t("queued"));
    await load(db);
  }

  async function discard(action: CaseAction) {
    if (!db) return;
    await deleteAction(db, action.client_id);
    await load(db);
  }

  async function discardThisRegistration() {
    if (!db || !clientDeathId) return;
    await discardRegistration(db, clientDeathId);
    router.back();
  }

  return (
    <Screen title={name || t("caseTitle")}>
      {found ? (
        <View style={{ gap: 4 }}>
          <Text style={styles.muted}>
            {found.unique_id} · {stateLabel(found.state)}
            {found.unit_name ? ` · ${found.unit_name}` : ""}
          </Text>
          {found.next_visit_at ? (
            <Text style={styles.muted}>{t("nextVisit", { date: new Date(found.next_visit_at).toLocaleDateString() })}</Text>
          ) : null}
          {found.informant_phone_masked ? (
            <Text style={styles.muted}>{t("phoneMasked", { phone: found.informant_phone_masked })}</Text>
          ) : null}
        </View>
      ) : null}
      {registration ? (
        <View style={{ gap: 4 }}>
          <Text style={registration.state === "needs_edit" ? styles.error : styles.muted}>
            {registration.state === "needs_edit" ? t("needsEdit") : t("pendingSend")}
          </Text>
          <Row>
            <Button
              kind="secondary"
              label={t("editRegistration")}
              onPress={() =>
                router.push({ pathname: "/register", params: { userId: account.user_id, clientDeathId: clientDeathId ?? "" } })
              }
            />
            {registration.state === "needs_edit" ? (
              <Button kind="danger" label={t("discard")} onPress={() => void discardThisRegistration()} />
            ) : null}
          </Row>
        </View>
      ) : null}
      <Button
        label={draft ? t("resumeInterview") : t("startInterview")}
        disabled={!db || draft?.completed === 1}
        onPress={startInterview}
      />
      {mode ? (
        <View style={{ gap: 8 }}>
          {mode === "attempt" ? (
            <Row>
              {CONTACT_OUTCOMES.map((value) => (
                <Button
                  key={value}
                  kind={outcome === value ? "primary" : "secondary"}
                  label={t(`outcome_${value}` as StringKey)}
                  onPress={() => setOutcome(value)}
                />
              ))}
            </Row>
          ) : null}
          {mode === "visit" || outcome !== "refused" ? (
            <>
              <Text style={styles.muted}>{t("visitDate")}</Text>
              <TextInput style={styles.input} autoCorrect={false} value={date} onChangeText={setDate} />
            </>
          ) : null}
          <Row>
            <Button label={t("save")} onPress={() => void saveAction()} />
            <Button kind="secondary" label={t("cancel")} onPress={() => setMode(undefined)} />
          </Row>
        </View>
      ) : (
        <Row>
          <Button kind="secondary" label={t("logAttempt")} disabled={!db} onPress={() => openForm("attempt")} />
          <Button kind="secondary" label={t("setVisit")} disabled={!db} onPress={() => openForm("visit")} />
        </Row>
      )}
      {message ? <Text style={styles.text}>{message}</Text> : null}
      {actions.map((action) => (
        <View key={action.client_id} style={styles.card}>
          <Text style={styles.text}>
            {action.kind === "attempt"
              ? t("actionAttempt", { outcome: t(`outcome_${action.body.outcome}` as StringKey) })
              : t("actionVisit", {
                  date: action.body.next_visit_at ? new Date(action.body.next_visit_at).toLocaleDateString() : "-"
                })}
          </Text>
          <Text style={action.state === "needs_edit" ? styles.error : styles.muted}>
            {action.state === "needs_edit" ? t("needsEdit") : t("pendingSend")}
          </Text>
          {action.state === "needs_edit" ? (
            <Row>
              <Button kind="secondary" label={t("edit")} onPress={() => openForm(action.kind, action)} />
              <Button kind="danger" label={t("discard")} onPress={() => void discard(action)} />
            </Row>
          ) : null}
        </View>
      ))}
      <Button kind="secondary" label={t("home")} onPress={() => router.back()} />
    </Screen>
  );
}
