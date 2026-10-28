import type { ReactNode } from "react";

/** Browser builds do not show the native-device coding preference prompt. */
export default function NativeIcd11DorisFirstLaunchGate({ children }: { children: ReactNode }) {
  return children;
}
