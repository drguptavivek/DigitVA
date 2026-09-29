/**
 * One interviewer's in-flight interviews, "New interview" (site/unit from the
 * cached bootstrap), send completed interviews, and sign out.
 */
import { randomUUID } from "expo-crypto";
import { Redirect, useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { Alert, Pressable, Text, View } from "react-native";

import { useAppState } from "../src/AppState";
import { SessionRevokedError, signOut } from "../src/auth";
import { getMeta, listDrafts, type Db, type DraftRow } from "../src/drafts";
import { t } from "../src/i18n";
import { openInterviewerDb } from "../src/interviewerDb";
import { refreshBootstrap, syncInterviewer, type Bootstrap } from "../src/sync";
import { Button, errorText, Row, Screen, styles } from "../src/ui";

interface Target {
  key: string;
  label: string;
  siteId: string;
  orgUnitId?: string;
}

function targetsFrom(bootstrap: Bootstrap | undefined): Target[] {
  return (bootstrap?.context ?? []).flatMap((entry) => {
    const site = entry.site_name ?? entry.site_id;
    const units = entry.org_units ?? [];
    if (units.length === 0) return [{ key: entry.site_id, label: site, siteId: entry.site_id }];
    return units.map((unit) => ({
      key: `${entry.site_id}:${unit.org_unit_id}`,
      label: `${site} · ${unit.unit_name ?? unit.unit_code ?? ""}`,
      siteId: entry.site_id,
      orgUnitId: unit.org_unit_id
    }));
  });
}

export default function Worklist() {
  const router = useRouter();
  const { userId } = useLocalSearchParams<{ userId: string }>();
  const { accounts, reload } = useAppState();
  const account = accounts.find((a) => a.user_id === userId);
  const [db, setDb] = useState<Db | undefined>();
  const [drafts, setDrafts] = useState<DraftRow[]>([]);
  const [bootstrap, setBootstrap] = useState<Bootstrap | undefined>();
  const [picking, setPicking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const handleError = useCallback(
    async (error: unknown) => {
      if (error instanceof SessionRevokedError) {
        Alert.alert(t("sessionRevoked"));
        await reload();
        router.replace("/");
        return;
      }
      setMessage(errorText(error));
    },
    [reload, router]
  );

  useFocusEffect(
    useCallback(() => {
      if (!account) return;
      let active = true;
      void (async () => {
        const handle = await openInterviewerDb(account.user_id);
        if (!active) return;
        setDb(handle);
        setDrafts(await listDrafts(handle));
        const cached = await getMeta<Bootstrap>(handle, "bootstrap");
        if (!active) return;
        setBootstrap(cached);
        if (cached) return;
        try {
          const fresh = await refreshBootstrap(account.user_id, handle);
          if (active) setBootstrap(fresh);
        } catch (error) {
          if (active) await handleError(error);
        }
      })();
      return () => {
        active = false;
      };
    }, [account, handleError])
  );

  if (!account) return <Redirect href="/" />;

  async function refresh() {
    if (!db || !account) return;
    setBusy(true);
    setMessage("");
    try {
      setBootstrap(await refreshBootstrap(account.user_id, db));
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
      setDrafts(await listDrafts(db));
    } catch (error) {
      await handleError(error);
    } finally {
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
    if (drafts.length === 0) {
      void doSignOut();
      return;
    }
    Alert.alert(t("signOut"), t("signOutUnsent", { count: drafts.length }), [
      { text: t("cancel"), style: "cancel" },
      { text: t("signOutConfirm"), style: "destructive", onPress: () => void doSignOut() }
    ]);
  }

  const targets = targetsFrom(bootstrap);
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
        <Button label={t("newInterview")} disabled={!db} onPress={() => setPicking(true)} />
      )}
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
            {new Date(draft.updated_at).toLocaleString()} · {draft.id.slice(0, 8)}
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
        <Button kind="danger" label={t("signOut")} disabled={busy} onPress={confirmSignOut} />
      </Row>
    </Screen>
  );
}
