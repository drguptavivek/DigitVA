import { Share, Text } from "react-native";
import { act, create } from "react-test-renderer";

jest.mock("react-native-safe-area-context", () => {
  const { View } = jest.requireActual("react-native");
  return { SafeAreaView: View, useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) };
});
import { DetailsChip } from "../src/ui";

describe("DetailsChip", () => {
  it("shows the raw code and shares it on tap", async () => {
    const share = jest.spyOn(Share, "share").mockResolvedValue({ action: "sharedAction" });
    let tree!: ReturnType<typeof create>;
    await act(async () => { tree = create(<DetailsChip code="load_failed" />); });
    expect(tree.root.findByType(Text).props.children).toBe("details: load_failed");
    await act(async () => { tree.root.findByProps({ accessibilityRole: "button" }).props.onPress(); });
    expect(share).toHaveBeenCalledWith({ message: "load_failed" });
  });

  it("renders nothing without a code", async () => {
    let tree!: ReturnType<typeof create>;
    await act(async () => { tree = create(<DetailsChip code={null} />); });
    expect(tree.toJSON()).toBeNull();
  });
});
