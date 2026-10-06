import { Redirect, useGlobalSearchParams, usePathname, useRouter } from "expo-router";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { ActivityIndicator, Alert, Text } from "react-native";

import { useAppState } from "./AppState";
import { refreshAccessSummary, signOut } from "./auth";
import { t } from "./i18n";
import { isUnlocked } from "./interviewerDb";
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
const CODING_ROUTE = "/coding";
const REVIEWING_ROUTE = "/reviewing";
const WORKSPACE_ROUTE = "/workspace";

/** Keep account controls available while collection is disabled. */
function NativePendingWorkspace({ userId }: { userId: string }) {
  const router = useRouter();
  const { accounts, lockNow, reload } = useAppState();
  const styles = useUiStyles();
  const [signOutError, setSignOutError] = useState(false);
  const account = accounts.find((item) => item.user_id === userId);
  const unlocked = isUnlocked(userId);

  async function doSignOut() {
    try {
      await signOut(userId);
      await reload();
      router.replace("/");
    } catch {
      setSignOutError(true);
    }
  }

  function confirmSignOut() {
    Alert.alert(t("signOut"), t("pendingSignOutConfirm"), [
      { text: t("cancel"), style: "cancel" },
      {
        text: t("signOutConfirm"),
        style: "destructive",
        onPress: () => void doSignOut(),
      },
    ]);
  }

  return (
    <Screen title={account?.name ?? t("accountsTitle")}>
      {account?.coding_access || account?.reviewing_access ? (
        <>
          <Text style={styles.text}>{t("workspaceTitle")}</Text>
          {account.coding_access ? <Button label={t("navCoding")} onPress={() => router.push({ pathname: CODING_ROUTE, params: { userId } })} /> : null}
          {account.reviewing_access ? <Button label={t("navReview")} onPress={() => router.push({ pathname: REVIEWING_ROUTE, params: { userId } })} /> : null}
        </>
      ) : <Text style={styles.text}>{t("codingReviewPending")}</Text>}
      {signOutError ? <Text style={styles.error}>{t("errGeneric")}</Text> : null}
      <Button kind="secondary" label={t("accounts")} onPress={() => router.replace("/")} />
      <Button kind="secondary" label={t("lockNow")} disabled={!unlocked} onPress={() => void lockNow()} />
      <Button kind="danger" label={t("signOut")} onPress={confirmSignOut} />
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
  const params = useGlobalSearchParams<{ userId?: string | string[]; mode?: string | string[] }>();
  const router = useRouter();
  const state = useAppState();
  const styles = useUiStyles();
  const [checking, setChecking] = useState(false);
  const [accessError, setAccessError] = useState<string>();
  const sceneUserId = routeParams && typeof routeParams === "object"
    ? (routeParams as { userId?: unknown }).userId
    : undefined;
  const rawUserId = routeName === undefined ? params.userId : sceneUserId;
  const routeQuery = routeParams && typeof routeParams === "object" ? routeParams as { mode?: unknown } : undefined;
  const rawMode = routeQuery?.mode ?? params.mode;
  const mode = typeof rawMode === "string" ? rawMode : Array.isArray(rawMode) ? rawMode[0] : undefined;
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
  const gatedWorkspaceRoute = pathname === CODING_ROUTE || pathname === REVIEWING_ROUTE || pathname === WORKSPACE_ROUTE;
  const requiresCoding = pathname === CODING_ROUTE || (pathname === WORKSPACE_ROUTE && mode === "coding");
  const requiresReviewing = pathname === REVIEWING_ROUTE || (pathname === WORKSPACE_ROUTE && mode === "reviewing");
  const readOnlyView = pathname === WORKSPACE_ROUTE && mode === "view";

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
    const needsWorkspace = gatedWorkspaceRoute || pathname === WORKLIST_ROUTE;
    if (hasAccount && ((needsCollection && collectionAccess === undefined) ||
        (needsRegistration && registrationAccess === undefined) ||
        (needsWorkspace && (codingAccess === undefined || reviewingAccess === undefined)))) {
      void checkAccess();
    }
  }, [checkAccess, codingAccess, collectionAccess, gatedWorkspaceRoute, hasAccount, pathname, registrationAccess, reviewingAccess]);

  if (!COLLECTION_ROUTES.has(pathname) && !REGISTRATION_ROUTES.has(pathname) && pathname !== WORKLIST_ROUTE && !gatedWorkspaceRoute) return children;
  if (!state.ready) return <ActivityIndicator style={{ flex: 1 }} />;
  if (!userId || !account) return <Redirect href="/" />;
  if (account.needs_sign_in || account.terms_required || account.access_blocked) return <NativePendingWorkspace userId={userId} />;
  if (gatedWorkspaceRoute && !isUnlocked(userId)) return <Redirect href={{ pathname: "/unlock", params: { userId } }} />;
  if (requiresCoding && account.coding_access === true) return children;
  if (requiresReviewing && account.reviewing_access === true) return children;
  if (readOnlyView) return children;
  if (pathname === WORKSPACE_ROUTE && !mode) return children;
  if (pathname === WORKLIST_ROUTE && (account.coding_access || account.reviewing_access) &&
      account.collection_access !== true && account.registration_access !== true) return <NativePendingWorkspace userId={userId} />;
  if (COLLECTION_ROUTES.has(pathname) && account.collection_access === true) return children;
  if (REGISTRATION_ROUTES.has(pathname) && account.registration_access === true) return children;
  if (pathname === WORKLIST_ROUTE &&
      (account.collection_access === true || account.registration_access === true)) return children;
  if ((COLLECTION_ROUTES.has(pathname) || pathname === CODING_ROUTE) && account.collection_access === false) {
    return <NativePendingWorkspace userId={userId} />;
  }
  if (requiresCoding || requiresReviewing || (pathname === WORKSPACE_ROUTE && mode && !readOnlyView)) {
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
