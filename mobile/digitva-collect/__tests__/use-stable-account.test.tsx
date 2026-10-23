import React from "react";
import { act, create } from "react-test-renderer";

import { useStableAccount } from "../src/useStableAccount";

let seen: unknown;
function Probe({ account }: { account?: { user_id: string; n: number } }) {
  seen = useStableAccount(account as never);
  return null;
}

it("keeps the same account object for the same user so an open form is not reloaded", async () => {
  const first = { user_id: "u", n: 1 };
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<Probe account={first} />); });
  await act(async () => tree.update(<Probe account={{ user_id: "u", n: 2 }} />));
  expect(seen).toBe(first);
  const other = { user_id: "v", n: 1 };
  await act(async () => tree.update(<Probe account={other} />));
  expect(seen).toBe(other);
});
