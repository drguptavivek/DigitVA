import type { ReactNode } from "react";

import AppHeader, { BottomTabs } from "../web/AppHeader";

/** Browser: no shell provider; the existing header and bottom bar. */
export const ShellRoot = ({ children }: { children: ReactNode }) => <>{children}</>;
export const ShellHeader = AppHeader;
export const ShellTabs = BottomTabs;
