/** App language picker. The questionnaire's own language is chosen on the form. */
import { useRouter } from "expo-router";

import { useAppState } from "../src/AppState";
import { t, UI_LOCALES } from "../src/i18n";
import { Button, Screen } from "../src/ui";

export default function Settings() {
  const router = useRouter();
  const { uiLocale, chooseUiLocale } = useAppState();
  return (
    <Screen title={t("appLanguage")}>
      {UI_LOCALES.map((locale) => (
        <Button
          key={locale.code}
          kind={locale.code === uiLocale ? "primary" : "secondary"}
          label={locale.label}
          onPress={() => void chooseUiLocale(locale.code)}
        />
      ))}
      <Button kind="secondary" label={t("home")} onPress={() => router.back()} />
    </Screen>
  );
}
