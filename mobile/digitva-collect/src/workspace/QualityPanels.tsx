import { useEffect, useState } from "react";
import { Text, TextInput, View, useWindowDimensions } from "react-native";
import { WhoVaQuestionControls } from "@drguptavivek/who-2022-va/native";
import type { InstrumentQuestion } from "@drguptavivek/who-2022-va";

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
  const { width } = useWindowDimensions();
  const choiceColumns = width < 480 ? 1 : width < 900 ? 2 : 3;
  return (
    <View>
      {narrative ? <NarrativePanel key="narrative" data={narrative} choiceColumns={choiceColumns} onSave={onSaveNarrative} /> : null}
      {socialAutopsy ? <SocialAutopsyPanel key="social-autopsy" data={socialAutopsy} choiceColumns={choiceColumns} onSave={onSaveSocialAutopsy} /> : null}
    </View>
  );
}

/** Render and save the ordered server-defined narrative quality fields. */
function NarrativePanel({ data, choiceColumns, onSave }: { data: NarrativeQuality; choiceColumns: number; onSave(body: { cannot_grade: boolean; [key: string]: string | number | boolean }): Promise<void> }) {
  const [values, setValues] = useState<Record<string, number>>(() => data.saved?.values ?? {});
  const [cannotGrade, setCannotGrade] = useState(() => data.saved?.cannot_grade ?? false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setValues(data.saved?.values ?? {});
    setCannotGrade(data.saved?.cannot_grade ?? false);
  }, [data]);

  const complete = data.fields.every((field) => values[field.key] !== undefined);
  const score = cannotGrade ? 0 : data.fields.reduce((total, field) => total + (values[field.key] ?? 0), 0);
  const rating = cannotGrade ? "Cannot Grade" : !complete ? "Not Assessed" : score >= 7 ? "Good" : score >= 5 ? "Fair" : "Poor";

  return (
    <View style={styles.card}>
      <Text accessibilityRole="header" style={styles.headline}>Narrative quality</Text>
      {data.fields.map((field) => (
        <View key={field.key} style={{ marginTop: 16 }}>
          <Text style={styles.headline}>{field.label}</Text>
          <WhoVaQuestionControls.SingleChoice
            question={choiceQuestion(`nqa_${field.key}`, field.label, "singleChoice", field.options.map((option) => ({ value: String(option.value), label: option.label })), cannotGrade)}
            value={values[field.key] === undefined ? undefined : String(values[field.key])}
            data={{}}
            locale="en"
            issues={[]}
            choiceColumns={choiceColumns}
            onAnswer={(value) => {
              if (typeof value === "string" && /^-?\d+$/.test(value)) {
                setValues((current) => ({ ...current, [field.key]: Number(value) }));
              }
            }}
          />
        </View>
      ))}
      <Text accessibilityLiveRegion="polite" style={styles.text}>Score: {complete || cannotGrade ? score : "—"} / {data.max_score} · {rating}</Text>
      <WhoVaQuestionControls.MultipleChoice
        question={choiceQuestion("nqa-cannot_grade", "Cannot grade", "multipleChoice", [{ value: "cannot_grade", label: "Cannot grade" }])}
        value={cannotGrade ? ["cannot_grade"] : []}
        data={{}}
        locale="en"
        issues={[]}
        choiceColumns={1}
        onAnswer={(value) => setCannotGrade(Array.isArray(value) && value.includes("cannot_grade"))}
      />
      <Button label="Save narrative quality" onPress={() => {
        setBusy(true);
        void onSave({ cannot_grade: cannotGrade, ...(cannotGrade ? {} : values) }).finally(() => setBusy(false));
      }} disabled={busy || (!cannotGrade && data.fields.some((field) => values[field.key] === undefined))} loading={busy} />
    </View>
  );
}

/** Require an answer for each server-defined delay level and keep `none` exclusive. */
function SocialAutopsyPanel({ data, choiceColumns, onSave }: { data: SocialAutopsy; choiceColumns: number; onSave(body: { selected_options: Array<{ delay_level: string; option_code: string }>; remark: string }): Promise<void> }) {
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
        <View key={question.delay_level} style={{ marginTop: 16 }}>
          <Text style={styles.headline}>{question.title}</Text>
          <WhoVaQuestionControls.MultipleChoice
            question={choiceQuestion(`social_autopsy_${question.delay_level}`, question.title, "multipleChoice", question.options.map((option) => ({ value: option.option_code, label: option.description ? `${option.label} — ${option.description}` : option.label })))}
            value={selected[question.delay_level] ?? []}
            data={{}}
            locale="en"
            issues={[]}
            choiceColumns={choiceColumns}
            onAnswer={(value) => {
              if (!Array.isArray(value)) return;
              const next = value.map(String);
              const currentOptions = selected[question.delay_level] ?? [];
              const choseNone = next.includes("none") && !currentOptions.includes("none");
              setSelected((state) => ({ ...state, [question.delay_level]: choseNone ? ["none"] : next.filter((option) => option !== "none") }));
            }}
          />
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

/** Adapt quality metadata to the same native choice controls used by the VA form. */
function choiceQuestion(name: string, label: string, control: "singleChoice" | "multipleChoice", options: Array<{ value: string; label: string }>, readOnly = false): InstrumentQuestion {
  return {
    name,
    order: 0,
    sourceRow: 0,
    sourceType: "coding_quality",
    dataType: control === "multipleChoice" ? "string[]" : "string",
    control,
    label: { en: label },
    hint: {},
    guidance: {},
    required: true,
    readOnly,
    constraintMessage: {},
    sectionPath: [],
    choices: options.map((option, index) => ({ ...option, label: { en: option.label }, sourceRow: index }))
  };
}
