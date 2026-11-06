import { ActivityIndicator, Text } from "react-native";
import { act, create } from "react-test-renderer";

jest.mock("react-native-safe-area-context", () => {
  const { View } = jest.requireActual("react-native");
  return { SafeAreaView: View, useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) };
});
import { ShellContext, type Shell } from "../src/nativeShell/shellContext";
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

describe("Screen title with the phone bar", () => {
  // Only the fields Screen reads; the rest of the shell is irrelevant here.
  const shell = (titleInBar: boolean) => ({ header: true, tabs: false, titleInBar, screenTitle: undefined, publishTitle: jest.fn() }) as unknown as Shell;
  const headers = (tree: ReturnType<typeof create>) => tree.root.findAll((n) => typeof n.type === "string" && n.props.accessibilityRole === "header" && n.props.children === "Settings");
  const action = <Text accessibilityLabel="Add">+</Text>;

  it("keeps the on-page title and its action when the bar shows no title (tab roots, pre-login, web)", async () => {
    const value = shell(false);
    const tree = await render(<ShellContext.Provider value={value}><Screen title="Settings" headerAction={action}><Text>body</Text></Screen></ShellContext.Provider>);
    expect(headers(tree)).toHaveLength(1);
    expect(tree.root.findAll((n) => typeof n.type === "string" && n.props.accessibilityLabel === "Add")).toHaveLength(1);
    expect(value.publishTitle).toHaveBeenCalledWith(expect.any(Object), "Settings");
  });

  it("drops the on-page title when the bar shows it, keeping any header action on the page", async () => {
    const plain = await render(<ShellContext.Provider value={shell(true)}><Screen title="Settings"><Text>body</Text></Screen></ShellContext.Provider>);
    expect(plain.root.findAllByType(Text).map((n) => n.props.children)).toContain("body");
    expect(headers(plain)).toHaveLength(0);
    const withAction = await render(<ShellContext.Provider value={shell(true)}><Screen title="Settings" headerAction={action}><Text>body</Text></Screen></ShellContext.Provider>);
    expect(withAction.root.findAll((n) => typeof n.type === "string" && n.props.accessibilityLabel === "Add")).toHaveLength(1);
    expect(headers(withAction)).toHaveLength(0);
  });

  it("withdraws its title when it unmounts", async () => {
    const value = shell(true);
    const tree = await render(<ShellContext.Provider value={value}><Screen title="Settings"><Text>body</Text></Screen></ShellContext.Provider>);
    const key = (value.publishTitle as jest.Mock).mock.calls[0][0];
    await act(async () => tree.unmount());
    expect(value.publishTitle).toHaveBeenLastCalledWith(key, undefined);
  });
});
