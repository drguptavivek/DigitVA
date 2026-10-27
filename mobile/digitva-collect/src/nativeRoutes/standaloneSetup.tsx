/**
 * Path C first run: the offline profile (name and country required, optional facility and org code) then the
 * local standalone account. No network. On success the person goes to the ordinary PIN setup, which creates the
 * encrypted store, so PIN and lock behave exactly as for an enrolled account.
 */
import { Redirect, useRouter } from "expo-router";
import { useState } from "react";
import { Platform, Text, TextInput, View } from "react-native";

import { useAppState } from "../AppState";
import { isPlusVariant } from "../appVariant";
import { t } from "../i18n";
import { type OfflineProfile } from "../offlineProfile";
import { setUpStandaloneAccount } from "../standalone/account";
import { Button, Screen, useUiStyles } from "../ui";

function Field({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  const styles = useUiStyles();
  return (
    <View style={{ gap: 4 }}>
      <Text style={styles.muted}>{label}</Text>
      <TextInput style={styles.input} value={value} onChangeText={onChange} accessibilityLabel={label} autoCapitalize="none" />
    </View>
  );
}

export default function StandaloneSetup() {
  const styles = useUiStyles();
  const router = useRouter();
  const { reload } = useAppState();
  const [name, setName] = useState("");
  const [country, setCountry] = useState("");
  const [facility, setFacility] = useState("");
  const [orgCode, setOrgCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (Platform.OS !== "android" || !isPlusVariant()) return <Redirect href="/" />;

  async function create() {
    setBusy(true);
    setError("");
    try {
      const profile: OfflineProfile = {
        name, country, facility_name: facility, org_code: orgCode,
        age_years: null, sex: null, designation: "", state: "", hiv_mortality: null, malaria_mortality: null, updated_at: "",
      };
      const account = await setUpStandaloneAccount(profile);
      await reload();
      router.replace({ pathname: "/unlock", params: { userId: account.user_id } });
    } catch (caught) {
      const code = caught instanceof Error ? caught.message : "";
      setError(
        code === "offline_profile_name_required" ? t("offlineProfileNeedName")
        : code === "offline_profile_country_required" ? t("offlineProfileNeedCountry")
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
      <Field label={t("offlineProfileName")} value={name} onChange={setName} />
      <Field label={t("offlineProfileCountry")} value={country} onChange={setCountry} />
      <Field label={t("offlineProfileFacility")} value={facility} onChange={setFacility} />
      <Field label={t("offlineProfileOrgCode")} value={orgCode} onChange={setOrgCode} />
      <Button label={t("standaloneCreate")} loading={busy} disabled={busy} onPress={() => void create()} />
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
      <Button kind="secondary" label={t("cancel")} disabled={busy} onPress={() => router.back()} />
    </Screen>
  );
}
