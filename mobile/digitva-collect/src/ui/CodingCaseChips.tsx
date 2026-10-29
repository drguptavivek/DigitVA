import { useRouter } from "expo-router";
import { View } from "react-native";

import { t } from "../i18n";
import { useIcd11DorisPreference } from "../icd11DorisPreference";
import { Button } from "../ui";

/** The two sources of coding cases; online is the only chip that follows connectivity. */
export function CodingCaseChips({ userId, canLocal, offline }: { userId: string; canLocal: boolean; offline?: boolean }) {
  const router = useRouter();
  const preference = useIcd11DorisPreference();
  return (
    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }} accessibilityRole="tablist">
      {canLocal ? (
        <Button
          size="sm"
          kind="secondary"
          label={t("localCases")}
          disabled={!preference.enabled}
          style={{ flexGrow: 1, minWidth: 140 }}
          onPress={() => router.push({ pathname: "/offline-coding", params: { userId } })}
        />
      ) : null}
      <Button
        size="sm"
        label={t("onlineCases")}
        disabled={offline === true}
        style={{ flexGrow: 1, minWidth: 140 }}
        onPress={() => router.push({ pathname: "/coding", params: { userId } })}
      />
      <Button
        size="sm"
        kind="secondary"
        label={t("myCodedCases")}
        style={{ flexGrow: 1, minWidth: 140 }}
        onPress={() => router.push({ pathname: "/coding", params: { userId, initialHistory: "1" } })}
      />
    </View>
  );
}
