import React from "react";
import { act, create } from "react-test-renderer";
import { BackHandler, Dimensions, ScrollView, Text } from "react-native";

import { sectionIcon } from "../src/Icon";
import { WorkspaceLayout } from "../src/workspace/WorkspaceLayout";

const categories = [
  { code: "one", label: "One", nav_label: "One", render_mode: "table_sections", icon_name: "fa-lungs", count: 3, attachment_count: 2 },
  { code: "two", label: "Two", nav_label: "Two Long Section Name", render_mode: "table_sections", icon_name: "fa-nope" },
  { code: "three", label: "Three", nav_label: "Three", render_mode: "table_sections" },
] as never[];

async function render(width: number, selectedCode = "two") {
  act(() => { Dimensions.set({ window: { width, height: 900, scale: 1, fontScale: 1 } }); });
  const onSelectCategory = jest.fn();
  let tree!: ReturnType<typeof create>;
  await act(async () => {
    tree = create(<WorkspaceLayout identity={{} as never} workspace={{ case: { instance_name: "form-1" } } as never} categories={categories}
      selectedCode={selectedCode} categoryLoading={false} onSelectCategory={onSelectCategory} onExit={() => undefined}><Text>content</Text></WorkspaceLayout>);
  });
  const button = (label: string) => tree.root.findAll((n) => n.props.accessibilityLabel === label && typeof n.props.onPress === "function")[0];
  const press = async (label: string) => { await act(async () => { button(label).props.onPress(); }); };
  return { tree, onSelectCategory, button, press };
}

test("phone: one rail button per section, labelled with counts, selected marked, no horizontal tab strip", async () => {
  const { tree, button } = await render(402);
  expect(tree.root.findAll((n) => n.type === ScrollView && n.props.horizontal)).toHaveLength(0);
  expect(button("One, 3 responses, 2 attachments").props.accessibilityState).toEqual({ selected: false });
  expect(button("Two Long Section Name").props.accessibilityState).toEqual({ selected: true });
  expect(button("Three")).toBeTruthy();
  expect(button("Show section names").props.accessibilityState).toEqual({ expanded: false });
});

test("phone: pressing a section selects it", async () => {
  const { onSelectCategory, press } = await render(402);
  await press("Three");
  expect(onSelectCategory).toHaveBeenCalledWith("three");
});

test("phone: the expand button lists every name; choosing one selects it and collapses", async () => {
  const { tree, press, onSelectCategory, button } = await render(402);
  const text = () => JSON.stringify(tree.toJSON());
  expect(text()).not.toContain("Two Long Section Name\"]");
  await press("Show section names");
  expect(text()).toContain("Two Long Section Name");
  expect(button("Hide section names").props.accessibilityState).toEqual({ expanded: true });
  await press("Three");
  expect(onSelectCategory).toHaveBeenCalledWith("three");
  expect(button("Show section names")).toBeTruthy();
});

test("phone: the scrim and Android back collapse the panel", async () => {
  let back: (() => boolean) | undefined;
  const spy = jest.spyOn(BackHandler, "addEventListener").mockImplementation(((_: string, handler: () => boolean) => { back = handler; return { remove: jest.fn() }; }) as never);
  const { tree, press, button } = await render(402);
  await press("Show section names");
  await act(async () => { tree.root.findByProps({ testID: "section-rail-scrim" }).props.onPress(); });
  expect(button("Show section names")).toBeTruthy();
  await press("Show section names");
  await act(async () => { expect(back!()).toBe(true); });
  expect(button("Show section names")).toBeTruthy();
  spy.mockRestore();
});

test("phone: the rail floats over the page and does not narrow it", async () => {
  const { tree } = await render(402);
  const rail = tree.root.findAll((n) => n.props.accessibilityLabel === "Case categories")[0];
  expect(rail.props.style.flat?.() ?? rail.props.style).toBeTruthy();
  const content = tree.root.findAll((n) => n.type === Text && n.props.children === "content")[0];
  let node = content.parent;
  while (node) {
    const pad = StyleOf(node.props.style);
    expect(pad.paddingLeft ?? 0).toBeLessThan(56);
    expect(pad.marginLeft ?? 0).toBeLessThan(56);
    node = node.parent;
  }
  const flat = StyleOf(rail.props.style);
  expect(flat.position).toBe("absolute");
});

function StyleOf(style: unknown): Record<string, number | string> {
  return Object.assign({}, ...(Array.isArray(style) ? style.flat(3) : [style]).filter(Boolean));
}

test("unknown or missing icon names fall back to the folder", () => {
  expect(sectionIcon("fa-nope")).toEqual(sectionIcon(null));
  expect(sectionIcon(undefined).android).toBe("folder_open");
  expect(sectionIcon("fa-lungs").android).toBe("pulmonology");
});

test("tablet: categories stay a vertical sidebar and no rail floats", async () => {
  const { tree } = await render(1024);
  const strips = tree.root.findAll((n) => n.type === ScrollView && n.props.accessibilityLabel === "Case categories");
  expect(strips).toHaveLength(1);
  expect(strips[0].props.horizontal).toBeFalsy();
});
