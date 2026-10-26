import { useEffect, useState } from "react";
import { Pressable, Text, View } from "react-native";

import type { ClientCsrf } from "../api";
import {
  allRequiredPurposesGranted, buildSortedPurposeChoices, fetchProjectConsentConfig, selectActiveNoticeVersion,
  verifyNoticeTextSha256, type ConsentMode, type ConsentNoticeVersion, type ConsentRecordEnvelope,
  type ProjectConsentConfig,
} from "../consent";
import { t } from "../i18n";
import { controls, fontSize, radius, spacing, typography, useTheme } from "../theme";
import { Button, useUiStyles } from "../ui";

const LANGUAGE_LABELS: Record<string, string> = {
  en: "English",
  hi: "हिन्दी",
};

/** Left-aligned checkbox card row for consent purposes and witness presence. */
function ConsentCheckboxRow({
  label,
  checked,
  badge,
  required,
  testID,
  onPress,
}: {
  label: string;
  checked: boolean;
  badge?: string;
  required?: boolean;
  testID?: string;
  onPress: () => void;
}) {
  const { colors } = useTheme();
  return (
    <Pressable
      accessibilityRole="checkbox"
      accessibilityState={{ checked }}
      accessibilityLabel={badge ? `${label} (${badge})` : label}
      testID={testID}
      onPress={onPress}
      style={({ pressed }) => ({
        flexDirection: "row",
        alignItems: "flex-start",
        gap: spacing.sm,
        paddingVertical: spacing.sm,
        paddingHorizontal: spacing.md,
        borderRadius: radius.md,
        borderWidth: 1,
        borderColor: checked ? colors.accent : colors.borderStrong,
        backgroundColor: checked ? colors.accentSoft : colors.surface,
        opacity: pressed ? 0.88 : 1,
      })}
    >
      <View
        style={{
          width: 20,
          height: 20,
          marginTop: 2,
          borderRadius: radius.sm,
          borderWidth: 1,
          borderColor: checked ? colors.accent : colors.borderStrong,
          backgroundColor: checked ? colors.accent : colors.surface,
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <Text
          style={{
            fontSize: fontSize.caption,
            lineHeight: 14,
            fontWeight: "700",
            color: checked ? colors.onAccent : "transparent",
            fontFamily: controls.fontFamily,
          }}
        >
          ✓
        </Text>
      </View>
      <Text
        style={{
          flex: 1,
          minWidth: 0,
          ...typography.body,
          fontWeight: checked ? "600" : "400",
          color: colors.text,
          fontFamily: controls.fontFamily,
          textAlign: "left",
        }}
      >
        {label}
      </Text>
      {badge ? (
        <View
          style={{
            paddingHorizontal: spacing.xs,
            paddingVertical: 2,
            borderRadius: radius.full,
            borderWidth: 1,
            borderColor: required ? colors.accent : colors.border,
            backgroundColor: required ? colors.accentSoft : colors.surfaceMuted,
          }}
        >
          <Text
            style={{
              ...typography.caption,
              fontWeight: "600",
              color: required ? colors.accent : colors.textMuted,
              fontFamily: controls.fontFamily,
            }}
          >
            {badge}
          </Text>
        </View>
      ) : null}
    </Pressable>
  );
}

/** The notice text and one toggle per purpose (sorted by code), shared by both consent panels. */
function NoticeAndPurposes({ notice, granted, onToggle, onSetAll }: {
  notice: ConsentNoticeVersion;
  granted: Record<string, boolean>;
  onToggle: (code: string) => void;
  onSetAll?: (next: Record<string, boolean>) => void;
}) {
  const styles = useUiStyles();
  const { colors } = useTheme();
  const sortedPurposes = [...notice.purposes].sort((a, b) => a.code.localeCompare(b.code));
  const allSelected = sortedPurposes.length > 0 && sortedPurposes.every((p) => Boolean(granted[p.code]));
  const paragraphs = notice.text.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean);
  return (
    <>
      <View
        testID="consent-notice-box"
        style={{
          backgroundColor: colors.surfaceMuted,
          borderColor: colors.border,
          borderWidth: 1,
          borderRadius: radius.md,
          padding: spacing.md,
          gap: spacing.xs,
        }}
      >
        {(paragraphs.length > 0 ? paragraphs : [notice.text]).map((paragraph, index) => (
          <Text key={index} style={styles.text}>{paragraph}</Text>
        ))}
      </View>
      <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: spacing.xs }}>
        <Text style={styles.fieldLabel}>{t("consentPurposesHeading")}</Text>
        {onSetAll && sortedPurposes.length > 1 ? (
          <Button
            size="sm"
            kind="secondary"
            label={allSelected ? t("consentClearAll") : t("consentSelectAll")}
            onPress={() => onSetAll(Object.fromEntries(sortedPurposes.map((p) => [p.code, !allSelected])))}
          />
        ) : null}
      </View>
      <View style={{ gap: spacing.xs }}>
        {sortedPurposes.map((purpose) => (
          <ConsentCheckboxRow
            key={purpose.code}
            testID={`consent-purpose-${purpose.code}`}
            label={purpose.label}
            checked={Boolean(granted[purpose.code])}
            required={purpose.required}
            badge={t(purpose.required ? "stationConsentRequired" : "stationConsentOptional")}
            onPress={() => onToggle(purpose.code)}
          />
        ))}
      </View>
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
        onSetAll={setGranted}
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
export function RespondentConsentPanel({ config, language, clientDraftId, busy, makeId, onDecision }: {
  config: ProjectConsentConfig | null;
  language: string;
  clientDraftId: string | null;
  busy?: boolean;
  /** The id of a new record; the phone passes expo-crypto's (Hermes has no global crypto), the browser's default is used otherwise. */
  makeId?: () => string;
  onDecision: (envelope: ConsentRecordEnvelope) => void;
}) {
  const styles = useUiStyles();
  const { colors } = useTheme();
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
      client_id: (makeId ?? (() => globalThis.crypto.randomUUID()))(),
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
              label={LANGUAGE_LABELS[code] ?? code.toUpperCase()}
              accessibilityLabel={code}
              onPress={() => { setChosenLanguage(code); setGranted({}); }}
            />
          ))}
        </View>
      ) : null}
      <NoticeAndPurposes
        notice={notice}
        granted={granted}
        onToggle={(code) => setGranted((previous) => ({ ...previous, [code]: !previous[code] }))}
        onSetAll={setGranted}
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
        <ConsentCheckboxRow
          testID="consent-witness-checkbox"
          label={t("consentWitnessPresent")}
          checked={witness}
          onPress={() => setWitness((previous) => !previous)}
        />
      ) : null}
      <View style={[styles.row, { borderTopWidth: 1, borderColor: colors.border, paddingTop: spacing.sm }]}>
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
