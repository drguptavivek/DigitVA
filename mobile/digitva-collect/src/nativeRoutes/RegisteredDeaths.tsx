/** A reporter's own registrations, loaded in bounded pages. */
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { AppState, Text, TextInput } from "react-native";

import { signOut } from "../auth";
import { getNativeRegisteredDeaths } from "../deathRegistrationApi";
import { useAppState } from "../AppState";
import { t } from "../i18n";
import { confirmSignOut as confirmUnsentSignOut } from "../signOutConfirm";
import type { CaseRow, RegisteredDeathCounts } from "../api";
import { Button, Row, Screen, useUiStyles } from "../ui";
import { CaseCard } from "../ui/CaseCard";
import { caseNumberLabel, caseSupportText } from "../ui/caseSupport";
import { deathStateBadge, diedText } from "../ui/interviewRows";
import { callInformant } from "./callInformant";
import { deathPhoneUrl } from "../deathWorkflow";
import { OfflineNotice, SkeletonCards, StateView } from "../ui/StateView";
import { isUnlocked } from "../interviewerDb";

type Stage = "all" | "waiting" | "interviewed";
/** Delay before a typed case id is sent: the list is read on the server. */
const SEARCH_DEBOUNCE_MS = 300;

export default function RegisteredDeaths({
  userId,
  registeredMine,
  projectId,
}: {
  userId: string;
  registeredMine: boolean;
  /** The training project when opened in training mode: the list asks for the training scope. */
  projectId?: string;
}) {
  const router = useRouter();
  const styles = useUiStyles();
  const { accounts, lockNow, reload, lockVersion, offline } = useAppState();
  const account = accounts.find((item) => item.user_id === userId);
  const ownerKey = `${userId}:${registeredMine ? "mine" : "all"}:${projectId ?? ""}`;
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
  const [stage, setStage] = useState<Stage>("all");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [counts, setCounts] = useState<RegisteredDeathCounts>();
  const [cursor, setCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [callingId, setCallingId] = useState<string>();
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
      const page = await getNativeRegisteredDeaths(userId, registeredMine, nextCursor, projectId, {
        ...(stage === "all" ? {} : { stage }),
        ...(query ? { q: query } : {}),
      });
      if (request !== generation.current || !current(ownerKey)) return;
      pageCursorByDeath.current = {
        ...pageCursorByDeath.current,
        ...Object.fromEntries(page.deaths.map((death) => [death.death_id, nextCursor ?? undefined])),
      };
      setDeaths((rows) => nextCursor ? [...rows, ...page.deaths] : page.deaths);
      setDeathsOwner(ownerKey);
      setCursor(page.next_cursor);
      setCounts(page.counts);
    } catch {
      if (request === generation.current && current(ownerKey)) setMessage(t("errGeneric"));
    } finally {
      if (request === generation.current) setBusy(false);
    }
  }, [current, ownerKey, projectId, query, registeredMine, stage, userId]);

  // A new chip or search changes `load`, so the focus effect below reloads from the first page; the generation
  // guard drops a slower answer of the earlier filter.
  useEffect(() => {
    const next = search.trim();
    if (next === query) return;
    const timer = setTimeout(() => setQuery(next), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query, search]);

  useFocusEffect(useCallback(() => {
    focused.current = true;
    void load();
    return () => {
      focused.current = false;
      // The list stays for the way back (it is cleared on lock or account change); a late answer is dropped.
      generation.current += 1;
      setMessage("");
    };
  }, [load]));

  useEffect(() => {
    if (!isUnlocked(userId) || !account?.registered_deaths_access) {
      generation.current += 1;
      setDeaths([]);
      setDeathsOwner(undefined);
      pageCursorByDeath.current = {};
      setCursor(null);
      setCounts(undefined);
    }
  }, [account?.registered_deaths_access, lockVersion, userId]);

  useEffect(() => {
    const subscription = AppState.addEventListener("change", (next) => {
      appState.current = next;
      if (next !== "active") {
        generation.current += 1;
        return;
      }
      if (focused.current && isUnlocked(userId)) void load();
    });
    return () => subscription.remove();
  }, [load, userId]);

  async function doSignOut() {
    try {
      if (!(await lockNow())) {
        setMessage(t("errGeneric"));
        return;
      }
      await signOut(userId);
      await reload();
      router.replace("/");
    } catch {
      setMessage(t("errGeneric"));
    }
  }

  /**
   * The reporter's own list (serialize_death) carries the informant's numbers, not the worklist's
   * has_informant_phone flags: dial the row's first dialable number. The number is never rendered or logged.
   */
  function rowPhone(death: CaseRow): string | undefined {
    const row = death as { informant_phone?: unknown; informant_phone_2?: unknown };
    return [row.informant_phone, row.informant_phone_2].find((p): p is string => typeof p === "string" && Boolean(deathPhoneUrl(p)));
  }

  async function callDeath(death: CaseRow) {
    if (callingId) return;
    setCallingId(death.death_id);
    try {
      if (!(await callInformant(userId, death.death_id, death.project_id, rowPhone(death)))) setMessage(t("errGeneric"));
    } catch {
      setMessage(t("errGeneric"));
    } finally {
      setCallingId(undefined);
    }
  }

  function confirmSignOut() {
    void confirmUnsentSignOut(userId, () => void doSignOut());
  }

  if (!account) return null;
  if (!isUnlocked(userId)) return null;
  if (!account.registered_deaths_access || !current(ownerKey)) return null;

  const visibleDeaths = deathsOwner === ownerKey ? deaths : [];
  const visibleCursor = deathsOwner === ownerKey ? cursor : null;

  return (
    <Screen title={t("reportedDeaths")}>
      <Text style={styles.muted}>{account?.name}</Text>
      <Button label={t("newDeath")} onPress={() => router.push({ pathname: "/register", params: { userId } })} />
      {offline ? <OfflineNotice /> : null}
      <Button kind="secondary" label={t("refresh")} loading={busy} disabled={Boolean(offline)} onPress={() => void load()} />
      {offline ? <Text style={styles.muted}>{t("refreshNeedsConnection")}</Text> : null}
      <TextInput
        style={styles.input}
        value={search}
        onChangeText={setSearch}
        placeholder={t("searchCaseId")}
        accessibilityLabel={t("searchCaseId")}
        autoCapitalize="characters"
        autoCorrect={false}
        maxLength={128}
        returnKeyType="search"
      />
      <Row>
        {(["all", "waiting", "interviewed"] as const).map((chip) => {
          const label = chip === "all" ? t("deathsChipAll") : t(chip === "waiting" ? "badgeWaitingInterview" : "badgeInterviewed");
          return (
            <Button
              key={chip}
              kind={stage === chip ? "primary" : "secondary"}
              label={counts ? `${label} · ${counts[chip]}` : label}
              onPress={() => setStage(chip)}
            />
          );
        })}
      </Row>
      {message ? <StateView kind="error" title={t("stateErrorTitle")} hint={message} actionLabel={t("refresh")} onAction={() => void load()} /> : null}
      {visibleDeaths.length === 0 && busy && !message ? <SkeletonCards count={2} /> : null}
      {visibleDeaths.length === 0 && !busy && !message && (stage !== "all" || query)
        ? <StateView title={t("stateNoDeathsMatchTitle")} hint={t("stateNoDeathsMatchHint")} /> : null}
      {visibleDeaths.length === 0 && !busy && !message && stage === "all" && !query ? <StateView title={t("stateNoDeathsTitle")} hint={t("stateNoDeathsHint")} actionLabel={t("newDeath")} onAction={() => router.push({ pathname: "/register", params: { userId } })} /> : null}
      {visibleDeaths.map((death) => {
        const area = death.unit_name ?? death.org_unit_name ?? undefined;
        const badge = deathStateBadge(death.status ?? death.state ?? "");
        const caseId = caseNumberLabel(death.unique_id);
        const yearOnly = (death as { date_of_death_year_only?: unknown }).date_of_death_year_only === true;
        return (
          <CaseCard
            key={death.death_id}
            idBelowTitle
            title={death.deceased_name ?? death.unique_id}
            caseId={caseId}
            ageYears={death.age_years}
            sex={death.deceased_sex}
            dateOfDeath={diedText(death.date_of_death, yearOnly)}
            area={area}
            latitude={death.latitude}
            longitude={death.longitude}
            badges={[badge]}
            copyText={caseSupportText({ caseId: death.unique_id, projectId: death.project_id, unit: area, ageYears: death.age_years, sex: death.deceased_sex, status: badge.label })}
            copyLabel={t("queueCopyDetails", { case: caseId })}
            onCall={rowPhone(death) || death.has_informant_phone || death.has_informant_phone_2 ? () => void callDeath(death) : undefined}
            callBusy={callingId === death.death_id}
            actions={(
              <Button kind="secondary" label={t("editRegistration")} onPress={() => router.push({
                pathname: "/register",
                params: {
                  userId,
                  deathId: death.death_id,
                  registrationSource: "mine",
                  ...(death.project_id ? { projectId: death.project_id } : {}),
                  ...(pageCursorByDeath.current[death.death_id] ? { registrationCursor: pageCursorByDeath.current[death.death_id] } : {}),
                },
              })} />
            )}
          />
        );
      })}
      {visibleCursor ? <Button kind="secondary" label={t("loadMore")} loading={busy} onPress={() => void load(visibleCursor)} /> : null}
      {!account.collection_access ? <Button kind="danger" label={t("signOut")} onPress={confirmSignOut} /> : null}
    </Screen>
  );
}
