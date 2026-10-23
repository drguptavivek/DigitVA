/** What app/_layout.tsx mounts: native = the phone shell (this folder); the browser keeps src/web/AppHeader.web.tsx (chrome.web.tsx). */
import type { ReactNode } from "react";

import { NativeHeader, NativeTabs } from "./NativeChrome";
import { ShellProvider } from "./shell";

export const ShellRoot = ({ children }: { children: ReactNode }) => <ShellProvider>{children}</ShellProvider>;
export const ShellHeader = NativeHeader;
export const ShellTabs = NativeTabs;
