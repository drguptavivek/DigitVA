import { View } from "react-native";

import type { JsonObject, JsonValue } from "./contracts";
import { Badge, Body, Card, CardTitle, Muted, gap } from "./doris/ui";

const RANKS = ["Primary", "Secondary", "Tertiary"] as const;

function record(value: JsonValue | undefined): JsonObject {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as JsonObject : {};
}

/** Text of a served scalar; "NaN", null and "" are no value, as the web SmartVA table skips them. */
export function servedText(value: JsonValue | undefined): string {
  if (typeof value !== "string" && typeof value !== "number") return "";
  const text = String(value).trim();
  return text === "NaN" ? "" : text;
}

/** "28.0" -> "28": an integral age shows without its decimal point; anything else is returned as served. */
export function wholeNumberText(text: string): string {
  const number = Number(text);
  return text !== "" && Number.isInteger(number) ? String(number) : text;
}

/**
 * The SmartVA result as the web "SmartVA Analysis" table shows it: age, gender, the key symptoms by rank, each cause
 * with its ICD-10 code, ICD-11 mapping badge and likelihood, then the symptom chips. Causes with no name are skipped.
 */
export function SmartVaReference({ value }: { value: JsonValue }) {
  const data = record(value);
  const keySymptoms = Array.isArray(data.key_symptoms) ? data.key_symptoms : [];
  const causes = (Array.isArray(data.causes) ? data.causes : []).map(record).filter((cause) => servedText(cause.cause) !== "");
  const symptoms = Array.isArray(data.symptoms) ? data.symptoms.map(servedText).filter(Boolean) : [];
  const age = wholeNumberText(servedText(data.age));
  const gender = servedText(data.gender);
  return (
    <Card>
      <CardTitle>SmartVA Analysis</CardTitle>
      {age ? <Body>Age: {age}</Body> : null}
      {gender ? <Body>Gender: {gender}</Body> : null}
      {keySymptoms.slice(0, RANKS.length).map((symptom, index) => servedText(symptom) ? <Body key={`key-${index}`}>{RANKS[index]} Key Symptom: {servedText(symptom)}</Body> : null)}
      {causes.map((cause, index) => {
        const rank = Number(cause.rank);
        const label = RANKS[(Number.isInteger(rank) && rank >= 1 && rank <= RANKS.length ? rank : index + 1) - 1];
        const icd10 = servedText(cause.icd10);
        const icd11 = servedText(cause.icd11_label) || servedText(cause.icd11);
        const likelihood = servedText(cause.likelihood);
        return (
          <View key={`cause-${index}`} style={{ gap: gap.xs }}>
            <Body>{label} Cause of Death: {servedText(cause.cause)}</Body>
            {icd10 ? (
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: gap.xs }}>
                <Badge variant="secondary">{`ICD-10: ${icd10}`}</Badge>
                <Badge variant="outline">{`ICD-11 mapping: ${icd11 || "unavailable"}`}</Badge>
              </View>
            ) : null}
            {likelihood ? <Muted>{label} Likelihood: {likelihood}</Muted> : null}
          </View>
        );
      })}
      {symptoms.length ? (
        <View style={{ gap: gap.xs }}>
          <Muted>SmartVA Symptoms</Muted>
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: gap.xs }}>
            {symptoms.map((symptom, index) => <Badge key={`symptom-${index}`} variant="outline">{symptom}</Badge>)}
          </View>
        </View>
      ) : null}
    </Card>
  );
}
