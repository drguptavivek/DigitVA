/** A reporter's own registrations, loaded in bounded pages. */
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, AppState, Text, View } from "react-native";

import { signOut } from "../auth";
import { getNativeRegisteredDeaths } from "../deathRegistrationApi";
import { useAppState } from "../AppState";
import { t } from "../i18n";
import type { CaseRow } from "../api";
import { Button, Screen, useUiStyles } from "../ui";
import { isUnlocked } from "../interviewerDb";

export default function RegisteredDeaths({
  userId,
  registeredMine,
}: {
  userId: string;
  registeredMine: boolean;
}) {
  const router = useRouter();
  const styles = useUiStyles();
  const { accounts, lockNow, reload, lockVersion } = useAppState();
  const account = accounts.find((item) => item.user_id === userId);
  const ownerKey = `${userId}:${registeredMine ? "mine" : "all"}`;
  const renderContextRef = useRef({
    ownerKey,
    userId,
    canRead: account?.user_id === userId && account.registered_deaths_access,
  });
  renderContextRef.current = {
    ownerKey,
    userId,
    canRead: account?.user_id === userId && account.registered_deaths_access,
  };
  const [deaths, setDeaths] = useState<CaseRow[]>([]);
  const [deathsOwner, setDeathsOwner] = useState<string>();
  const [cursor, setCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const pageCursorByDeath = useRef<Record<string, string | undefined>>({});
  const generation = useRef(0);
  const focused = useRef(false);
  const appState = useRef(AppState.currentState);
  const current = useCallback((expectedOwner: string) => {
    const latest = renderContextRef.current;
    return focused.current && appState.current === "active" && latest.ownerKey === expectedOwner &&
      latest.canRead && isUnlocked(latest.userId);
  }, []);

  const load = useCallback(async (nextCursor?: string | null) => {
    if (!current(ownerKey)) return;
    const request = ++generation.current;
    setBusy(true);
    setMessage("");
    try {
      const page = await getNativeRegisteredDeaths(userId, registeredMine, nextCursor);
      if (request !== generation.current || !current(ownerKey)) return;
      pageCursorByDeath.current = {
        ...pageCursorByDeath.current,
        ...Object.fromEntries(page.deaths.map((death) => [death.death_id, nextCursor ?? undefined])),
      };
      setDeaths((rows) => nextCursor ? [...rows, ...page.deaths] : page.deaths);
      setDeathsOwner(ownerKey);
      setCursor(page.next_cursor);
    } catch {
      if (request === generation.current && current(ownerKey)) setMessage(t("errGeneric"));
    } finally {
      if (request === generation.current) setBusy(false);
    }
  }, [current, ownerKey, registeredMine, userId]);

  useFocusEffect(useCallback(() => {
    focused.current = true;
    void load();
    return () => {
      focused.current = false;
      generation.current += 1;
      setDeaths([]);
      setDeathsOwner(undefined);
      pageCursorByDeath.current = {};
      setCursor(null);
      setMessage("");
    };
  }, [load]));

  useEffect(() => {
    if (!isUnlocked(userId) || !account?.registered_deaths_access) {
      generation.current += 1;
      setDeaths([]);
      setDeathsOwner(undefined);
      setCursor(null);
    }
  }, [account?.registered_deaths_access, lockVersion, userId]);

  useEffect(() => {
    const subscription = AppState.addEventListener("change", (next) => {
      appState.current = next;
      if (next !== "active") {
        generation.current += 1;
        setDeaths([]);
        setDeathsOwner(undefined);
        pageCursorByDeath.current = {};
        setCursor(null);
        return;
      }
      if (focused.current && isUnlocked(userId)) void load();
    });
    return () => subscription.remove();
  }, [load, userId]);

  async function doSignOut() {
    try {
      await signOut(userId);
      await reload();
      router.replace("/");
    } catch {
      setMessage(t("errGeneric"));
    }
  }

  function confirmSignOut() {
    Alert.alert(t("signOut"), t("pendingSignOutConfirm"), [
      { text: t("cancel"), style: "cancel" },
      { text: t("signOutConfirm"), style: "destructive", onPress: () => void doSignOut() },
    ]);
  }

  if (!account) return null;
  if (!isUnlocked(userId)) return null;
  if (!account.registered_deaths_access || !current(ownerKey)) return null;

  const visibleDeaths = deathsOwner === ownerKey ? deaths : [];
  const visibleCursor = deathsOwner === ownerKey ? cursor : null;

  return (
    <Screen title={t("reportedDeaths")}>
      <Text style={styles.muted}>{account?.name}</Text>
      {account.collection_access ? (
        <Button kind="secondary" label={t("worklistTitle")} onPress={() => router.replace({ pathname: "/worklist", params: { userId } })} />
      ) : null}
      <Button label={t("newDeath")} onPress={() => router.push({ pathname: "/register", params: { userId } })} />
      <Button kind="secondary" label={t("refresh")} loading={busy} onPress={() => void load()} />
      {message ? <Text style={styles.error}>{message}</Text> : null}
      {visibleDeaths.length === 0 && !busy ? <Text style={styles.muted}>{t("noReportedDeaths")}</Text> : null}
      {visibleDeaths.map((death) => (
        <View key={death.death_id} style={styles.card}>
          <Text style={styles.text}>{death.deceased_name ?? death.unique_id}</Text>
          <Text style={styles.muted}>
            {death.unique_id}{death.date_of_death ? ` · ${death.date_of_death}` : ""}
            {death.unit_name || death.org_unit_name ? ` · ${death.unit_name ?? death.org_unit_name}` : ""}
          </Text>
          <Button kind="secondary" label={t("editRegistration")} onPress={() => router.push({
            pathname: "/register",
            params: {
              userId,
              deathId: death.death_id,
              registrationSource: "mine",
              ...(pageCursorByDeath.current[death.death_id] ? { registrationCursor: pageCursorByDeath.current[death.death_id] } : {}),
            },
          })} />
        </View>
      ))}
      {visibleCursor ? <Button kind="secondary" label={t("loadMore")} loading={busy} onPress={() => void load(visibleCursor)} /> : null}
      <Button kind="secondary" label={t("lockNow")} onPress={() => void lockNow()} />
      {!account.collection_access ? <Button kind="danger" label={t("signOut")} onPress={confirmSignOut} /> : null}
    </Screen>
  );
}
