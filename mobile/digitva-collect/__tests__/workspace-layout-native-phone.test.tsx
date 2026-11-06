import React from "react";
import { act, create } from "react-test-renderer";
import { Dimensions, ScrollView, Text } from "react-native";

import { WorkspaceLayout } from "../src/workspace/WorkspaceLayout";

const categories = [
  { code: "one", label: "One", nav_label: "One", render_mode: "table_sections" },
  { code: "two", label: "Two", nav_label: "Two", render_mode: "table_sections" },
] as never[];

async function render(width: number) {
  Dimensions.set({ window: { width, height: 900, scale: 1, fontScale: 1 } });
  let tree!: ReturnType<typeof create>;
  await act(async () => {
    tree = create(<WorkspaceLayout identity={{} as never} workspace={{ case: { instance_name: "form-1" } } as never} categories={categories}
      selectedCode="two" categoryLoading={false} onSelectCategory={() => undefined} onExit={() => undefined}><Text>content</Text></WorkspaceLayout>);
  });
  return tree.root.findAll((n) => n.type === ScrollView && n.props.accessibilityLabel === "Case categories");
}

test("phone: categories are one horizontal strip, not a row sidebar", async () => {
  const strips = await render(402);
  expect(strips).toHaveLength(1);
  expect(strips[0].props.horizontal).toBe(true);
  expect(strips[0].findAll((n) => n.props.accessibilityState?.selected === true)).not.toHaveLength(0);
});

test("tablet: categories stay a vertical sidebar", async () => {
  const strips = await render(1024);
  expect(strips).toHaveLength(1);
  expect(strips[0].props.horizontal).toBeFalsy();
});
