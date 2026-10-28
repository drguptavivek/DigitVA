/**
 * Collect Plus only: the coder/facility profile Settings > Collect Plus > "Offline profile" captures for
 * pure-offline coding (src/offlineProfile.ts). On-device only, like everything in offline mode; the fields feed
 * a future sync's provenance and the SmartVA endemicity inputs. Other builds redirect home.
 */
import { Redirect, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Text } from "react-native";

import { isPlusVariant } from "../appVariant";
import { t } from "../i18n";
import { OfflineProfileForm } from "../offlineProfileForm";
import { getOfflineProfile, saveOfflineProfile, type OfflineProfile } from "../offlineProfile";
import { errorText, Screen, useUiStyles } from "../ui";

function profileError(caught: unknown): string {
  const code = caught instanceof Error ? caught.message : "";
  return code === "offline_profile_name_required" ? t("offlineProfileNeedName")
    : code === "offline_profile_country_required" ? t("offlineProfileNeedCountry")
    : code === "offline_profile_age_invalid" ? t("offlineProfileNeedAge")
    : errorText(caught);
}

export default function OfflineProfileScreen() {
  const router = useRouter();
  const styles = useUiStyles();
  const [initialProfile, setInitialProfile] = useState<OfflineProfile | null | undefined>(undefined);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    getOfflineProfile().then((profile) => {
      if (!live) return;
      setInitialProfile(profile);
      setSavedAt(profile?.updated_at ?? null);
    }).catch((caught) => { if (live) setError(errorText(caught)); });
    return () => { live = false; };
  }, []);

  const save = async (profile: OfflineProfile) => {
    setError("");
    setBusy(true);
    try {
      await saveOfflineProfile(profile);
      const stored = await getOfflineProfile();
      setInitialProfile(stored);
      setSavedAt(stored?.updated_at ?? null);
    } catch (caught) {
      setError(profileError(caught));
    } finally {
      setBusy(false);
    }
  };

  if (!isPlusVariant()) return <Redirect href="/" />;
  return (
    <Screen title={t("offlineProfileTitle")}>
      <Text style={styles.muted}>{t("offlineProfileHint")}</Text>
      <OfflineProfileForm
        initialProfile={initialProfile}
        submitLabel={t("offlineProfileSave")}
        loading={busy}
        error={error}
        savedAt={savedAt}
        onSubmit={save}
        onCancel={() => router.back()}
        cancelLabel={t("settings")}
      />
    </Screen>
  );
}
