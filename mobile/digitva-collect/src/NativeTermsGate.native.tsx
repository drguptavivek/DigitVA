import { useGlobalSearchParams, useRouter } from "expo-router";
import { useRef, useState, type ReactNode } from "react";
import { Text, View } from "react-native";

import { useAppState } from "./AppState";
import { acceptDeviceTerms, refreshAccessSummary, signOut } from "./auth";
import { SessionRevokedError, SignInRequiredError } from "./authErrors";
import { ApiError } from "./api";
import { t } from "./i18n";
import { Button, errorText, Screen, useUiStyles } from "./ui";

export default function NativeTermsGate({ children }: { children: ReactNode }) {
  const params = useGlobalSearchParams<{ userId?: string }>();
  const { accounts, reload, clearError, error: appError } = useAppState();
  const router = useRouter();
  const styles = useUiStyles();
  const account = accounts.find((entry) => entry.user_id === params.userId);
  const routeUser = useRef(params.userId);
  routeUser.current = params.userId;
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const blockedCode = account?.access_blocked;
  const gateActive = Boolean(account && (account.terms_required || blockedCode || appError));

  async function accept() {
    if (!account || busy) return;
    setBusy(true);
    setMessage("");
    try {
      await acceptDeviceTerms(account.user_id);
      await reload();
      if (routeUser.current !== account.user_id) return;
      router.replace({
        pathname: "/unlock",
        params: { userId: account.user_id, refresh: "1" },
      });
    } catch (error) {
      setMessage(errorText(error));
      await reload();
      if (
        (error instanceof SessionRevokedError ||
          error instanceof SignInRequiredError) &&
        routeUser.current === account.user_id
      ) {
        router.replace("/");
      }
    } finally {
      setBusy(false);
    }
  }

  async function retryAccess() {
    if (!account || busy) return;
    setBusy(true);
    setMessage("");
    try {
      const access = await refreshAccessSummary(account.user_id);
      if (access) clearError?.();
      await reload();
    } catch (error) {
      setMessage(errorText(error));
      await reload();
    } finally {
      setBusy(false);
    }
  }

  const gateMessage = message || (account ? appError : undefined) || (blockedCode ? errorText(new ApiError(403, blockedCode)) : "");

  return (
    <View style={{ flex: 1 }}>
      <View
        style={{ flex: 1 }}
        pointerEvents={gateActive ? "none" : "auto"}
        accessibilityElementsHidden={gateActive}
        importantForAccessibility={
          gateActive ? "no-hide-descendants" : "auto"
        }
      >
        {children}
      </View>
      {gateActive ? (
        <View
          style={{ position: "absolute", inset: 0 }}
          accessibilityViewIsModal
        >
          <Screen title={account?.terms_required ? t("termsTitle") : t("serverError")}>
            {account?.terms_required ? <>
              <Text style={styles.text}>{t("termsConfidential")}</Text>
              <Text style={styles.text}>{t("termsNoSharing")}</Text>
              <Text style={styles.text}>{t("termsPurpose")}</Text>
              <Button
                label={t("acceptTerms")}
                disabled={busy}
                loading={busy}
                onPress={() => void accept()}
              />
            </> : <Button
              label={t("retry")}
              disabled={busy}
              loading={busy}
              onPress={() => void retryAccess()}
            />}
            {gateMessage ? <Text style={styles.error}>{gateMessage}</Text> : null}
            <Button
              kind="secondary"
              label={t("home")}
              disabled={busy}
              onPress={() => router.replace("/")}
            />
            <Button
              kind="danger"
              label={t("signOut")}
              disabled={busy}
              onPress={() => {
                if (!account) return;
                setBusy(true);
                void signOut(account.user_id)
                  .then(reload)
                  .then(() => router.replace("/"))
                  .catch((error) => setMessage(errorText(error)))
                  .finally(() => setBusy(false));
              }}
            />
          </Screen>
        </View>
      ) : null}
    </View>
  );
}
