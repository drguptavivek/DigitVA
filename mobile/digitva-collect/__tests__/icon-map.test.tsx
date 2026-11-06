/** src/Icon.tsx: one meaning per icon, an SF Symbol on iOS and the Material Symbol on Android and the web. */
import { act, create } from "react-test-renderer";

import { Icon, icons } from "../src/Icon";

async function symbolProps(element: React.ReactElement) {
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(element); });
  return tree.root.findAll((n) => typeof n.type === "string" && n.props.testID === "symbol")[0].props;
}

test("the shell icons pair the SF Symbol and Material Symbol of the same meaning", () => {
  expect(icons.home).toEqual({ ios: "house", android: "home" });
  expect(icons.interviews).toEqual({ ios: "list.bullet.rectangle", android: "list_alt" });
  expect(icons.register).toEqual({ ios: "plus.circle", android: "add_circle" });
  expect(icons.sync).toEqual({ ios: "arrow.triangle.2.circlepath", android: "sync" });
  expect(icons.back).toEqual({ ios: "chevron.left", android: "arrow_back_ios_new" });
  expect(icons.help).toEqual({ ios: "questionmark.circle", android: "help" });
  expect(icons.language).toEqual({ ios: "translate", android: "translate" }); // the 文A glyph: language, not a globe
});

test("Icon hands expo-symbols the iOS name and the Material name for Android and the web", async () => {
  const props = await symbolProps(<Icon name={icons.sync} color="#1f4d60" size={24} />);
  expect(props.name).toEqual({ ios: "arrow.triangle.2.circlepath", android: "sync", web: "sync" });
  expect(props.tintColor).toBe("#1f4d60");
});

test("an icon without a label is hidden from screen readers; with one it is announced", async () => {
  const hidden = await symbolProps(<Icon name={icons.help} color="#000000" />);
  expect(hidden.accessible).toBe(false);
  expect(hidden.importantForAccessibility).toBe("no-hide-descendants");
  const labelled = await symbolProps(<Icon name={icons.help} color="#000000" accessibilityLabel="Help" />);
  expect(labelled.accessible).toBe(true);
  expect(labelled.accessibilityLabel).toBe("Help");
});
