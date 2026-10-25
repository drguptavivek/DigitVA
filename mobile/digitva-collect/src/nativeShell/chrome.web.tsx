import type { ReactNode } from "react";
import { View } from "react-native";

import AppHeader, { BottomTabs } from "../web/AppHeader";
import { useTheme } from "../theme";

/** Browser: no shell provider; the existing header and bottom bar. */
export function ShellRoot({ children }: { children: ReactNode }) {
  const { colors } = useTheme();
  return <View style={{ flex: 1, backgroundColor: colors.background }}>{children}</View>;
}
export const ShellHeader = AppHeader;
export const ShellTabs = BottomTabs;
