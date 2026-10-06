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
  "/death-registration",
  "/form",
  "/interview",
  "/register",
  "/revision",
  "/worklist",
]);

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
      <Text style={styles.text}>{t("codingReviewPending")}</Text>
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
  const params = useGlobalSearchParams<{ userId?: string | string[] }>();
  const router = useRouter();
  const state = useAppState();
  const styles = useUiStyles();
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
    if (COLLECTION_ROUTES.has(pathname) && hasAccount && collectionAccess === undefined) {
      void checkAccess();
    }
  }, [checkAccess, collectionAccess, hasAccount, pathname]);

  if (!COLLECTION_ROUTES.has(pathname)) return children;
  if (!state.ready) return <ActivityIndicator style={{ flex: 1 }} />;
  if (!userId || !account) return <Redirect href="/" />;
  if (account.collection_access === true) return children;
  if (account.collection_access === false) return <NativePendingWorkspace userId={userId} />;
  return (
    <Screen title={t("accountsTitle")}>
      {checking ? <ActivityIndicator /> : <Text style={styles.error}>{accessError ?? t("errGeneric")}</Text>}
      <Button label={t("retryAccess")} loading={checking} onPress={() => void checkAccess()} />
      <Button kind="secondary" label={t("accounts")} onPress={() => router.replace("/")} />
    </Screen>
  );
}
