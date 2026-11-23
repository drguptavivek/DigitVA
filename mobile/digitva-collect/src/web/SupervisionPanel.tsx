import { Text } from "react-native";

import { t } from "../i18n";
import { SupervisionList } from "../supervision/SupervisionPanel";
import { useUiStyles } from "../ui";
import { useCanSupervise, useWebSupervisionHost } from "./supervisionHost";

/** The supervisor's part of the Deaths tab in the browser; the list itself is shared with the phone (src/supervision). */
export function SupervisionPanel() {
  const styles = useUiStyles();
  const host = useWebSupervisionHost();
  const canSupervise = useCanSupervise();
  if (!host) return null;
  if (!canSupervise) return <Text role="alert" style={styles.error}>{t("serverForbidden")}</Text>;
  return <SupervisionList host={host} />;
}
