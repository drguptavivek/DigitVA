/**
 * Path C first run: the complete offline profile (name, age, sex, country, HIV and malaria levels required: an
 * interview prefills them, digitva-0vz7) then the local standalone account.
 * No network. On success the person goes to the ordinary PIN setup, which creates the encrypted store, so PIN and
 * lock behave exactly as for an enrolled account.
 */
import { Redirect, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Platform, Text } from "react-native";

import { useAppState } from "../AppState";
import { isPlusVariant } from "../appVariant";
import { t } from "../i18n";
import { OfflineProfileForm, standaloneProfileMissingText } from "../offlineProfileForm";
import { getOfflineProfile, standaloneProfileMissing, type OfflineProfile } from "../offlineProfile";
import { setUpStandaloneAccount } from "../standalone/account";
import { errorText, Screen, useUiStyles } from "../ui";

export default function StandaloneSetup() {
  const styles = useUiStyles();
  const router = useRouter();
  const { reload } = useAppState();
  const [initialProfile, setInitialProfile] = useState<OfflineProfile | null | undefined>(undefined);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    getOfflineProfile().then((profile) => {
      if (live) setInitialProfile(profile);
    }).catch((caught) => {
      if (live) setError(errorText(caught));
    });
    return () => { live = false; };
  }, []);

  if (Platform.OS !== "android" || !isPlusVariant()) return <Redirect href="/" />;

  async function create(profile: OfflineProfile) {
    setBusy(true);
    setError("");
    try {
      const account = await setUpStandaloneAccount(profile);
      await reload();
      router.replace({ pathname: "/unlock", params: { userId: account.user_id } });
    } catch (caught) {
      const code = caught instanceof Error ? caught.message : "";
      setError(
        code === "standalone_server_session_active" ? t("standaloneLogoutRequired")
        : code === "standalone_profile_incomplete" ? standaloneProfileMissingText(standaloneProfileMissing(profile))
        : code === "offline_profile_name_required" ? t("offlineProfileNeedName")
        : code === "offline_profile_country_required" ? t("offlineProfileNeedCountry")
        : code === "offline_profile_age_invalid" ? t("offlineProfileNeedAge")
        : t("standaloneSetupFailed"),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen title={t("standaloneSetupTitle")}>
      <Text style={styles.text}>{t("standaloneSetupHint")}</Text>
      <Text style={styles.muted}>{t("standaloneWarning")}</Text>
      <OfflineProfileForm
        initialProfile={initialProfile}
        submitLabel={t("standaloneCreate")}
        loading={busy}
        error={error}
        onSubmit={create}
        onCancel={() => router.back()}
        cancelLabel={t("cancel")}
        allRequired
      />
    </Screen>
  );
}
