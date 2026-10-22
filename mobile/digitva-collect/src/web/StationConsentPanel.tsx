import { useEffect, useState } from "react";
import { Text, View } from "react-native";

import type { ClientCsrf } from "../api";
import {
  allRequiredPurposesGranted, buildSortedPurposeChoices, fetchProjectConsentConfig, selectActiveNoticeVersion,
  verifyNoticeTextSha256, type ConsentNoticeVersion, type ConsentRecordEnvelope,
} from "../consent";
import { t } from "../i18n";
import { Button, useUiStyles } from "../ui";

/**
 * Respondent consent for the informant details of a station registration (offline always needs it,
 * contract 5.5). Shows the project's own notice from the station config, one toggle per purpose,
 * and reports a granted envelope once every required purpose is on; `null` until then.
 * Refusal is not recorded here: the user clears the informant fields instead.
 */
export function StationConsentPanel({ projectId, csrf, onChange }: {
  projectId: string;
  csrf: ClientCsrf;
  onChange: (envelope: ConsentRecordEnvelope | null) => void;
}) {
  const styles = useUiStyles();
  const [notice, setNotice] = useState<ConsentNoticeVersion | null>(null);
  const [failed, setFailed] = useState(false);
  const [granted, setGranted] = useState<Record<string, boolean>>({});
  const [clientId] = useState(() => globalThis.crypto.randomUUID());

  useEffect(() => {
    let live = true;
    fetchProjectConsentConfig(projectId, csrf)
      .then((config) => {
        if (!live) return;
        const active = selectActiveNoticeVersion(config);
        if (active && verifyNoticeTextSha256(active)) setNotice(active);
        else setFailed(true);
      })
      .catch(() => live && setFailed(true));
    return () => { live = false; };
  }, [projectId, csrf]);

  useEffect(() => {
    if (!notice || !allRequiredPurposesGranted(notice, granted)) {
      onChange(null);
      return;
    }
    onChange({
      client_id: clientId,
      client_draft_id: null,
      notice_version_id: notice.notice_version_id,
      notice_language: notice.language,
      notice_sha256: notice.text_sha256,
      decision: "granted",
      purposes: buildSortedPurposeChoices(notice, granted),
      mode: "spoken",
      witness_present: false,
      supersedes_client_id: null,
      recorded_at: new Date().toISOString(),
    });
    // onChange is a state setter in the parent; the envelope follows the toggles only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [notice, granted, clientId]);

  if (failed) return <Text style={styles.error} accessibilityRole="alert">{t("stationConsentNoNotice")}</Text>;
  if (!notice) return null;
  return (
    <View style={styles.card} testID="station-consent">
      <Text style={styles.text}>{t("stationConsentHeading")}</Text>
      <Text style={styles.muted}>{t("stationConsentIntro")}</Text>
      <Text style={styles.text}>{notice.text}</Text>
      {[...notice.purposes].sort((a, b) => a.code.localeCompare(b.code)).map((purpose) => (
        <Button
          key={purpose.code}
          size="sm"
          kind={granted[purpose.code] ? "primary" : "secondary"}
          label={`${granted[purpose.code] ? "[x] " : "[ ] "}${purpose.label} (${t(purpose.required ? "stationConsentRequired" : "stationConsentOptional")})`}
          onPress={() => setGranted((previous) => ({ ...previous, [purpose.code]: !previous[purpose.code] }))}
        />
      ))}
    </View>
  );
}
