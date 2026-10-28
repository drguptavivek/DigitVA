import { Pressable, Text, View } from "react-native";
import { Button, useUiStyles } from "./ui";

export function RefusalPanel({ locale, age, sex, onAge, onSex, onSave, onChangeConsent, onNew }: {
  locale: string; age: string; sex: string; onAge: (value: string) => void; onSex: (value: string) => void;
  onSave: () => void; onChangeConsent: () => void; onNew: () => void;
}) {
  const styles = useUiStyles();
  const hi = locale.startsWith("hi");
  const ages = [["neonate", hi ? "नवजात" : "Neonate"], ["child", hi ? "बच्चा" : "Child"], ["15_49y", "15–49"], ["50_64y", "50–64"], ["65_plus", "65+"], ["unknown", hi ? "अज्ञात" : "Unknown"]];
  const sexes = [["male", hi ? "पुरुष" : "Male"], ["female", hi ? "महिला" : "Female"], ["unknown", hi ? "अज्ञात" : "Unknown"]];
  const choices = (items: string[][], selected: string, choose: (value: string) => void) => (
    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
      {items.map(([value, label]) => <Pressable key={value} accessibilityRole="radio" accessibilityState={{ checked: selected === value }} onPress={() => choose(selected === value ? "" : value)} style={[styles.card, { padding: 8, borderWidth: selected === value ? 2 : 1 }]}><Text style={styles.text}>{label}</Text></Pressable>)}
    </View>
  );
  return <View style={{ gap: 12, padding: 16 }} testID="refusal-panel">
    <Text style={styles.headline}>{hi ? "साक्षात्कार से इनकार" : "Interview refused"}</Text>
    <Text style={styles.text}>{hi ? "साक्षात्कार आगे नहीं बढ़ेगा। ये विवरण वैकल्पिक हैं।" : "The interview will not continue. These details are optional."}</Text>
    <Text style={styles.text}>{hi ? "आयु समूह" : "Age group"}</Text>{choices(ages, age, onAge)}
    <Text style={styles.text}>{hi ? "लिंग" : "Sex"}</Text>{choices(sexes, sex, onSex)}
    <Button label={hi ? "इनकार सहेजें" : "Save refusal"} onPress={onSave} />
    <Button kind="secondary" label={hi ? "सहमति बदलें" : "Change consent"} onPress={onChangeConsent} />
    <Button kind="secondary" label={hi ? "नया साक्षात्कार" : "New interview"} onPress={onNew} />
  </View>;
}
