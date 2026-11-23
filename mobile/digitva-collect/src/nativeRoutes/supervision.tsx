/**
 * Interview supervision on the phone (docs/policy/mobile-sign-in.md, "Interview supervisors on the phone"):
 * the shared supervision list and case screen (src/supervision) over the account's bearer session. Online only;
 * Edit interview and consent withdrawal are not offered here.
 */
import { useRouter, useFocusEffect, useLocalSearchParams } from "expo-router";
import { useCallback, useMemo, useRef, useState } from "react";

import { useAppState } from "../AppState";
import { t } from "../i18n";
import type { SupervisionHost } from "../supervision/host";
import { SupervisionList } from "../supervision/SupervisionPanel";
import { errorText, Notice, Screen } from "../ui";
import { createNativeWorkspaceTransport } from "../workspace/transport.native";

export default function Supervision() {
  const router = useRouter();
  const { userId } = useLocalSearchParams<{ userId?: string }>();
  const { offline } = useAppState();
  // A death report saved in the edit screen: come back to a fresh list, not the stale case detail.
  const [returns, setReturns] = useState(0);
  const focusedOnce = useRef(false);
  useFocusEffect(useCallback(() => {
    if (focusedOnce.current) setReturns((count) => count + 1);
    focusedOnce.current = true;
  }, []));
  const host = useMemo<SupervisionHost | undefined>(() => userId ? {
    request: createNativeWorkspaceTransport(userId),
    errorText,
    openDeathEdit: (deathId) => router.push({ pathname: "/register", params: { userId, deathId, by: "supervisor" } } as never),
    consentWithdrawal: false,
  } : undefined, [router, userId]);
  return (
    <Screen title={t("homeBlockSupervisor")}>
      {offline ? <Notice tone="warning">{t("supervisionNeedsConnection")}</Notice> : null}
      {host ? <SupervisionList key={returns} host={host} /> : null}
    </Screen>
  );
}
