/**
 * Collect Plus only: the coder/facility profile Settings > Collect Plus > "Offline profile" captures for
 * pure-offline coding (src/offlineProfile.ts). On-device only, like everything in offline mode; the fields feed
 * a future sync's provenance and the SmartVA endemicity inputs. Other builds redirect home.
 */
import { Redirect, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Text, TextInput, View } from "react-native";

import { isPlusVariant } from "../appVariant";
import { t } from "../i18n";
import { getOfflineProfile, saveOfflineProfile, type OfflineProfile } from "../offlineProfile";
import { Button, errorText, Screen, useUiStyles } from "../ui";

type Sex = NonNullable<OfflineProfile["sex"]>;
type Level = NonNullable<OfflineProfile["hiv_mortality"]>;

const SEX_OPTIONS: Array<{ value: Sex; labelKey: Parameters<typeof t>[0] }> = [
  { value: "male", labelKey: "offlineProfileMale" },
  { value: "female", labelKey: "offlineProfileFemale" },
  { value: "other", labelKey: "offlineProfileOther" },
];

const LEVEL_OPTIONS: Array<{ value: Level; labelKey: Parameters<typeof t>[0] }> = [
  { value: "none", labelKey: "offlineProfileLevelNone" },
  { value: "low", labelKey: "offlineProfileLevelLow" },
  { value: "high", labelKey: "offlineProfileLevelHigh" },
];

function ChoiceRow({ label, options, value, unsetLabel, onChange }: {
  label: string;
  options: Array<{ value: string; label: string }>;
  value: string | null;
  unsetLabel: string;
  onChange: (value: string | null) => void;
}) {
  const styles = useUiStyles();
  return (
    <View style={{ gap: 4 }}>
      <Text style={styles.muted}>{label}</Text>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
        <Button
          kind={value === null ? "primary" : "secondary"}
          label={unsetLabel}
          onPress={() => onChange(null)}
        />
        {options.map((option) => (
          <Button
            key={option.value}
            kind={value === option.value ? "primary" : "secondary"}
            label={option.label}
            onPress={() => onChange(option.value)}
          />
        ))}
      </View>
    </View>
  );
}

/** One single-line answer; age is validated on save, not while typing. */
function Field({ label, value, onChange, keyboard }: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  keyboard?: "numeric";
}) {
  const styles = useUiStyles();
  return (
    <View style={{ gap: 4 }}>
      <Text style={styles.muted}>{label}</Text>
      <TextInput
        style={styles.input}
        value={value}
        onChangeText={onChange}
        keyboardType={keyboard}
        accessibilityLabel={label}
        autoCapitalize="none"
      />
    </View>
  );
}

export default function OfflineProfileScreen() {
  const router = useRouter();
  const styles = useUiStyles();
  const [name, setName] = useState("");
  const [ageYears, setAgeYears] = useState("");
  const [sex, setSex] = useState<Sex | null>(null);
  const [designation, setDesignation] = useState("");
  const [facilityName, setFacilityName] = useState("");
  const [country, setCountry] = useState("");
  const [stateName, setStateName] = useState("");
  const [orgCode, setOrgCode] = useState("");
  const [hivMortality, setHivMortality] = useState<Level | null>(null);
  const [malariaMortality, setMalariaMortality] = useState<Level | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    getOfflineProfile().then((profile) => {
      if (!live || !profile) return;
      setName(profile.name);
      setAgeYears(profile.age_years === null ? "" : String(profile.age_years));
      setSex(profile.sex);
      setDesignation(profile.designation);
      setFacilityName(profile.facility_name);
      setCountry(profile.country);
      setStateName(profile.state);
      setOrgCode(profile.org_code ?? "");
      setHivMortality(profile.hiv_mortality);
      setMalariaMortality(profile.malaria_mortality);
      setSavedAt(profile.updated_at);
    }).catch(() => setError(errorText(new Error("offline_profile_unreadable"))));
    return () => { live = false; };
  }, []);

  const save = async () => {
    setError("");
    const age = ageYears.trim();
    setBusy(true);
    try {
      const profile: OfflineProfile = {
        name,
        age_years: age === "" ? null : Number(age),
        sex,
        designation,
        facility_name: facilityName,
        country,
        state: stateName,
        org_code: orgCode,
        hiv_mortality: hivMortality,
        malaria_mortality: malariaMortality,
        updated_at: "",
      };
      await saveOfflineProfile(profile);
      const stored = await getOfflineProfile();
      if (stored) setSavedAt(stored.updated_at);
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "";
      setError(
        message === "offline_profile_name_required" ? t("offlineProfileNeedName")
        : message === "offline_profile_country_required" ? t("offlineProfileNeedCountry")
        : message === "offline_profile_age_invalid" ? t("offlineProfileNeedAge")
        : errorText(caught),
      );
    } finally {
      setBusy(false);
    }
  };

  if (!isPlusVariant()) return <Redirect href="/" />;
  return (
    <Screen title={t("offlineProfileTitle")}>
      <Text style={styles.muted}>{t("offlineProfileHint")}</Text>
      <Field label={t("offlineProfileName")} value={name} onChange={setName} />
      <Field label={t("offlineProfileAge")} value={ageYears} onChange={setAgeYears} keyboard="numeric" />
      <ChoiceRow
        label={t("offlineProfileSex")}
        options={SEX_OPTIONS.map((option) => ({ value: option.value, label: t(option.labelKey) }))}
        value={sex}
        unsetLabel={t("offlineProfileLevelUnset")}
        onChange={(value) => setSex(value as Sex | null)}
      />
      <Field label={t("offlineProfileDesignation")} value={designation} onChange={setDesignation} />
      <Field label={t("offlineProfileFacility")} value={facilityName} onChange={setFacilityName} />
      <Field label={t("offlineProfileCountry")} value={country} onChange={setCountry} />
      <Field label={t("offlineProfileState")} value={stateName} onChange={setStateName} />
      <Field label={t("offlineProfileOrgCode")} value={orgCode} onChange={setOrgCode} />
      <ChoiceRow
        label={t("offlineProfileHiv")}
        options={LEVEL_OPTIONS.map((option) => ({ value: option.value, label: t(option.labelKey) }))}
        value={hivMortality}
        unsetLabel={t("offlineProfileLevelUnset")}
        onChange={(value) => setHivMortality(value as Level | null)}
      />
      <ChoiceRow
        label={t("offlineProfileMalaria")}
        options={LEVEL_OPTIONS.map((option) => ({ value: option.value, label: t(option.labelKey) }))}
        value={malariaMortality}
        unsetLabel={t("offlineProfileLevelUnset")}
        onChange={(value) => setMalariaMortality(value as Level | null)}
      />
      {savedAt ? <Text style={styles.muted}>{t("offlineProfileSaved", { time: savedAt })}</Text> : null}
      <Button label={t("offlineProfileSave")} loading={busy} disabled={busy} onPress={() => void save()} />
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
      <Button kind="secondary" label={t("settings")} onPress={() => router.back()} />
    </Screen>
  );
}
