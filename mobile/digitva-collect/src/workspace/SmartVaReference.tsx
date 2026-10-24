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

const PREVIOUS = "Previous diagnosis of ";
const NARRATIVE = "Open Response Word: ";

/** Splits the served symptoms into the grouped lines and the rest; the age quartile is dropped (the age is shown). */
function groupSymptoms(symptoms: string[]) {
  const previous: string[] = [];
  const narrative: string[] = [];
  const other: string[] = [];
  for (const symptom of symptoms) {
    if (symptom.startsWith(PREVIOUS)) previous.push(symptom.slice(PREVIOUS.length));
    else if (symptom.startsWith(NARRATIVE)) narrative.push(symptom.slice(NARRATIVE.length));
    else if (!symptom.startsWith("Age quartile")) other.push(symptom);
  }
  return { previous, narrative, other };
}

/**
 * The SmartVA result as a compact card: age and gender, the ranked causes (likelihood badge, ICD-10 and ICD-11 line),
 * the de-duplicated key symptoms, then the symptoms with previous diagnoses and narrative words grouped.
 * Causes with no name are skipped.
 */
export function SmartVaReference({ value }: { value: JsonValue }) {
  const data = record(value);
  const keySymptoms = Array.from(new Set((Array.isArray(data.key_symptoms) ? data.key_symptoms : []).map(servedText).filter(Boolean)));
  const causes = (Array.isArray(data.causes) ? data.causes : []).map(record).filter((cause) => servedText(cause.cause) !== "");
  const { previous, narrative, other } = groupSymptoms(Array.isArray(data.symptoms) ? data.symptoms.map(servedText).filter(Boolean) : []);
  const age = wholeNumberText(servedText(data.age));
  const demographics = [age ? `${age} years` : "", servedText(data.gender)].filter(Boolean).join(" · ");
  return (
    <Card>
      <CardTitle>SmartVA Analysis</CardTitle>
      {demographics ? <Muted>{demographics}</Muted> : null}
      {causes.map((cause, index) => {
        const rank = Number(cause.rank);
        const position = Number.isInteger(rank) && rank >= 1 && rank <= RANKS.length ? rank : index + 1;
        const icd10 = servedText(cause.icd10);
        const icd11 = servedText(cause.icd11_label) || servedText(cause.icd11);
        const likelihood = servedText(cause.likelihood);
        return (
          <View key={`cause-${index}`} style={{ gap: 2 }}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: gap.xs }}>
              <Body>{position}</Body>
              <Body style={{ fontWeight: "700", flexShrink: 1 }}>{servedText(cause.cause)}</Body>
              {likelihood ? <Badge variant="secondary">{likelihood}</Badge> : null}
            </View>
            {icd10 ? <Muted>{`ICD-10 ${icd10} · ICD-11 ${icd11 || "unavailable"}`}</Muted> : null}
          </View>
        );
      })}
      {keySymptoms.length ? <Body><Body style={{ fontWeight: "700" }}>Key symptoms: </Body>{keySymptoms.join(", ")}</Body> : null}
      {previous.length ? <Body>Previous diagnoses: {previous.join(", ")}</Body> : null}
      {narrative.length ? <Body>Narrative words: {narrative.join(", ")}</Body> : null}
      {other.length ? (
        <View style={{ gap: gap.xs }}>
          <Muted>Other symptoms</Muted>
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: gap.xs }}>
            {other.map((symptom, index) => <Badge key={`symptom-${index}`} variant="outline">{symptom}</Badge>)}
          </View>
        </View>
      ) : null}
    </Card>
  );
}
