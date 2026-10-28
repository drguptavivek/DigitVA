import { useEffect, useState } from "react";
import { Text, TextInput, View } from "react-native";

import { t } from "../i18n";
import { Button, useUiStyles } from "../ui";
import {
  defaultStandaloneNoticeSettings,
  loadStandaloneNoticeSettings,
  MAX_STANDALONE_NOTICE_LENGTH,
  saveStandaloneNoticeSettings,
  STANDALONE_NOTICE_LANGUAGES,
  validStandaloneNoticeText,
  type StandaloneNoticeLanguage,
  type StandaloneNoticeSettings,
} from "./noticeSettings";

export default function StandaloneConsentNoticeSettings() {
  const styles = useUiStyles();
  const [notices, setNotices] = useState<StandaloneNoticeSettings>(defaultStandaloneNoticeSettings);
  const [saved, setSaved] = useState<StandaloneNoticeSettings>();
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveFeedback, setSaveFeedback] = useState<"saved" | "failed">();

  useEffect(() => {
    let active = true;
    void loadStandaloneNoticeSettings().then((loaded) => {
      if (!active) return;
      setNotices(loaded);
      setSaved(loaded);
      setLoading(false);
    }).catch(() => {
      if (!active) return;
      setLoadFailed(true);
      setLoading(false);
    });
    return () => { active = false; };
  }, []);

  const valid = STANDALONE_NOTICE_LANGUAGES.every((language) => validStandaloneNoticeText(notices[language]));
  const dirty = saved !== undefined && STANDALONE_NOTICE_LANGUAGES.some((language) => notices[language] !== saved[language]);
  const updateNotice = (language: StandaloneNoticeLanguage, text: string) => {
    setNotices((current) => ({ ...current, [language]: text }));
    setSaveFeedback(undefined);
  };
  async function save() {
    if (!valid || saving) return;
    setSaving(true);
    setSaveFeedback(undefined);
    try {
      await saveStandaloneNoticeSettings(notices);
      setSaved(notices);
      setSaveFeedback("saved");
    } catch {
      setSaveFeedback("failed");
    } finally {
      setSaving(false);
    }
  }

  if (loading || loadFailed) {
    return <Text accessibilityRole={loadFailed ? "alert" : undefined} style={loadFailed ? styles.error : styles.muted}>
      {t(loadFailed ? "standaloneConsentNoticeLoadError" : "standaloneConsentNoticeLoading")}
    </Text>;
  }

  return (
    <View style={{ gap: 8 }}>
      <Text style={styles.muted}>{t("standaloneConsentNoticeIntro")}</Text>
      {STANDALONE_NOTICE_LANGUAGES.map((language) => (
        <View key={language} style={{ gap: 6 }}>
          <Text accessibilityRole="header" style={styles.text}>
            {t(language === "en" ? "standaloneConsentNoticeEnglish" : "standaloneConsentNoticeHindi")}
          </Text>
          <TextInput
            accessibilityLabel={t(language === "en" ? "standaloneConsentNoticeEnglish" : "standaloneConsentNoticeHindi")}
            multiline
            maxLength={MAX_STANDALONE_NOTICE_LENGTH}
            onChangeText={(text) => updateNotice(language, text)}
            scrollEnabled
            style={[styles.input, { height: 220, textAlignVertical: "top" }]}
            testID={`standalone-consent-notice-${language}`}
            value={notices[language]}
          />
        </View>
      ))}
      {!valid ? <Text accessibilityRole="alert" style={styles.error}>{t("standaloneConsentNoticeInvalid")}</Text> : null}
      <Button
        disabled={!dirty || !valid || saving}
        label={t("standaloneConsentNoticeSave")}
        loading={saving}
        onPress={() => void save()}
      />
      {saveFeedback ? (
        <Text accessibilityRole={saveFeedback === "failed" ? "alert" : undefined} style={saveFeedback === "failed" ? styles.error : styles.muted}>
          {t(saveFeedback === "saved" ? "standaloneConsentNoticeSaved" : "standaloneConsentNoticeSaveError")}
        </Text>
      ) : null}
    </View>
  );
}
