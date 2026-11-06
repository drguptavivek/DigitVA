/** What app/_layout.tsx mounts: native = the phone shell (this folder); the browser keeps src/web/AppHeader.web.tsx (chrome.web.tsx). */
import type { ReactNode } from "react";

import { IosDatePickerHost } from "../IosDatePickerHost";
import { NativeHeader, NativeTabs } from "./NativeChrome";
import { ShellProvider } from "./shell";

// The iOS date picker host sits beside every screen, since the WHO form asks for dates imperatively (src/platform.ts).
export const ShellRoot = ({ children }: { children: ReactNode }) => (
  <ShellProvider>
    {children}
    <IosDatePickerHost />
  </ShellProvider>
);
export const ShellHeader = NativeHeader;
export const ShellTabs = NativeTabs;
