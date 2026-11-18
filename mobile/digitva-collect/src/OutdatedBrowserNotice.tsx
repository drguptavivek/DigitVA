import { useState } from "react";
import { Pressable } from "react-native";

import { ConfirmDialog } from "./ConfirmDialog";
import { Icon, icons } from "./Icon";
import { t } from "./i18n";
import { useTheme } from "./theme";

/** A warning icon beside the title row's actions; tapping it explains that the browser is too old (browserSupport). */
export function OutdatedBrowserNotice() {
  const { colors } = useTheme();
  const [open, setOpen] = useState(false);
  return (
    <>
      <Pressable
        testID="outdated-browser-warning"
        accessibilityRole="button"
        accessibilityLabel={t("outdatedBrowserTitle")}
        hitSlop={8}
        onPress={() => setOpen(true)}
        style={{ minWidth: 44, minHeight: 44, alignItems: "center", justifyContent: "center" }}
      >
        <Icon name={icons.warning} color={colors.warning} size={26} />
      </Pressable>
      {open ? (
        <ConfirmDialog
          title={t("outdatedBrowserTitle")}
          message={t("outdatedBrowserWarning")}
          confirmLabel={t("ok")}
          cancelLabel={null}
          onConfirm={() => setOpen(false)}
          onCancel={() => setOpen(false)}
        />
      ) : null}
    </>
  );
}
