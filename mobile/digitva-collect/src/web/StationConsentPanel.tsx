import { useEffect, useState } from "react";
import { Text, View } from "react-native";

import type { ClientCsrf } from "../api";
import {
  allRequiredPurposesGranted, buildSortedPurposeChoices, fetchProjectConsentConfig, selectActiveNoticeVersion,
  verifyNoticeTextSha256, type ConsentMode, type ConsentNoticeVersion, type ConsentRecordEnvelope,
  type ProjectConsentConfig,
} from "../consent";
import { t } from "../i18n";
import { Button, useUiStyles } from "../ui";

/** The notice text and one toggle per purpose (sorted by code), shared by both consent panels. */
function NoticeAndPurposes({ notice, granted, onToggle }: {
  notice: ConsentNoticeVersion;
  granted: Record<string, boolean>;
  onToggle: (code: string) => void;
}) {
  const styles = useUiStyles();
  return (
    <>
      <Text style={styles.text}>{notice.text}</Text>
      {[...notice.purposes].sort((a, b) => a.code.localeCompare(b.code)).map((purpose) => (
        <Button
          key={purpose.code}
          size="sm"
          kind={granted[purpose.code] ? "primary" : "secondary"}
          label={`${granted[purpose.code] ? "[x] " : "[ ] "}${purpose.label} (${t(purpose.required ? "stationConsentRequired" : "stationConsentOptional")})`}
          onPress={() => onToggle(purpose.code)}
        />
      ))}
    </>
  );
}

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
      <NoticeAndPurposes
        notice={notice}
        granted={granted}
        onToggle={(code) => setGranted((previous) => ({ ...previous, [code]: !previous[code] }))}
      />
    </View>
  );
}

const MODE_LABEL = { spoken: "consentModeSpoken", tap: "consentModeTap", signed: "consentModeSigned" } as const;

/**
 * The web's respondent consent screen (digitva-athy, owner 2026-10-22): the project's newest notice
 * in the chosen language (*language* first, switchable), one toggle per purpose, how consent was
 * given (the version's allowed modes) and a witness flag where the version allows one. The user
 * records an explicit decision: agree (every required purpose on) or refuse (every purpose off).
 * The envelope (contract 5.3) goes to *onDecision*; the caller sends it to the server.
 */
export function RespondentConsentPanel({ config, language, clientDraftId, busy, onDecision }: {
  config: ProjectConsentConfig | null;
  language: string;
  clientDraftId: string | null;
  busy?: boolean;
  onDecision: (envelope: ConsentRecordEnvelope) => void;
}) {
  const styles = useUiStyles();
  const languages = [...new Set((config?.notice_versions ?? []).filter(verifyNoticeTextSha256).map((v) => v.language))].sort();
  const [chosenLanguage, setChosenLanguage] = useState(language);
  const notice = selectActiveNoticeVersion(config, chosenLanguage);
  const [granted, setGranted] = useState<Record<string, boolean>>({});
  const allowedModes = notice?.allowed_modes ?? [];
  const [mode, setMode] = useState<ConsentMode | null>(null);
  const [witness, setWitness] = useState(false);
  const chosenMode = mode && allowedModes.includes(mode) ? mode : allowedModes.includes("spoken") ? "spoken" : allowedModes[0];

  if (!notice || !chosenMode) {
    return <Text style={styles.error} accessibilityRole="alert" testID="respondent-consent-no-notice">{t("consentNoNotice")}</Text>;
  }

  function decide(decision: "granted" | "refused") {
    if (!notice || !chosenMode) return;
    onDecision({
      client_id: globalThis.crypto.randomUUID(),
      client_draft_id: clientDraftId,
      notice_version_id: notice.notice_version_id,
      notice_language: notice.language,
      notice_sha256: notice.text_sha256,
      decision,
      // A refusal answers every purpose no: the decision is refused exactly when a required one is.
      // (Explicit false: an unanswered purpose would default to its required flag.)
      purposes: buildSortedPurposeChoices(
        notice,
        decision === "granted" ? granted : Object.fromEntries(notice.purposes.map((p) => [p.code, false])),
      ),
      mode: chosenMode,
      witness_present: notice.witness_allowed && witness,
      supersedes_client_id: null,
      recorded_at: new Date().toISOString(),
    });
  }

  return (
    <View style={styles.card} testID="respondent-consent">
      <Text style={styles.headline}>{t("consentHeading")}</Text>
      <Text style={styles.muted}>{t("consentIntro")}</Text>
      {languages.length > 1 ? (
        <View style={styles.row}>
          {languages.map((code) => (
            <Button
              key={code}
              size="sm"
              kind={code === notice.language ? "primary" : "secondary"}
              label={code}
              onPress={() => { setChosenLanguage(code); setGranted({}); }}
            />
          ))}
        </View>
      ) : null}
      <NoticeAndPurposes
        notice={notice}
        granted={granted}
        onToggle={(code) => setGranted((previous) => ({ ...previous, [code]: !previous[code] }))}
      />
      {allowedModes.length > 1 ? (
        <>
          <Text style={styles.fieldLabel}>{t("consentModeLabel")}</Text>
          <View style={styles.row}>
            {allowedModes.map((value) => (
              <Button
                key={value}
                size="sm"
                kind={value === chosenMode ? "primary" : "secondary"}
                label={t(MODE_LABEL[value])}
                onPress={() => setMode(value)}
              />
            ))}
          </View>
        </>
      ) : null}
      {notice.witness_allowed ? (
        <Button
          size="sm"
          kind={witness ? "primary" : "secondary"}
          label={`${witness ? "[x] " : "[ ] "}${t("consentWitnessPresent")}`}
          onPress={() => setWitness((previous) => !previous)}
        />
      ) : null}
      <View style={styles.row}>
        <Button
          label={t("consentAgree")}
          disabled={busy || !allRequiredPurposesGranted(notice, granted)}
          loading={busy}
          onPress={() => decide("granted")}
        />
        <Button kind="secondary" label={t("consentRefuse")} disabled={busy} onPress={() => decide("refused")} />
      </View>
      {!allRequiredPurposesGranted(notice, granted) ? <Text style={styles.muted}>{t("consentAgreeHint")}</Text> : null}
    </View>
  );
}
