import React, { act } from "react";
import { create, type ReactTestRenderer } from "react-test-renderer";

import { ConfirmDialog } from "../src/ConfirmDialog";
import { setUiLocale } from "../src/i18n";
import { useWhoNoConfirm } from "../src/useWhoNoConfirm";

beforeEach(() => setUiLocale("en"));

function setup() {
  const calls = { confirmed: 0, reverted: 0 };
  const session = { data: { Id10013: "no", age: 5 } as Record<string, unknown>, replaceData: jest.fn() };
  let hook!: ReturnType<typeof useWhoNoConfirm>;
  function Probe() {
    hook = useWhoNoConfirm({ onConfirmed: () => { calls.confirmed += 1; }, onReverted: () => { calls.reverted += 1; } });
    return hook.dialog;
  }
  let tree!: ReactTestRenderer;
  act(() => { tree = create(<Probe />); });
  const live = { getSnapshot: () => ({ data: session.data }), replaceData: session.replaceData };
  act(() => hook.onReady({ getSnapshot: () => ({ data: { Id10013: "yes", age: 5 } }), replaceData: live.replaceData } as never));
  return { calls, session, tree, get hook() { return hook; }, live };
}

it("lets a non-No change through without asking", () => {
  const s = setup();
  let ok!: boolean;
  act(() => { ok = s.hook.onChange({ Id10013: "yes" } as never); });
  expect(ok).toBe(true);
  expect(s.tree.root.findAllByType(ConfirmDialog)).toHaveLength(0);
});

it("asks on No and does nothing until answered; confirm runs the refusal path", () => {
  const s = setup();
  act(() => { expect(s.hook.onChange({ Id10013: "no" } as never)).toBe(false); });
  expect(s.tree.root.findAllByType(ConfirmDialog)).toHaveLength(1);
  expect(s.calls).toEqual({ confirmed: 0, reverted: 0 });
  act(() => s.tree.root.findByType(ConfirmDialog).props.onConfirm());
  expect(s.calls).toEqual({ confirmed: 1, reverted: 0 });
  expect(s.live.replaceData).not.toHaveBeenCalled();
  expect(s.tree.root.findAllByType(ConfirmDialog)).toHaveLength(0);
});

it("cancel puts the previous answers back and keeps the draft", () => {
  const s = setup();
  act(() => { s.hook.onChange({ Id10013: "yes", age: 5 } as never); });
  act(() => { s.hook.onChange({ Id10013: "no", age: 5 } as never); });
  act(() => s.tree.root.findByType(ConfirmDialog).props.onCancel());
  expect(s.calls).toEqual({ confirmed: 0, reverted: 1 });
  expect(s.live.replaceData).toHaveBeenCalledWith({ Id10013: "yes", age: 5 });
  expect(s.tree.root.findAllByType(ConfirmDialog)).toHaveLength(0);
});
