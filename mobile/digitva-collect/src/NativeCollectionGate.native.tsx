import { Redirect, useGlobalSearchParams, usePathname, useRouter } from "expo-router";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { ActivityIndicator, Text, View } from "react-native";

import { useAppState } from "./AppState";
import { refreshAccessSummary } from "./auth";
import { t } from "./i18n";
import { ClockBlock } from "./nativeShell/ClockNotice";
import { usePhoneClock } from "./phoneClock";
import { isUnlocked, openInterviewerDb, unsentWorkCount } from "./interviewerDb";
import { uploadQueuedWork } from "./sync";
import { Button, errorText, Screen, useUiStyles } from "./ui";

const COLLECTION_ROUTES = new Set([
  "/case",
  "/collection",
  "/form",
  "/interview",
  "/revision",
]);
const REGISTRATION_ROUTES = new Set(["/death-registration", "/register"]);
const WORKLIST_ROUTE = "/worklist";
/** Data entry: blocked while the phone clock is more than 4 hours off. Viewing and sending are not. */
const ENTRY_ROUTES = new Set(["/death-registration", "/register", "/form", "/interview", "/revision"]);

/**
 * Keep account controls available while collection is disabled. Unsent work
 * is counted and can still be sent while the session lasts; an account that
 * needs sign-in (or lost its access with work unsent) is offered "Sign in
 * again", which keeps the store, rather than only a wiping sign-out.
 */
function NativePendingWorkspace({ userId }: { userId: string }) {
  const router = useRouter();
  const { accounts, reload } = useAppState();
  const styles = useUiStyles();
  const [message, setMessage] = useState<string>();
  const [unsent, setUnsent] = useState<number>();
  const [sending, setSending] = useState(false);
  const account = accounts.find((item) => item.user_id === userId);
  const unlocked = isUnlocked(userId);

  const recount = useCallback(async () => {
    try {
      setUnsent(await unsentWorkCount(userId));
    } catch {
      setUnsent(undefined);
    }
  }, [userId]);

  useEffect(() => {
    void recount();
  }, [recount, unlocked]);

  async function sendUnsent() {
    setSending(true);
    setMessage(undefined);
    try {
      const result = await uploadQueuedWork(userId, await openInterviewerDb(userId));
      await recount();
      setMessage(t("syncResult", { sent: result.sent, failed: result.failed, remaining: (await unsentWorkCount(userId)) ?? 0 }));
    } catch (error) {
      setMessage(errorText(error));
      await reload();
    } finally {
      setSending(false);
    }
  }

  return (
    <Screen title={account?.name ?? t("accountsTitle")}>
      {account?.access_removed ? (
        <Text style={styles.error}>
          {unsent === undefined ? t("accessRemovedLocked") : t("accessRemovedUnsent", { count: unsent })}
        </Text>
      ) : unsent ? (
        <Text style={styles.text}>{t("unsentWaiting", { count: unsent })}</Text>
      ) : null}
      {account?.needs_sign_in ? (
        <Button label={t("signInAgainAction")} onPress={() => router.push({ pathname: "/sign-in", params: { userId } })} />
      ) : unlocked && unsent ? (
        <Button label={t("sendUnsent")} loading={sending} disabled={sending} onPress={() => void sendUnsent()} />
      ) : null}
      {/* The Android app collects data only; coding and review are on the web. */}
      <Text style={styles.text}>{t(account?.coding_access || account?.reviewing_access ? "codingOnWeb" : "codingReviewPending")}</Text>
      {message ? <Text style={styles.error}>{message}</Text> : null}
    </Screen>
  );
}

