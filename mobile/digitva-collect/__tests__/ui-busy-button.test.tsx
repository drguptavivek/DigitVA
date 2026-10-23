import { ActivityIndicator, Text } from "react-native";
import { act, create } from "react-test-renderer";

jest.mock("react-native-safe-area-context", () => {
  const { View } = jest.requireActual("react-native");
  return { SafeAreaView: View, useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) };
});
import { Button, Screen } from "../src/ui";

const render = async (element: React.ReactElement) => {
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(element); });
  return tree;
};

describe("Button busy mode", () => {
  it("keeps its label and adds an inline spinner instead of swapping to Loading", async () => {
    const idle = await render(<Button label="Refresh" onPress={() => undefined} />);
    const busy = await render(<Button label="Refresh" loading onPress={() => undefined} />);
    expect(idle.root.findAllByType(ActivityIndicator)).toHaveLength(0);
    expect(busy.root.findAllByType(ActivityIndicator)).toHaveLength(1);
    expect(busy.root.findAllByType(Text).map((n) => n.props.children)).toEqual(["Refresh"]);
    // The spinner is absolutely placed, so the button keeps its width.
    expect(busy.root.findByType(ActivityIndicator).props.style.position).toBe("absolute");
  });

  it("is disabled and announces busy while loading", async () => {
    const onPress = jest.fn();
    const busy = await render(<Button label="Send" loading onPress={onPress} />);
    const button = busy.root.findAll((n) => n.props.accessibilityRole === "button" && n.props.accessibilityState)[0];
    expect(button.props.accessibilityState).toMatchObject({ busy: true, disabled: true });
  });
});

describe("Screen immersive variant", () => {
  it("renders only its children: no title bar and no debug banner", async () => {
    const tree = await render(<Screen title="Interview title" variant="immersive"><Text>body</Text></Screen>);
    const texts = tree.root.findAllByType(Text).map((n) => n.props.children);
    expect(texts).toEqual(["body"]);
    expect(tree.root.findAll((n) => n.props.accessibilityRole === "header")).toHaveLength(0);
  });

  it("standard variant still shows the title", async () => {
    const tree = await render(<Screen title="Interview title"><Text>body</Text></Screen>);
    expect(tree.root.findAllByType(Text).map((n) => n.props.children)).toContain("Interview title");
  });
});
