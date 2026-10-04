/** App language picker. The questionnaire's own language is chosen on the form. */
import { useRouter } from "expo-router";
import { Platform } from "react-native";

import { useAppState } from "../src/AppState";
import { t, UI_LOCALES } from "../src/i18n";
import { Button, Screen } from "../src/ui";
import { SettingsScreen as WebSettings } from "../src/browserScreens";

export default function Settings() {
  if (Platform.OS === "web") return <WebSettings />;
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
