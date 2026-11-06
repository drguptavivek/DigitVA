import { useRouter } from "expo-router";
import type { ReactNode } from "react";

import { icons } from "../Icon";
import { t } from "../i18n";
import { useIcd11DorisPreference } from "../icd11DorisPreference";
import { Card, ListRow, Separator } from "../ui";

/**
 * The coding case lists as rows of one grouped card (design sheet 01): each opens its list screen, so they are
 * navigation rows with chevrons, never buttons or a filter. Online is the only row that follows connectivity.
 * `leading`: other "go somewhere" rows of the screen (Home's Register a death) at the top of the same card, each
 * followed by an icon-inset Separator.
 */
export function CodingCaseChips({ userId, canLocal, offline, leading }: { userId: string; canLocal: boolean; offline?: boolean; leading?: ReactNode }) {
  const router = useRouter();
  const preference = useIcd11DorisPreference();
  return (
    <Card grouped testID="coding-case-lists">
      {leading}
      {canLocal ? (
        <>
          <ListRow
            icon={icons.localCases}
            label={t("localCases")}
            disabled={!preference.enabled}
            onPress={() => router.push({ pathname: "/offline-coding", params: { userId } })}
          />
          <Separator icon />
        </>
      ) : null}
      <ListRow
        icon={icons.onlineCases}
        label={t("onlineCases")}
        disabled={offline === true}
        onPress={() => router.push({ pathname: "/coding", params: { userId } })}
      />
      <Separator icon />
      <ListRow
        icon={icons.codedCases}
        label={t("myCodedCases")}
        onPress={() => router.push({ pathname: "/coding", params: { userId, initialHistory: "1" } })}
      />
    </Card>
  );
}
