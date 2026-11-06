import { Modal, ScrollView } from "react-native";
import { act, create } from "react-test-renderer";

jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => ({ top: 24, bottom: 34, left: 0, right: 0 }) }));
import { FormTopBar, Sheet } from "../src/FormTopBar";
import { BottomSheet, SheetRow } from "../src/nativeShell/BottomSheet";
import { CheckMark } from "../src/ui/controls";

const render = async (element: React.ReactElement) => {
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(element); });
  return tree;
};

describe("form bottom sheets above the Android navigation bar", () => {
  it("Sheet is the app's BottomSheet: handle, title, edge-to-edge layout and one scrolling list", async () => {
    const items = Array.from({ length: 12 }, (_, i) => ({ key: `k${i}`, label: `Item ${i}`, onPress: () => undefined }));
    const tree = await render(<Sheet visible title="Menu" items={items} onClose={() => undefined} />);
    expect(tree.root.findAllByType(BottomSheet)).toHaveLength(1);
    expect(tree.root.findByProps({ testID: "sheet-title" }).props.children).toBe("Menu");
    expect(tree.root.findAllByType(ScrollView).length).toBe(1);
    const modal = tree.root.findByType(Modal);
    expect(modal.props.navigationBarTranslucent).toBe(true);
    expect(modal.props.statusBarTranslucent).toBe(true);
  });

  it("renders actions as SheetRows and a choice list with the current item checked; choosing closes first", async () => {
    const calls: string[] = [];
    const onClose = () => calls.push("close");
    const actions = await render(
      <Sheet visible title="Interview" onClose={onClose} items={[{ key: "a", label: "Delete draft", onPress: () => calls.push("a") }]} />,
    );
    const rows = actions.root.findAllByType(SheetRow);
    expect(rows).toHaveLength(1);
    await act(async () => rows[0].props.onPress());
    expect(calls).toEqual(["close", "a"]);

    const choices = await render(
      <Sheet
        visible
        title="Questionnaire language"
        onClose={() => undefined}
        items={[
          { key: "en", label: "English", selected: true, onPress: () => undefined },
          { key: "hi", label: "Hindi", selected: false, onPress: () => undefined },
        ]}
      />,
    );
    expect(choices.root.findAllByType(SheetRow)).toHaveLength(0);
    const english = choices.root.findAll((n) => n.props.accessibilityRole === "menuitem" && n.props.accessibilityLabel === "English")[0];
    expect(english.props.accessibilityState.selected).toBe(true);
    expect(english.findAllByType(CheckMark)).toHaveLength(1);
    const hindi = choices.root.findAll((n) => n.props.accessibilityRole === "menuitem" && n.props.accessibilityLabel === "Hindi")[0];
    expect(hindi.findAllByType(CheckMark)).toHaveLength(0);
  });

  it("BottomSheet (account, help, sync, pickers) is laid out for edge-to-edge too", async () => {
    const tree = await render(<BottomSheet visible title="Help" onClose={() => undefined}><></></BottomSheet>);
    expect(tree.root.findByType(Modal).props.navigationBarTranslucent).toBe(true);
    expect(tree.root.findAllByType(ScrollView).length).toBe(1);
  });
});

describe("FormTopBar", () => {
  it("shows a small label above the title and the problems chip with its count", async () => {
    const onProblems = jest.fn();
    const tree = await render(
      <FormTopBar title="Asha Devi" label="Revision" saveState="saved" onBack={() => undefined} menuItems={[]} problemCount={3} onProblems={onProblems} />,
    );
    const texts = tree.root.findAll((n) => typeof n.type === "string" && typeof n.props.children === "string").map((n) => n.props.children);
    expect(texts).toEqual(expect.arrayContaining(["Revision", "Asha Devi"]));
    const chip = tree.root.findAll((n) => n.props.testID === "problems-chip" && typeof n.props.onPress === "function")[0];
    await act(async () => chip.props.onPress());
    expect(onProblems).toHaveBeenCalledTimes(1);
  });

  it("has no chip without problems", async () => {
    const tree = await render(<FormTopBar title="x" saveState="saved" onBack={() => undefined} menuItems={[]} />);
    expect(tree.root.findAll((n) => n.props.testID === "problems-chip")).toHaveLength(0);
  });
});
