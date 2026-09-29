/**
 * Register a death offline: the web register form's fields, checked with the
 * same rules (src/cases.ts validateRegistration), saved as a pending
 * registration with its own client_death_id and sent on the next sync. With
 * `clientDeathId` it edits one the server refused (it becomes pending again,
 * same id). "Save and start interview" opens the questionnaire on it at once.
 */
import { randomUUID } from "expo-crypto";
import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Text, TextInput, View } from "react-native";

import { useAppState } from "../src/AppState";
import {
  cleanRegistration,
  getRegistration,
  localToday,
  saveRegistration,
  SEX_VALUES,
  validateRegistration,
  type RegistrationFields
} from "../src/cases";
import { getMeta, type Db } from "../src/drafts";
import { t, type StringKey } from "../src/i18n";
import { isUnlocked, openInterviewerDb } from "../src/interviewerDb";
import { registersDeaths, targetsFrom, type Bootstrap, type Target, type Units } from "../src/sync";
import { Button, Row, Screen, styles } from "../src/ui";

type Field = keyof RegistrationFields;

/** Text fields in the web form's order, with their label and keyboard. */
const TEXT_FIELDS: Array<{ name: Field; label: StringKey; keyboard?: "numeric" | "phone-pad"; help?: StringKey }> = [
  { name: "deceased_name", label: "fieldDeceasedName" },
  { name: "date_of_death", label: "fieldDateOfDeath" },
  { name: "date_of_birth", label: "fieldDateOfBirth" },
  { name: "age_years", label: "fieldAge", keyboard: "numeric" },
  { name: "abha_number", label: "fieldAbhaNumber" },
  { name: "abha_address", label: "fieldAbhaAddress" },
  { name: "place_of_death", label: "fieldPlaceOfDeath" },
  { name: "address", label: "fieldAddress" },
  { name: "address_house_street", label: "fieldHouseStreet" },
  { name: "address_village_ward", label: "fieldVillageWard" },
  { name: "address_landmark", label: "fieldLandmark" },
  { name: "informant_name", label: "fieldInformantName" },
  { name: "father_name", label: "fieldFatherName" },
  { name: "mother_name", label: "fieldMotherName" },
  { name: "informant_phone", label: "fieldInformantPhone", keyboard: "phone-pad", help: "phoneHelp" },
  { name: "informant_phone_2", label: "fieldInformantPhone2", keyboard: "phone-pad" },
  { name: "remarks", label: "fieldRemarks" }
];

const SEX_LABELS: Record<(typeof SEX_VALUES)[number], StringKey> = {
  male: "sexMale",
  female: "sexFemale",
  undetermined: "sexUndetermined",
  unknown: "sexUnknown"
};

export default function Register() {
  const router = useRouter();
  const params = useLocalSearchParams<{ userId: string; clientDeathId?: string }>();
  const { accounts } = useAppState();
  const account = accounts.find((a) => a.user_id === params.userId);
  const [db, setDb] = useState<Db | undefined>();
  const [targets, setTargets] = useState<Target[]>([]);
  const [target, setTarget] = useState<Target | undefined>();
  const [fields, setFields] = useState<RegistrationFields>({ deceased_name: "", deceased_sex: "", date_of_death: "" });
  const [errors, setErrors] = useState<Partial<Record<Field, StringKey>>>({});
  const [message, setMessage] = useState("");
  const editing = params.clientDeathId;

  useEffect(() => {
    if (!account) return;
    let active = true;
    void (async () => {
      const handle = await openInterviewerDb(account.user_id).catch(() => undefined);
      if (!handle) return;
      const [bootstrap, units, existing] = await Promise.all([
        getMeta<Bootstrap>(handle, "bootstrap"),
        getMeta<Units | null>(handle, "units"),
        editing ? getRegistration(handle, editing) : Promise.resolve(undefined)
      ]);
      if (!active) return;
      const choices = targetsFrom(bootstrap, units).filter((c) => registersDeaths(bootstrap, c.siteId));
      setDb(handle);
      setTargets(choices);
      if (existing) {
        setFields(existing.fields);
        setTarget(
          choices.find((c) => c.siteId === existing.site_id && (c.orgUnitId ?? null) === existing.org_unit_id) ?? {
            key: "existing",
            label: existing.site_id,
            siteId: existing.site_id,
            orgUnitId: existing.org_unit_id ?? undefined
          }
        );
      } else if (choices.length === 1) {
        setTarget(choices[0]);
      }
    })();
    return () => {
      active = false;
    };
  }, [account, editing]);

  if (!account) return <Redirect href="/" />;
  if (!isUnlocked(account.user_id)) {
    return <Redirect href={{ pathname: "/unlock", params: { userId: account.user_id } }} />;
  }

  const set = (name: Field) => (value: string) => setFields((current) => ({ ...current, [name]: value }));

  async function save(startAfter: boolean) {
    if (!db || !account || !target) return;
    const found = validateRegistration(fields, localToday());
    setErrors(found);
    if (Object.keys(found).length > 0) {
      setMessage(t("registerFixErrors"));
      return;
    }
    const clientDeathId = editing ?? randomUUID();
    await saveRegistration(db, {
      client_death_id: clientDeathId,
      site_id: target.siteId,
      org_unit_id: target.orgUnitId ?? null,
      fields: cleanRegistration(fields)
    });
    if (!startAfter) {
      router.back();
      return;
    }
    router.replace({
      pathname: "/form",
      params: { userId: account.user_id, draftId: randomUUID(), clientDeathId }
    });
  }

  const errorFor = (name: Field) => (errors[name] ? <Text style={styles.error}>{t(errors[name]!)}</Text> : null);

  return (
    <Screen title={t("registerDeath")}>
      <Text style={styles.text}>{t("chooseSite")}</Text>
      {targets.length === 0 && !target ? <Text style={styles.muted}>{t("noSites")}</Text> : null}
      <View style={{ gap: 8 }}>
        {editing && target ? (
          <Text style={styles.muted}>{target.label}</Text>
        ) : (
          targets.map((choice) => (
            <Button
              key={choice.key}
              kind={choice.key === target?.key ? "primary" : "secondary"}
              label={choice.label}
              onPress={() => setTarget(choice)}
            />
          ))
        )}
      </View>
      <Text style={styles.muted}>{t("fieldSex")}</Text>
      <Row>
        {SEX_VALUES.map((sex) => (
          <Button
            key={sex}
            kind={fields.deceased_sex === sex ? "primary" : "secondary"}
            label={t(SEX_LABELS[sex])}
            onPress={() => set("deceased_sex")(sex)}
          />
        ))}
      </Row>
      {errorFor("deceased_sex")}
      {TEXT_FIELDS.map((field) => (
        <View key={field.name} style={{ gap: 4 }}>
          <Text style={styles.muted}>{t(field.label)}</Text>
          <TextInput
            style={styles.input}
            autoCorrect={false}
            keyboardType={field.keyboard ?? "default"}
            value={fields[field.name] ?? ""}
            onChangeText={set(field.name)}
          />
          {field.help ? <Text style={styles.muted}>{t(field.help)}</Text> : null}
          {errorFor(field.name)}
        </View>
      ))}
      {message ? <Text style={styles.error}>{message}</Text> : null}
      <Row>
        <Button label={t("save")} disabled={!db || !target} onPress={() => void save(false)} />
        <Button label={t("registerSaveStart")} disabled={!db || !target} onPress={() => void save(true)} />
        <Button kind="secondary" label={t("cancel")} onPress={() => router.back()} />
      </Row>
    </Screen>
  );
}
