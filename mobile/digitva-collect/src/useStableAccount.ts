import { useRef } from "react";

import type { Account } from "./auth";

/**
 * The account object for an open form. A background refresh replaces account
 * objects whose fields changed; keying the form's load on the new object would
 * remount it under the user. Gates still react to the live accounts list.
 */
export function useStableAccount(account: Account | undefined): Account | undefined {
  const ref = useRef(account);
  if (account?.user_id !== ref.current?.user_id) ref.current = account;
  return ref.current;
}
