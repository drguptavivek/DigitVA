import { Redirect, usePathname, useRouter } from "expo-router";
import type { ReactNode } from "react";
import { ActivityIndicator, Text } from "react-native";

import { useAppState } from "./AppState";
import { t } from "./i18n";
import { Button, Screen, useUiStyles } from "./ui";

const COLLECTION_ROUTES = new Set([
  "/case",
  "/collection",
  "/form",
  "/interview",
  "/revision",
  "/worklist",
]);
const REGISTRATION_ROUTES = new Set(["/death-registration", "/register"]);

/** Block direct browser collection routes before their screens make intake calls. */
export default function NativeCollectionGate({
  children,
  routeName,
}: { children: ReactNode; routeName?: string; routeParams?: unknown }) {
  const currentPathname = usePathname().replace(/\/$/, "") || "/";
  const pathname = routeName === undefined
    ? currentPathname
    : `/${routeName.split("/").filter(Boolean).at(-1) ?? ""}`;
  const router = useRouter();
  const { ready, bootstrap } = useAppState();
  const styles = useUiStyles();

  if (!COLLECTION_ROUTES.has(pathname) && !REGISTRATION_ROUTES.has(pathname)) return children;
  if (!ready) return <ActivityIndicator style={{ flex: 1 }} />;
  if (!bootstrap) return <Redirect href="/" />;
  if (COLLECTION_ROUTES.has(pathname) && bootstrap.capabilities.intake) return children;
  if (REGISTRATION_ROUTES.has(pathname) && bootstrap.capabilities.registerDeath) return children;
  return (
    <Screen title={t("workspaceTitle")}>
      <Text style={styles.text}>{t("codingReviewPending")}</Text>
      <Button label={t("workspaceTitle")} onPress={() => router.replace("/workspace")} />
    </Screen>
  );
}
