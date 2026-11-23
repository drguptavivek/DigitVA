import { useRouter } from "expo-router";

import { t } from "../i18n";
import { icons } from "../Icon";
import { Card, ListRow } from "../ui";

export const SUPERVISION_ROUTE = "/supervision";

/** Home's way in: one row, shown to accounts whose last /me/access answer reported supervision. */
export function SupervisionEntry({ userId }: { userId: string }) {
  const router = useRouter();
  return (
    <Card grouped testID="supervision-entry">
      <ListRow
        icon={icons.review}
        label={t("homeBlockSupervisor")}
        secondary={t("supervisionPhoneHint")}
        onPress={() => router.push({ pathname: SUPERVISION_ROUTE, params: { userId } } as never)}
      />
    </Card>
  );
}
