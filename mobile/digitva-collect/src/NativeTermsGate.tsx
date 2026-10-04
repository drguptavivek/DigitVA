import type { ReactNode } from "react";

/** Browser terms acceptance remains part of the server session. */
export default function NativeTermsGate({ children }: { children: ReactNode }) {
  return children;
}
