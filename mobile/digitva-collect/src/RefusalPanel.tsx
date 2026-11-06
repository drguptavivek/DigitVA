import { Pressable, Text, View } from "react-native";
import { translate, type ThemeStringKey } from "./i18n";
import { Button, useUiStyles } from "./ui";

export function RefusalPanel({ locale, age, sex, onAge, onSex, onSave, onChangeConsent, onNew }: {
  locale: string; age: string; sex: string; onAge: (value: string) => void; onSex: (value: string) => void;
  onSave: () => void; onChangeConsent: () => void; onNew: () => void;
}) {
  const styles = useUiStyles();
  // `locale` is the interview's language, which may differ from the app's: the text follows it.
  const say = (key: ThemeStringKey) => translate(locale, key);
  const ages = [["neonate", say("refusalPanelNeonate")], ["child", say("refusalPanelChild")], ["15_49y", "15–49"], ["50_64y", "50–64"], ["65_plus", "65+"], ["unknown", say("refusalPanelUnknown")]];
  const sexes = [["male", say("refusalPanelMale")], ["female", say("refusalPanelFemale")], ["unknown", say("refusalPanelUnknown")]];
  const choices = (items: string[][], selected: string, choose: (value: string) => void) => (
    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
      {items.map(([value, label]) => <Pressable key={value} accessibilityRole="radio" accessibilityState={{ checked: selected === value }} onPress={() => choose(selected === value ? "" : value)} style={[styles.card, { padding: 8, borderWidth: selected === value ? 2 : 1 }]}><Text style={styles.text}>{label}</Text></Pressable>)}
    </View>
  );
  return <View style={{ gap: 12, padding: 16 }} testID="refusal-panel">
    <Text style={styles.headline}>{say("refusalPanelTitle")}</Text>
    <Text style={styles.text}>{say("refusalPanelLead")}</Text>
    <Text style={styles.text}>{say("refusalPanelAgeGroup")}</Text>{choices(ages, age, onAge)}
    <Text style={styles.text}>{say("refusalPanelSex")}</Text>{choices(sexes, sex, onSex)}
    <Button label={say("refusalPanelSave")} onPress={onSave} />
    <Button kind="secondary" label={say("refusalPanelChangeConsent")} onPress={onChangeConsent} />
    <Button kind="secondary" label={say("refusalPanelNew")} onPress={onNew} />
  </View>;
}
