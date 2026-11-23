import { Text, View } from "react-native";

import { MONOSPACE } from "./IdentifierFields";
import { t } from "./i18n";
import type { CaseIdentifier } from "./identifiers";
import { useUiStyles } from "./ui";

/**
 * A case's registration numbers on a card or the detail. Value viewers see label first and the
 * number in monospace; a missing number shows nothing on a card and "Not yet issued" on the detail.
 * Badge-only viewers (no `value` key) see "<label>: recorded" or "<label>: missing".
 */
export function IdentifierFacts({ identifiers, variant }: { identifiers: CaseIdentifier[] | undefined; variant: "card" | "detail" }) {
  const styles = useUiStyles();
  if (!identifiers?.length) return null;
  // Per entry: no `value` key is a badge ("recorded"/"missing"); a null value is a type with no number yet.
  const rows = identifiers.flatMap((entry) => {
    if (!("value" in entry)) {
      return [<Text key={entry.code} style={styles.muted} testID={`identifier-badge-${entry.code}`}>
        {t(entry.present ? "idBadgeRecorded" : "idBadgeMissing", { label: entry.label })}
      </Text>];
    }
    if (!entry.value) {
      return variant === "detail"
        ? [<Text key={entry.code} style={styles.muted} testID={`identifier-value-${entry.code}`}>{entry.label}: {t("idNotYetIssued")}</Text>]
        : [];
    }
    return [<Text key={entry.code} style={variant === "detail" ? styles.text : styles.muted} testID={`identifier-value-${entry.code}`}>
      {entry.label}: <Text style={{ fontFamily: MONOSPACE }}>{entry.value}</Text>
    </Text>];
  });
  return rows.length ? <View style={{ gap: 2 }} testID="identifier-facts">{rows}</View> : null;
}
