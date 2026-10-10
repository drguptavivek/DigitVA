import type { ReactNode } from "react";
import { Text, View } from "react-native";

import { styles } from "../ui";
import type { CategoryPayload, JsonValue } from "./contracts";

const ATTACHMENT_PATH = /^\/api\/v1\/attachments\/(?:legacy\/[^/?#]+\/[^/?#]+|[^/?#]+)(?:\.[a-zA-Z0-9]+)?$/;

/** Render ordered server category data as escaped native text and optional media slots. */
export function CategoryPanel({
  category,
  renderMedia,
}: {
  category: CategoryPayload;
  renderMedia?: (attachmentPath: string) => ReactNode;
  iconName?: string | null;
}) {
  return (
    <View accessibilityLabel={category.label}>
      <Text style={styles.headline}>{category.label}</Text>
      {category.summary_items.map((value, index) => (
        <CategoryValue key={`summary-${index}`} value={value} renderMedia={renderMedia} />
      ))}
      {category.subcategories.map((subcategory) => (
        <View key={subcategory.code} style={styles.card}>
          <Text style={styles.headline}>{subcategory.label}</Text>
          {subcategory.items.map((item, index) => (
            <View key={`${item.label}-${index}`}>
              <Text style={styles.muted}>{item.label}</Text>
              <CategoryValue value={item.value} renderMedia={renderMedia} />
              {item.flip ? <Text style={styles.muted}>Flipped</Text> : null}
              {item.info ? <Text style={styles.muted}>More information</Text> : null}
            </View>
          ))}
        </View>
      ))}
    </View>
  );
}

/** Render server values as labelled escaped text; attachment URLs go only through the supplied slot. */
export function CategoryValue({
  value,
  renderMedia,
}: {
  value: JsonValue;
  renderMedia?: (attachmentPath: string) => ReactNode;
}) {
  if (value === null || value === "") return null;
  if (typeof value === "string") {
    if (renderMedia && ATTACHMENT_PATH.test(value)) return <>{renderMedia(value)}</>;
    return <Text style={styles.text}>{value}</Text>;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return <Text style={styles.text}>{String(value)}</Text>;
  }
  if (Array.isArray(value)) {
    return (
      <View>
        {value.map((item, index) => <CategoryValue key={index} value={item} renderMedia={renderMedia} />)}
      </View>
    );
  }
  if (typeof value.label === "string" && "value" in value) {
    return (
      <View>
        <Text style={styles.muted}>{value.label}</Text>
        <CategoryValue value={value.value} renderMedia={renderMedia} />
      </View>
    );
  }
  return (
    <View>
      {Object.entries(value).map(([key, item]) => (
        <View key={key}>
          <Text style={styles.muted}>{valueLabels[key] ?? key.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase())}</Text>
          <CategoryValue value={item} renderMedia={renderMedia} />
        </View>
      ))}
    </View>
  );
}

const valueLabels: Record<string, string> = {
  age: "Age",
  gender: "Gender",
  key_symptoms: "Key symptoms",
  causes: "Predicted causes",
  rank: "Rank",
  cause: "Cause",
  icd10: "ICD-10",
  icd11: "ICD-11",
  likelihood: "Likelihood",
  symptoms: "Symptoms",
};
