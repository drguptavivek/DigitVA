import type React from "react";

/** Native has its own navigation; the shared browser header and bottom bar (AppHeader.web.tsx) render nothing here. */
export default function AppHeader() {
  return null;
}

export function AppHeaderBar(_props: { sticky?: boolean }) {
  return null;
}

export function BottomTabs() {
  return null;
}

/** Native has no app header: the help trigger stays where the screen puts it. */
export function HeaderHelpSlot({ children }: { children: (inHeader: boolean) => React.ReactNode }) {
  return <>{children(false)}</>;
}
