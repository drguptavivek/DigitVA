/** The six PIN boxes: typing, auto-advance, backspace, paste, masking, shake. */
import React, { useState } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

jest.mock("../src/i18n", () => ({ t: (key: string) => key }));
jest.mock("../src/ui", () => ({ useUiStyles: () => ({ input: {}, muted: {} }) }));

import { applyPinInput, backspaceFromEmpty, PinBoxes } from "../src/PinBoxes";

describe("applyPinInput", () => {
  it("fills left to right and moves to the next box", () => {
    expect(applyPinInput("", 0, "1")).toEqual({ value: "1", focus: 1 });
    expect(applyPinInput("12", 2, "3")).toEqual({ value: "123", focus: 3 });
    expect(applyPinInput("12345", 5, "6")).toEqual({ value: "123456", focus: 5 });
  });

  it("never leaves a gap when a later box is typed into", () => {
    expect(applyPinInput("12", 5, "9")).toEqual({ value: "129", focus: 3 });
  });

  it("replaces a digit typed over a filled box (old and new digit arrive together)", () => {
    expect(applyPinInput("123", 1, "27")).toEqual({ value: "173", focus: 2 });
    expect(applyPinInput("123", 1, "72")).toEqual({ value: "173", focus: 2 });
  });

  it("fills every box from a pasted PIN, ignoring non-digits and extra digits", () => {
    expect(applyPinInput("", 0, "123456")).toEqual({ value: "123456", focus: 5 });
    expect(applyPinInput("9", 3, "12 34-56")).toEqual({ value: "123456", focus: 5 });
    expect(applyPinInput("", 0, "12345678").value).toBe("123456");
  });

  it("ignores letters", () => {
    expect(applyPinInput("12", 2, "a").value).toBe("12");
  });

  it("deleting a digit closes the gap and stays on that box", () => {
    expect(applyPinInput("123", 1, "")).toEqual({ value: "13", focus: 1 });
  });

  it("backspace on an empty box drops the last digit and steps back", () => {
    expect(backspaceFromEmpty("123")).toEqual({ value: "12", focus: 2 });
    expect(backspaceFromEmpty("1")).toEqual({ value: "", focus: 0 });
  });
});

function Harness({ shakeSignal }: { shakeSignal?: number }) {
  const [value, setValue] = useState("");
  return <PinBoxes value={value} onChange={setValue} label="PIN" shakeSignal={shakeSignal} />;
}

const boxes = (tree: ReactTestRenderer) =>
  tree.root.findAll(
    (node) => typeof node.props.onChangeText === "function" && String(node.props.testID).startsWith("pin-box-") && node.parent?.props.testID !== node.props.testID
  );

describe("PinBoxes", () => {
  it("renders six masked numeric boxes, the first focused at once", async () => {
    let tree!: ReactTestRenderer;
    await act(async () => {
      tree = create(<Harness />);
    });
    const all = boxes(tree);
    expect(all).toHaveLength(6);
    expect(all.every((box) => box.props.secureTextEntry === true && box.props.keyboardType === "number-pad")).toBe(true);
    expect(all[0].props.autoFocus).toBe(true);
    expect(all.slice(1).some((box) => box.props.autoFocus)).toBe(false);
  });

  it("types digits across the boxes and a paste fills all of them", async () => {
    let tree!: ReactTestRenderer;
    await act(async () => {
      tree = create(<Harness />);
    });
    act(() => boxes(tree)[0].props.onChangeText("4"));
    act(() => boxes(tree)[1].props.onChangeText("2"));
    expect(boxes(tree).map((box) => box.props.value).join("")).toBe("42");
    act(() => boxes(tree)[0].props.onChangeText("135790"));
    expect(boxes(tree).map((box) => box.props.value)).toEqual(["1", "3", "5", "7", "9", "0"]);
  });

  it("backspace on an empty box clears the previous one", async () => {
    let tree!: ReactTestRenderer;
    await act(async () => {
      tree = create(<Harness />);
    });
    act(() => boxes(tree)[0].props.onChangeText("123"));
    act(() => boxes(tree)[3].props.onKeyPress({ nativeEvent: { key: "Backspace" } }));
    expect(boxes(tree).map((box) => box.props.value).join("")).toBe("12");
  });

  it("shows and hides the digits with the toggle", async () => {
    let tree!: ReactTestRenderer;
    await act(async () => {
      tree = create(<Harness />);
    });
    const toggle = () => tree.root.findAll((node) => node.props.accessibilityRole === "button" && typeof node.props.onPress === "function")[0];
    expect(JSON.stringify(tree.toJSON())).toContain("pinShow");
    act(() => toggle().props.onPress());
    expect(boxes(tree).every((box) => box.props.secureTextEntry === false)).toBe(true);
    expect(JSON.stringify(tree.toJSON())).toContain("pinHide");
  });

  it("runs the shake when the signal changes and keeps rendering", async () => {
    const start = jest.spyOn(require("react-native").Animated, "sequence");
    let tree!: ReactTestRenderer;
    await act(async () => {
      tree = create(<Harness shakeSignal={0} />);
    });
    expect(start).not.toHaveBeenCalled();
    await act(async () => {
      tree.update(<Harness shakeSignal={1} />);
    });
    expect(start).toHaveBeenCalledTimes(1);
    expect(boxes(tree)).toHaveLength(6);
    start.mockRestore();
  });
});

describe("PIN inputs stay out of the autofill service (digitva-jish)", () => {
  it("every box opts out of autofill", () => {
    const { create } = require("react-test-renderer");
    const { PinBoxes: Boxes } = require("../src/PinBoxes");
    let tree: any;
    require("react-test-renderer").act(() => { tree = create(<Boxes value="" onChange={() => undefined} label="PIN" />); });
    const boxes = tree.root.findAll((n: any) => /^pin-box-/.test(n.props.testID ?? "") && typeof n.type === "string");
    expect(boxes.length).toBeGreaterThan(0);
    for (const box of boxes) {
      expect(box.props.importantForAutofill).toBe("no");
      expect(box.props.autoComplete).toBe("off");
    }
  });
});
