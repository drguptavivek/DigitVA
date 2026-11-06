/**
 * The app-language choice (digitva-s028, docs/policy/expo-client.md "Adding a UI language"): one list, the bundled
 * languages plus the server's published ones (useUiLanguages), each name written in its own script and tagged with
 * its BCP 47 language for screen readers. Two or three languages are a compact segmented control at the end of the
 * row; four or more a row naming the current language that opens LanguageSheet. A language a native speaker has
 * not fully reviewed says "Machine-translated" under its name.
 */
import { useState } from "react";
import { Text, View } from "react-native";

import { useAppState } from "../AppState";
import { t, type UiLanguage } from "../i18n";
import { Icon, type IconName } from "../Icon";
import { BottomSheet } from "../nativeShell/BottomSheet";
import { controls, spacing, useTheme } from "../theme";
import { useUiLanguages } from "../uiPacks";
import { ListRow, SegmentedControl } from "../ui";
import { MenuChoiceRow } from "./controls";

/** From this many languages the choice is a list sheet; a segmented control holds two or three. */
export const LANGUAGE_LIST_FROM = 4;

/** A published language whose review share is known and below 1 (a bundled language the server does not list has none). */
export const machineTranslated = (language: UiLanguage | undefined): boolean =>
  language?.reviewed !== undefined && language.reviewed < 1;

/** The languages as a sheet of single-choice rows, the current one ticked; picking one closes it. */
export function LanguageSheet({ visible, title, languages, value, onChoose, onClose }: {
  visible: boolean; title: string; languages: UiLanguage[]; value: string; onChoose(code: string): void; onClose(): void;
}) {
  return (
    <BottomSheet visible={visible} title={title} onClose={onClose}>
      <View accessibilityRole="radiogroup" accessibilityLabel={title} testID="language-sheet">
        {languages.map((language) => (
          <MenuChoiceRow
            key={language.code}
            label={language.label}
            language={language.language}
            detail={machineTranslated(language) ? t("uiLanguageMachineTranslated") : undefined}
            selected={language.code === value}
            onPress={() => onChoose(language.code)}
          />
        ))}
      </View>
    </BottomSheet>
  );
}

/**
 * A grouped-card row choosing the app language (Settings, the Account sheet). `icon`: the row's leading glyph, so its
 * label lines up with glyph rows in the same card.
 */
export function UiLanguageRow({ label, icon, testID }: { label: string; icon?: IconName; testID?: string }) {
  const { uiLocale, chooseUiLocale } = useAppState();
  const { ui, typography, textScale } = useTheme();
  const languages = useUiLanguages();
  const [open, setOpen] = useState(false);
  const current = languages.find((language) => language.code === uiLocale);
  const note = machineTranslated(current) ? t("uiLanguageMachineTranslated") : undefined;
  const choose = (code: string) => {
    setOpen(false);
    if (code !== uiLocale) void chooseUiLocale(code);
  };
  if (languages.length >= LANGUAGE_LIST_FROM) {
    return (
      <>
        <ListRow testID={testID} icon={icon} label={label} secondary={note} value={current?.label} accessibilityLabel={[label, current?.label, note].filter(Boolean).join(", ")} onPress={() => setOpen(true)} />
        <LanguageSheet visible={open} title={label} languages={languages} value={uiLocale} onChoose={choose} onClose={() => setOpen(false)} />
      </>
    );
  }
  // Settings' labelled-row geometry (as Mode and Text size): the label keeps its words, the compact (36pt) control
  // takes the rest of the row up to 240pt, so the row stays 48pt and the controls of one card line up.
  return (
    <View testID={testID} style={{ minHeight: (note ? 56 : 48) * Math.max(1, textScale), flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingHorizontal: spacing.md, paddingVertical: spacing.xs }}>
      {icon ? <View style={{ marginRight: spacing.xxs }}><Icon name={icon} color={ui.primary} size={24} /></View> : null}
      <View style={{ flexShrink: 1 }}>
        <Text style={{ ...typography.body, color: ui.foreground, fontFamily: controls.fontFamily }}>{label}</Text>
        {note ? <Text style={{ ...typography.subhead, color: ui.mutedForeground, fontFamily: controls.fontFamily }}>{note}</Text> : null}
      </View>
      <View testID="language-control" style={{ flex: 1, maxWidth: 240, marginLeft: "auto" }}>
        <SegmentedControl
          compact
          accessibilityLabel={label}
          options={languages.map((language) => ({ value: language.code, label: language.label, language: language.language }))}
          value={uiLocale}
          onChange={choose}
        />
      </View>
    </View>
  );
}
