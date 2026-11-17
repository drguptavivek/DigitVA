import React from "react";
import { act, create } from "react-test-renderer";
import { Dimensions, Text } from "react-native";

import { WorkspaceLayout } from "../src/workspace/WorkspaceLayout";

const categories = ["one", "two", "three"].map((code) => ({ code, label: code, nav_label: code, render_mode: "table_sections" })) as never[];

async function render(selectedCode: string, extra: { nextBlockedReason?: string; notes?: React.ReactNode } = {}) {
  Dimensions.set({ window: { width: 402, height: 900, scale: 1, fontScale: 1 } });
  const onSelectCategory = jest.fn();
  let tree!: ReturnType<typeof create>;
  await act(async () => {
    tree = create(<WorkspaceLayout identity={{} as never} workspace={{ case: { instance_name: "form-1" } } as never} categories={categories}
      selectedCode={selectedCode} categoryLoading={false} onSelectCategory={onSelectCategory} onExit={() => undefined} {...extra}><Text>content</Text></WorkspaceLayout>);
  });
  const button = (label: string) => tree.root.findAll((n) => n.props.accessibilityRole === "button" && n.props.onPress && n.findAll((c) => c.children?.includes(label)).length > 0).pop();
  return { tree, onSelectCategory, button };
}

test("Previous and Next move between categories; ends are disabled", async () => {
  const mid = await render("two");
  await act(async () => { mid.button("Next")!.props.onPress(); });
  expect(mid.onSelectCategory).toHaveBeenLastCalledWith("three");
  await act(async () => { mid.button("Previous")!.props.onPress(); });
  expect(mid.onSelectCategory).toHaveBeenLastCalledWith("one");
  const first = await render("one");
  expect(first.button("Previous")!.props.accessibilityState?.disabled).toBe(true);
  const last = await render("three");
  expect(last.button("Next")!.props.accessibilityState?.disabled).toBe(true);
});

test("a blocked Next is disabled and shows the reason", async () => {
  const { tree, onSelectCategory, button } = await render("two", { nextBlockedReason: "Complete the Narrative Quality Assessment before proceeding." });
  expect(JSON.stringify(tree.toJSON())).toContain("Complete the Narrative Quality Assessment before proceeding.");
  await act(async () => { button("Next")!.props.onPress?.(); });
  expect(onSelectCategory).not.toHaveBeenCalled();
});

test("Notes button is on every page and reveals the notes", async () => {
  for (const code of ["one", "two", "three"]) {
    const { tree, button } = await render(code, { notes: <Text>note-body</Text> });
    expect(button("Notes")).toBeTruthy();
    await act(async () => { button("Notes")!.props.onPress(); });
    expect(button("Hide Notes")).toBeTruthy();
    expect(tree.root.findAll((n) => n.children?.includes("note-body"))).not.toHaveLength(0);
  }
});