/** Stop collection screens before they can load stale data or start intake calls. */
export default function NativeCollectionGate({
  children,
  routeName,
  routeParams,
}: { children: ReactNode; routeName?: string; routeParams?: unknown }) {
  const currentPathname = usePathname().replace(/\/$/, "") || "/";
  const pathname = routeName === undefined
    ? currentPathname
    : `/${routeName.split("/").filter(Boolean).at(-1) ?? ""}`;
  const params = useGlobalSearchParams<{ userId?: string | string[] }>();
  const router = useRouter();
  const state = useAppState();
  const styles = useUiStyles();
  const { level } = usePhoneClock();
  const [checking, setChecking] = useState(false);
  const [accessError, setAccessError] = useState<string>();
  const sceneUserId = routeParams && typeof routeParams === "object"
    ? (routeParams as { userId?: unknown }).userId
    : undefined;
  const rawUserId = routeName === undefined ? params.userId : sceneUserId;
  const userId = typeof rawUserId === "string"
    ? rawUserId
    : Array.isArray(rawUserId) && typeof rawUserId[0] === "string"
      ? rawUserId[0]
      : undefined;
  const account = state.accounts.find((item) => item.user_id === userId);
  const hasAccount = Boolean(account);
  const collectionAccess = account?.collection_access;
  const registrationAccess = account?.registration_access;
  const codingAccess = account?.coding_access;
  const reviewingAccess = account?.reviewing_access;

  const checkAccess = useCallback(async () => {
    if (!userId) return;
    setChecking(true);
    setAccessError(undefined);
    try {
      const access = await refreshAccessSummary(userId);
      await state.reload();
      if (!access) setAccessError(t("errGeneric"));
    } catch (error) {
      setAccessError(errorText(error));
      await state.reload();
    } finally {
      setChecking(false);
    }
  }, [state.reload, userId]);

  useEffect(() => {
    const needsCollection = COLLECTION_ROUTES.has(pathname) || pathname === WORKLIST_ROUTE;
    const needsRegistration = REGISTRATION_ROUTES.has(pathname) || pathname === WORKLIST_ROUTE;
    const needsWorkspace = pathname === WORKLIST_ROUTE;
    if (hasAccount && ((needsCollection && collectionAccess === undefined) ||
        (needsRegistration && registrationAccess === undefined) ||
        (needsWorkspace && (codingAccess === undefined || reviewingAccess === undefined)))) {
      void checkAccess();
    }
  }, [checkAccess, codingAccess, collectionAccess, hasAccount, pathname, registrationAccess, reviewingAccess]);

  const guarded = (screen: ReactNode) => level === "block" && ENTRY_ROUTES.has(pathname)
    ? <View style={{ flex: 1 }}>{screen}<ClockBlock /></View>
    : screen;
  if (!COLLECTION_ROUTES.has(pathname) && !REGISTRATION_ROUTES.has(pathname) && pathname !== WORKLIST_ROUTE) return children;
  if (!state.ready) return <ActivityIndicator style={{ flex: 1 }} />;
  if (!userId || !account) return <Redirect href="/" />;
  if (account.needs_sign_in || account.terms_required || account.access_blocked) return <NativePendingWorkspace userId={userId} />;
  if (pathname === WORKLIST_ROUTE && (account.coding_access || account.reviewing_access) &&
      account.collection_access !== true && account.registration_access !== true) return <NativePendingWorkspace userId={userId} />;
  if (COLLECTION_ROUTES.has(pathname) && account.collection_access === true) return guarded(children);
  if (REGISTRATION_ROUTES.has(pathname) && account.registration_access === true) return guarded(children);
  if (pathname === WORKLIST_ROUTE &&
      (account.collection_access === true || account.registration_access === true)) return children;
  if (COLLECTION_ROUTES.has(pathname) && account.collection_access === false) {
    return <NativePendingWorkspace userId={userId} />;
  }
  if (account.collection_access === false &&
      (REGISTRATION_ROUTES.has(pathname) || pathname === WORKLIST_ROUTE) && account.registration_access === false) {
    return <NativePendingWorkspace userId={userId} />;
  }
  return (
    <Screen title={t("accountsTitle")}>
      {checking ? <ActivityIndicator /> : <Text style={styles.error}>{accessError ?? t("errGeneric")}</Text>}
      <Button label={t("retryAccess")} loading={checking} onPress={() => void checkAccess()} />
      <Button kind="secondary" label={t("accounts")} onPress={() => router.replace("/")} />
    </Screen>
  );
}
