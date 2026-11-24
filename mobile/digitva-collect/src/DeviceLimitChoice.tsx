/**
 * Device limit reached at sign-in (docs/policy/mobile-sign-in.md, replacing a phone at sign-in): the server's
 * `409 device_limit` lists the account's signed-in phones; the person may sign one out and retry the same sign-in
 * with `replace_device_id`, or cancel back to the form. The enrol screen's project choice is the pattern: a Screen,
 * one grouped card of rows, a text Cancel; the confirm is Settings' device-removal Alert.
 */
import { ErrorCode } from "./errorCodes";
import { Alert, Text, View } from "react-native";

import { ApiError } from "./api";
import { t } from "./i18n";
import { formatWhen } from "./ui/interviewRows";
import { Card, ListRow, Screen, Separator, TextLink, useUiStyles } from "./ui";

/** One signed-in phone in a `device_limit` reply. */
export type LimitPhone = { device_id: string; label: string | null; last_seen_at: string | null; unsent_count: number | null };

/**
 * The phones a `409 device_limit` offers, keeping only well-formed entries (the reply is untrusted); undefined for
 * any other error or an older server's reply without them, which keeps the plain `deviceLimit` message.
 */
export function deviceLimitPhones(error: unknown): LimitPhone[] | undefined {
  if (!(error instanceof ApiError) || error.code !== ErrorCode.DEVICE_LIMIT || !Array.isArray(error.payload?.devices)) return undefined;
  const phones = (error.payload.devices as unknown[]).filter((item): item is LimitPhone => {
    const phone = item as Partial<LimitPhone> | null;
    return typeof phone?.device_id === "string" && !!phone.device_id
      && (phone.label == null || typeof phone.label === "string")
      && (phone.last_seen_at == null || typeof phone.last_seen_at === "string")
      && (phone.unsent_count == null || (Number.isInteger(phone.unsent_count) && phone.unsent_count >= 0));
  });
  return phones.length ? phones : undefined;
}

const phoneName = (phone: LimitPhone) => phone.label || t("deviceLimitUnnamed");
const unsentText = (phone: LimitPhone) =>
  phone.unsent_count ? t("deviceLimitUnsent", { count: phone.unsent_count }) : "";

export function DeviceLimitChoice({ phones, busy, onPick, onCancel }: {
  phones: LimitPhone[];
  busy: boolean;
  /** Retry the refused sign-in with this phone as `replace_device_id`. */
  onPick: (deviceId: string) => void;
  onCancel: () => void;
}) {
  const styles = useUiStyles();

  function confirm(phone: LimitPhone) {
    Alert.alert(t("deviceLimitConfirmTitle"), [t("deviceLimitConfirmBody", { name: phoneName(phone) }), unsentText(phone)].filter(Boolean).join("\n\n"), [
      { text: t("cancel"), style: "cancel" },
      { text: t("deviceLimitConfirm"), style: "destructive", onPress: () => onPick(phone.device_id) },
    ]);
  }

  return (
    <Screen title={t("deviceLimitTitle")}>
      <Text style={styles.muted}>{t("deviceLimitBody")}</Text>
      <Card grouped>
        {phones.map((phone, index) => {
          const seen = formatWhen(phone.last_seen_at);
          const unsent = unsentText(phone);
          return (
            <View key={phone.device_id}>
              {index ? <Separator /> : null}
              <ListRow
                testID={`limit-device-${phone.device_id}`}
                label={phoneName(phone)}
                secondary={[seen ? t("deviceLimitLastSeen", { time: seen }) : "", unsent].filter(Boolean).join("\n") || undefined}
                // Unsent work on that phone: the attention (accent tint) row, as Unsent is everywhere else.
                tone={unsent ? "attention" : undefined}
                disabled={busy}
                onPress={() => confirm(phone)}
              />
            </View>
          );
        })}
      </Card>
      <TextLink label={t("cancel")} disabled={busy} onPress={onCancel} />
    </Screen>
  );
}
