import { useEffect, useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";

import { Button, styles } from "../ui";
import type { NarrativeQuality, SocialAutopsy } from "./contracts";

/** Edits the server-ordered narrative quality and social-autopsy gates. */
export function QualityPanels({
  narrative,
  socialAutopsy,
  onSaveNarrative,
  onSaveSocialAutopsy,
}: {
  narrative: NarrativeQuality | null;
  socialAutopsy: SocialAutopsy | null;
  onSaveNarrative: (body: { cannot_grade: boolean; [key: string]: string | number | boolean }) => Promise<void>;
  onSaveSocialAutopsy: (body: { selected_options: Array<{ delay_level: string; option_code: string }>; remark: string }) => Promise<void>;
}) {
  return (
    <View>
      {narrative ? <NarrativePanel key="narrative" data={narrative} onSave={onSaveNarrative} /> : null}
      {socialAutopsy ? <SocialAutopsyPanel key="social-autopsy" data={socialAutopsy} onSave={onSaveSocialAutopsy} /> : null}
    </View>
  );
}

/** Render and save the ordered server-defined narrative quality fields. */
function NarrativePanel({ data, onSave }: { data: NarrativeQuality; onSave(body: { cannot_grade: boolean; [key: string]: string | number | boolean }): Promise<void> }) {
  const [values, setValues] = useState<Record<string, number>>(() => data.saved?.values ?? {});
  const [cannotGrade, setCannotGrade] = useState(() => data.saved?.cannot_grade ?? false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setValues(data.saved?.values ?? {});
    setCannotGrade(data.saved?.cannot_grade ?? false);
  }, [data]);

  return (
    <View style={styles.card}>
      <Text accessibilityRole="header" style={styles.headline}>Narrative quality</Text>
      {data.fields.map((field) => (
        <View key={field.key}>
          <Text style={styles.muted}>{field.label}</Text>
          {field.options.map((option) => (
            <Pressable key={option.value} accessibilityRole="radio" accessibilityLabel={`${field.label}: ${option.label}`} accessibilityState={{ selected: values[field.key] === option.value }} disabled={cannotGrade} onPress={() => setValues((current) => ({ ...current, [field.key]: option.value }))}>
              <Text style={styles.text}>{values[field.key] === option.value ? "◉" : "○"} {option.label}</Text>
            </Pressable>
          ))}
        </View>
      ))}
      <Pressable accessibilityRole="checkbox" accessibilityLabel="Cannot grade" accessibilityState={{ checked: cannotGrade }} onPress={() => setCannotGrade((value) => !value)}>
        <Text style={styles.text}>{cannotGrade ? "☑" : "☐"} Cannot grade</Text>
      </Pressable>
      <Button label="Save narrative quality" onPress={() => {
        setBusy(true);
        void onSave({ cannot_grade: cannotGrade, ...(cannotGrade ? {} : values) }).finally(() => setBusy(false));
      }} disabled={busy || (!cannotGrade && data.fields.some((field) => values[field.key] === undefined))} loading={busy} />
    </View>
  );
}

/** Require an answer for each server-defined delay level and keep `none` exclusive. */
function SocialAutopsyPanel({ data, onSave }: { data: SocialAutopsy; onSave(body: { selected_options: Array<{ delay_level: string; option_code: string }>; remark: string }): Promise<void> }) {
  const [selected, setSelected] = useState<Record<string, string[]>>(() => selectedMap(data));
  const [remark, setRemark] = useState(data.saved?.remark ?? "");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setSelected(selectedMap(data));
    setRemark(data.saved?.remark ?? "");
  }, [data]);

  const complete = data.questions.every((question) => (selected[question.delay_level] ?? []).length > 0);
  return (
    <View style={styles.card}>
      <Text accessibilityRole="header" style={styles.headline}>Social autopsy</Text>
      {data.questions.map((question) => (
        <View key={question.delay_level}>
          <Text style={styles.muted}>{question.title}</Text>
          {question.options.map((option) => {
            const values = selected[question.delay_level] ?? [];
            const checked = values.includes(option.option_code);
            return (
              <Pressable key={option.option_code} accessibilityRole="checkbox" accessibilityLabel={`${question.title}: ${option.label}`} accessibilityState={{ checked }} onPress={() => setSelected((current) => {
                const currentValues = current[question.delay_level] ?? [];
                const next = checked
                  ? currentValues.filter((value) => value !== option.option_code)
                  : option.option_code === "none"
                    ? ["none"]
                    : [...currentValues.filter((value) => value !== "none"), option.option_code];
                return { ...current, [question.delay_level]: next };
              })}>
                <Text style={styles.text}>{checked ? "☑" : "☐"} {option.label}{option.description ? ` — ${option.description}` : ""}</Text>
              </Pressable>
            );
          })}
        </View>
      ))}
      <TextInput accessibilityLabel="Social autopsy remark" placeholder="Remark" value={remark} onChangeText={setRemark} style={styles.input} multiline />
      <Button label="Save social autopsy" onPress={() => {
        setBusy(true);
        const selected_options = data.questions.flatMap((question) => (selected[question.delay_level] ?? []).map((option_code) => ({ delay_level: question.delay_level, option_code })));
        void onSave({ selected_options, remark }).finally(() => setBusy(false));
      }} disabled={busy || !complete} loading={busy} />
    </View>
  );
}

/** Restore the caller's saved choices by delay level. */
function selectedMap(data: SocialAutopsy): Record<string, string[]> {
  const selected: Record<string, string[]> = {};
  for (const { delay_level, option_code } of data.saved?.selected_options ?? []) {
    selected[delay_level] = [...(selected[delay_level] ?? []), option_code];
  }
  return selected;
}
