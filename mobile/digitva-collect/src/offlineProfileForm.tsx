import { useEffect, useState } from "react";
import { Text, TextInput, View } from "react-native";

import { t, type StringKey } from "./i18n";
import type { OfflineProfile } from "./offlineProfile";
import { Button, useUiStyles } from "./ui";

type Sex = NonNullable<OfflineProfile["sex"]>;
type Level = NonNullable<OfflineProfile["hiv_mortality"]>;

export interface OfflineProfileFormProps {
  initialProfile?: OfflineProfile | null;
  submitLabel: string;
  loading?: boolean;
  error?: string;
  savedAt?: string | null;
  onSubmit: (profile: OfflineProfile) => void | Promise<void>;
  onCancel?: () => void;
  cancelLabel?: string;
}

interface Draft {
  name: string;
  ageYears: string;
  sex: Sex | null;
  designation: string;
  facilityName: string;
  country: string;
  state: string;
  orgCode: string;
  hivMortality: Level | null;
  malariaMortality: Level | null;
}

const EMPTY_DRAFT: Draft = {
  name: "",
  ageYears: "",
  sex: null,
  designation: "",
  facilityName: "",
  country: "",
  state: "",
  orgCode: "",
  hivMortality: null,
  malariaMortality: null,
};

const SEX_OPTIONS: Array<{ value: Sex; labelKey: StringKey }> = [
  { value: "male", labelKey: "offlineProfileMale" },
  { value: "female", labelKey: "offlineProfileFemale" },
  { value: "other", labelKey: "offlineProfileOther" },
];

const LEVEL_OPTIONS: Array<{ value: Level; labelKey: StringKey }> = [
  { value: "none", labelKey: "offlineProfileLevelNone" },
  { value: "low", labelKey: "offlineProfileLevelLow" },
  { value: "high", labelKey: "offlineProfileLevelHigh" },
];

function draftFromProfile(profile: OfflineProfile): Draft {
  return {
    name: profile.name,
    ageYears: profile.age_years === null ? "" : String(profile.age_years),
    sex: profile.sex,
    designation: profile.designation,
    facilityName: profile.facility_name,
    country: profile.country,
    state: profile.state,
    orgCode: profile.org_code ?? "",
    hivMortality: profile.hiv_mortality,
    malariaMortality: profile.malaria_mortality,
  };
}

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

function ChoiceRow({ label, options, value, onChange }: {
  label: string;
  options: Array<{ value: string; label: string }>;
  value: string | null;
  onChange: (value: string | null) => void;
}) {
  const styles = useUiStyles();
  return (
    <View style={{ gap: 4 }}>
      <Text style={styles.muted}>{label}</Text>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
        <Button
          kind={value === null ? "primary" : "secondary"}
          label={t("offlineProfileLevelUnset")}
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

export function OfflineProfileForm({
  initialProfile,
  submitLabel,
  loading = false,
  error,
  savedAt,
  onSubmit,
  onCancel,
  cancelLabel,
}: OfflineProfileFormProps) {
  const styles = useUiStyles();
  const [draft, setDraft] = useState<Draft>(() => initialProfile ? draftFromProfile(initialProfile) : EMPTY_DRAFT);
  const [optionalOpen, setOptionalOpen] = useState(Boolean(initialProfile));

  useEffect(() => {
    if (initialProfile) {
      setDraft(draftFromProfile(initialProfile));
      setOptionalOpen(true);
    }
  }, [initialProfile]);

  const update = <K extends keyof Draft>(key: K, value: Draft[K]) => {
    setDraft((current) => ({ ...current, [key]: value }));
  };

  const submit = () => {
    const age = draft.ageYears.trim();
    void onSubmit({
      name: draft.name,
      age_years: age === "" ? null : Number(age),
      sex: draft.sex,
      designation: draft.designation,
      facility_name: draft.facilityName,
      country: draft.country,
      state: draft.state,
      org_code: draft.orgCode,
      hiv_mortality: draft.hivMortality,
      malaria_mortality: draft.malariaMortality,
      updated_at: initialProfile?.updated_at ?? "",
    });
  };

  return (
    <View style={{ gap: 8 }}>
      <Field label={t("offlineProfileName")} value={draft.name} onChange={(value) => update("name", value)} />
      <Field label={t("offlineProfileCountry")} value={draft.country} onChange={(value) => update("country", value)} />
      <Button
        kind="secondary"
        label={t(optionalOpen ? "offlineProfileHideOptional" : "offlineProfileShowOptional")}
        expanded={optionalOpen}
        onPress={() => setOptionalOpen((open) => !open)}
      />
      {optionalOpen ? (
        <View style={{ gap: 8 }}>
          <Field label={t("offlineProfileAge")} value={draft.ageYears} onChange={(value) => update("ageYears", value)} keyboard="numeric" />
          <ChoiceRow
            label={t("offlineProfileSex")}
            options={SEX_OPTIONS.map((option) => ({ value: option.value, label: t(option.labelKey) }))}
            value={draft.sex}
            onChange={(value) => update("sex", value as Sex | null)}
          />
          <Field label={t("offlineProfileDesignation")} value={draft.designation} onChange={(value) => update("designation", value)} />
          <Field label={t("offlineProfileFacility")} value={draft.facilityName} onChange={(value) => update("facilityName", value)} />
          <Field label={t("offlineProfileState")} value={draft.state} onChange={(value) => update("state", value)} />
          <Field label={t("offlineProfileOrgCode")} value={draft.orgCode} onChange={(value) => update("orgCode", value)} />
          <ChoiceRow
            label={t("offlineProfileHiv")}
            options={LEVEL_OPTIONS.map((option) => ({ value: option.value, label: t(option.labelKey) }))}
            value={draft.hivMortality}
            onChange={(value) => update("hivMortality", value as Level | null)}
          />
          <ChoiceRow
            label={t("offlineProfileMalaria")}
            options={LEVEL_OPTIONS.map((option) => ({ value: option.value, label: t(option.labelKey) }))}
            value={draft.malariaMortality}
            onChange={(value) => update("malariaMortality", value as Level | null)}
          />
        </View>
      ) : null}
      {savedAt ? <Text style={styles.muted}>{t("offlineProfileSaved", { time: savedAt })}</Text> : null}
      <Button label={submitLabel} loading={loading} disabled={loading} onPress={submit} />
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
      {onCancel && cancelLabel ? <Button kind="secondary" label={cancelLabel} disabled={loading} onPress={onCancel} /> : null}
    </View>
  );
}
