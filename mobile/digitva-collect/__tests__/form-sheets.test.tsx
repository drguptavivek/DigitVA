import { Modal, ScrollView } from "react-native";
import { act, create } from "react-test-renderer";

jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => ({ top: 24, bottom: 34, left: 0, right: 0 }) }));
import { FormTopBar, Sheet } from "../src/FormTopBar";
import { BottomSheet } from "../src/nativeShell/BottomSheet";

const render = async (element: React.ReactElement) => {
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(element); });
  return tree;
};
const flat = (style: unknown): Record<string, unknown> => Object.assign({}, ...[style].flat(Infinity).filter(Boolean) as object[]);

describe("form bottom sheets above the Android navigation bar", () => {
  it("Sheet pads below its last item by the bottom inset, caps its height and scrolls", async () => {
    const items = Array.from({ length: 12 }, (_, i) => ({ key: `k${i}`, label: `Item ${i}`, onPress: () => undefined }));
    const tree = await render(<Sheet visible title="Menu" items={items} onClose={() => undefined} />);
    const panel = tree.root.findByProps({ testID: "sheet-panel" });
    const style = flat(panel.props.style);
    expect(style.maxHeight).toBe("85%");
    // spacing.lg below the last row, plus the 34dp system bar.
    expect(Number(style.paddingBottom)).toBeGreaterThanOrEqual(34 + 16);
    expect(tree.root.findAllByType(ScrollView).length).toBe(1);
    const modal = tree.root.findByType(Modal);
    expect(modal.props.navigationBarTranslucent).toBe(true);
    expect(modal.props.statusBarTranslucent).toBe(true);
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
