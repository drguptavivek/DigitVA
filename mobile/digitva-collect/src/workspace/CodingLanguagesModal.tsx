import { useContext, useEffect, useState } from "react";
import { Modal, ScrollView, Text, View } from "react-native";
import { SafeAreaInsetsContext } from "react-native-safe-area-context";

import { t } from "../i18n";
import { controls } from "../theme";
import { Button, errorText, useUiStyles } from "../ui";
import { Checkbox } from "../ui/controls";
import type { JsonRequester } from "./api";
import { getCodingLanguageChoices, saveCodingLanguages, type CodingLanguageChoices } from "./codingLanguages";

/**
 * The coder's own coding languages (the ✎ after "Your languages"), in the app: Collect shows no web page
 * (digitva-mb0d.2). The current languages start ticked; Save needs at least one, as the server does, and calls
 * `onSaved` so the queue reloads its counts.
 */
export function CodingLanguagesModal({ request, onClose, onSaved }: { request: JsonRequester; onClose: () => void; onSaved: () => void }) {
  const styles = useUiStyles();
  const [choices, setChoices] = useState<CodingLanguageChoices | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    let live = true;
    getCodingLanguageChoices(request).then((loaded) => {
      if (!live) return;
      setChoices(loaded);
      // An inactive language cannot be saved, so only offered ones start ticked.
      setSelected(loaded.mine.filter((code) => loaded.available.some((language) => language.code === code)));
    }).catch((failure) => { if (live) setError(errorText(failure)); });
    return () => { live = false; };
  }, [request]);

  function toggle(code: string, checked: boolean) {
    setSelected((current) => (choices?.available ?? [])
      .map((language) => language.code)
      .filter((item) => item === code ? checked : current.includes(item)));
  }

  async function save() {
    setSaving(true);
    setError("");
    try {
      await saveCodingLanguages(request, selected);
      onSaved();
    } catch (failure) {
      setError(errorText(failure));
      setSaving(false);
    }
  }

  // A full-screen modal draws edge to edge on Android: keep the title clear of the status bar and the list of the nav bar.
  const insets = useContext(SafeAreaInsetsContext) ?? { top: 0, bottom: 0 };
  return (
    <Modal visible transparent={false} animationType="slide" onRequestClose={onClose}>
      <View style={[styles.safe, { paddingTop: insets.top, paddingBottom: insets.bottom }]}>
        <View testID="coding-languages-header" style={[styles.body, { gap: 8 }]}>
          <Text accessibilityRole="header" style={styles.headline}>{t("codingLanguagesTitle")}</Text>
          {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
          {choices === null && !error ? <Text style={styles.muted}>{t("loading")}</Text> : null}
          {choices !== null && !selected.length ? <Text style={styles.muted} testID="coding-languages-none">{t("codingLanguagesNoneSelected")}</Text> : null}
          {choices !== null ? <Button label={t("save")} testID="coding-languages-save" disabled={!selected.length || saving} loading={saving} style={{ minHeight: controls.minTouchTarget }} onPress={() => void save()} /> : null}
          <Button kind="secondary" label={t("codingLanguagesClose")} testID="coding-languages-close" style={{ minHeight: controls.minTouchTarget }} onPress={onClose} />
        </View>
        <ScrollView testID="coding-languages-list" contentContainerStyle={[styles.body, { gap: 8 }]}>
          {(choices?.available ?? []).map((language) => (
            <Checkbox
              key={language.code}
              checked={selected.includes(language.code)}
              onChange={(checked) => toggle(language.code, checked)}
              label={language.name.toLowerCase() === language.code.toLowerCase() ? language.name : `${language.name} (${language.code})`}
              testID={`coding-language-${language.code}`}
            />
          ))}
        </ScrollView>
      </View>
    </Modal>
  );
}
