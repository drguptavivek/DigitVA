/**
 * One interviewer's in-flight work: the cases downloaded for offline visits,
 * deaths registered on this phone and not yet sent, and interviews on this
 * phone. "New interview" (site/unit from the cached bootstrap), "Register a
 * death", sync (send everything, then refresh the case list), lock, and
 * sign out. Reached only while the interviewer's store is unlocked.
 */
import { randomUUID } from "expo-crypto";
import { Redirect, useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { Alert, Pressable, Text, View } from "react-native";

import { useAppState } from "../src/AppState";
import { SessionRevokedError, SignInRequiredError, signOut } from "../src/auth";
import { listActions, listCases, listRegistrations, type CaseRow, type Registration } from "../src/cases";
import { getMeta, listDrafts, type Db, type DraftRow } from "../src/drafts";
import { t } from "../src/i18n";
import { isUnlocked, openInterviewerDb } from "../src/interviewerDb";
import {
  refreshBootstrap,
  refreshCases,
  registersDeaths,
  syncInterviewer,
  targetsFrom,
  type Bootstrap,
  type Units
} from "../src/sync";
import { Button, errorText, Row, Screen, stateLabel, styles } from "../src/ui";

export default function Worklist() {
  const router = useRouter();
  const { userId } = useLocalSearchParams<{ userId: string }>();
  const { accounts, reload, lockNow } = useAppState();
  const account = accounts.find((a) => a.user_id === userId);
  const [db, setDb] = useState<Db | undefined>();
  const [drafts, setDrafts] = useState<DraftRow[]>([]);
  const [cases, setCases] = useState<CaseRow[]>([]);
  const [registrations, setRegistrations] = useState<Registration[]>([]);
  const [queued, setQueued] = useState(0);
  const [bootstrap, setBootstrap] = useState<Bootstrap | undefined>();
  const [units, setUnits] = useState<Units | null | undefined>();
  const [picking, setPicking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const loadLocal = useCallback(async (handle: Db) => {
    const [d, c, r, a] = await Promise.all([
      listDrafts(handle),
      listCases(handle),
      listRegistrations(handle),
      listActions(handle)
    ]);
    setDrafts(d);
    setCases(c);
    setRegistrations(r);
    setQueued(a.length);
  }, []);

  const handleError = useCallback(
    async (error: unknown) => {
      if (error instanceof SessionRevokedError) {
        Alert.alert(t("sessionRevoked"));
        await reload();
        router.replace("/");
        return;
      }
      // Tokens dropped, data kept: the home screen now flags this account.
      if (error instanceof SignInRequiredError) await reload();
      setMessage(errorText(error));
    },
    [reload, router]
  );

  useFocusEffect(
    useCallback(() => {
      if (!account) return;
      let active = true;
      void (async () => {
        const handle = await openInterviewerDb(account.user_id).catch(() => undefined);
        if (!active || !handle) return;
        setDb(handle);
        await loadLocal(handle);
        const cached = await getMeta<Bootstrap>(handle, "bootstrap");
        const cachedUnits = await getMeta<Units | null>(handle, "units");
        if (!active) return;
        setBootstrap(cached);
        setUnits(cachedUnits);
        if (cached && cachedUnits !== undefined) return;
        try {
          const fresh = await refreshBootstrap(account.user_id, handle);
          if (active) {
            setBootstrap(fresh.bootstrap);
            setUnits(fresh.units ?? null);
          }
        } catch (error) {
          if (active) await handleError(error);
        }
      })();
      return () => {
        active = false;
      };
    }, [account, handleError, loadLocal])
  );

  if (!account) return <Redirect href="/" />;
  if (!isUnlocked(account.user_id)) {
    return <Redirect href={{ pathname: "/unlock", params: { userId: account.user_id } }} />;
  }

  async function refresh() {
    if (!db || !account) return;
    setBusy(true);
    setMessage("");
    try {
      const fresh = await refreshBootstrap(account.user_id, db);
      setBootstrap(fresh.bootstrap);
      setUnits(fresh.units ?? null);
      await refreshCases(account.user_id, db);
      await loadLocal(db);
    } catch (error) {
      await handleError(error);
    } finally {
      setBusy(false);
    }
  }

  async function send() {
    if (!db || !account) return;
    setBusy(true);
    setMessage("");
    try {
      const result = await syncInterviewer(account.user_id, db);
      setMessage(t("syncResult", { ...result }));
    } catch (error) {
      await handleError(error);
    } finally {
      await loadLocal(db).catch(() => undefined);
      setBusy(false);
    }
  }

  function confirmSignOut() {
    if (!account) return;
    const doSignOut = async () => {
      await signOut(account.user_id);
      await reload();
      router.replace("/");
    };
    const unsent = drafts.length + registrations.length + queued;
    if (unsent === 0) {
      void doSignOut();
      return;
    }
    Alert.alert(t("signOut"), t("signOutUnsent", { count: unsent }), [
      { text: t("cancel"), style: "cancel" },
      { text: t("signOutConfirm"), style: "destructive", onPress: () => void doSignOut() }
    ]);
  }

  const targets = targetsFrom(bootstrap, units);
  return (
    <Screen title={t("worklistTitle")}>
      <Text style={styles.muted}>{account.name}</Text>
      {picking ? (
        <View style={{ gap: 8 }}>
          <Text style={styles.text}>{t("chooseSite")}</Text>
          {targets.length === 0 ? <Text style={styles.muted}>{t("noSites")}</Text> : null}
          {targets.map((target) => (
            <Button
              key={target.key}
              kind="secondary"
              label={target.label}
              onPress={() => {
                setPicking(false);
                router.push({
                  pathname: "/form",
                  params: {
                    userId: account.user_id,
                    draftId: randomUUID(),
                    siteId: target.siteId,
                    ...(target.orgUnitId ? { orgUnitId: target.orgUnitId } : {})
                  }
                });
              }}
            />
          ))}
          <Button kind="secondary" label={t("cancel")} onPress={() => setPicking(false)} />
        </View>
      ) : (
        <Row>
          <Button label={t("newInterview")} disabled={!db} onPress={() => setPicking(true)} />
          <Button
            kind="secondary"
            label={t("registerDeath")}
            disabled={!db || !registersDeaths(bootstrap)}
            onPress={() => router.push({ pathname: "/register", params: { userId: account.user_id } })}
          />
        </Row>
      )}
      <Text style={styles.text} accessibilityRole="header">
        {t("casesTitle")}
      </Text>
      {cases.length === 0 ? <Text style={styles.muted}>{t("noCases")}</Text> : null}
      {cases.map((row) => (
        <Pressable
          key={row.death_id}
          accessibilityRole="button"
          style={styles.card}
          onPress={() => router.push({ pathname: "/case", params: { userId: account.user_id, deathId: row.death_id } })}
        >
          <Text style={styles.text}>{row.deceased_name ?? row.unique_id}</Text>
          <Text style={styles.muted}>
            {row.unique_id} · {stateLabel(row.state)}
            {row.next_visit_at ? ` · ${t("nextVisit", { date: new Date(row.next_visit_at).toLocaleDateString() })}` : ""}
          </Text>
        </Pressable>
      ))}
      {registrations.length > 0 ? (
        <Text style={styles.text} accessibilityRole="header">
          {t("registrationsTitle")}
        </Text>
      ) : null}
      {registrations.map((reg) => (
        <Pressable
          key={reg.client_death_id}
          accessibilityRole="button"
          style={styles.card}
          onPress={() =>
            router.push({ pathname: "/case", params: { userId: account.user_id, clientDeathId: reg.client_death_id } })
          }
        >
          <Text style={styles.text}>{reg.fields.deceased_name}</Text>
          <Text style={reg.state === "needs_edit" ? styles.error : styles.muted}>
            {reg.state === "needs_edit" ? t("needsEdit") : t("pendingSend")}
          </Text>
        </Pressable>
      ))}
      <Text style={styles.text} accessibilityRole="header">
        {t("interviewsTitle")}
      </Text>
      {drafts.length === 0 ? <Text style={styles.muted}>{t("noDrafts")}</Text> : null}
      {drafts.map((draft) => (
        <Pressable
          key={draft.id}
          accessibilityRole="button"
          disabled={draft.completed === 1}
          style={styles.card}
          onPress={() =>
            router.push({ pathname: "/form", params: { userId: account.user_id, draftId: draft.id } })
          }
        >
          <Text style={styles.text}>{draft.completed ? t("draftReady") : t("draftInProgress")}</Text>
          <Text style={styles.muted}>
            {new Date(draft.updated_at).toLocaleString()} · {draft.unique_id ?? draft.id.slice(0, 8)}
          </Text>
        </Pressable>
      ))}
      <Row>
        <Button label={t("sync")} disabled={busy || !db} onPress={() => void send()} />
        <Button kind="secondary" label={t("refresh")} disabled={busy || !db} onPress={() => void refresh()} />
      </Row>
      {message ? <Text style={styles.text}>{message}</Text> : null}
      <Row>
        <Button kind="secondary" label={t("home")} onPress={() => router.replace("/")} />
        <Button kind="secondary" label={t("lockNow")} disabled={busy} onPress={() => void lockNow()} />
        <Button kind="danger" label={t("signOut")} disabled={busy} onPress={confirmSignOut} />
      </Row>
    </Screen>
  );
}
