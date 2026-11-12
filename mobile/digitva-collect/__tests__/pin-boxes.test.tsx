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
  it("development builds take a fast-typed or whole PIN in the pin-input field", async () => {
    let tree!: ReactTestRenderer;
    await act(async () => {
      tree = create(<Harness />);
    });
    const fast = () => tree.root.findAll((node) => node.props.testID === "pin-input" && typeof node.props.onChangeText === "function")[0];
    for (const digit of "1234") act(() => fast().props.onChangeText(digit));
    expect(boxes(tree).map((box) => box.props.value).join("")).toBe("1234");
    act(() => fast().props.onChangeText("987654"));
    expect(boxes(tree).map((box) => box.props.value).join("")).toBe("987654");
  });

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

/** Set PIN's two rows: each row keeps its own digits, and Confirm takes focus only once the PIN row is full. */
describe("PIN and Confirm rows", () => {
  function TwoRows() {
    const [pin, setPin] = useState("");
    const [confirm, setConfirm] = useState("");
    const [focusConfirm, setFocusConfirm] = useState(0);
    return (
      <>
        <PinBoxes value={pin} onChange={setPin} label="PIN" onFilled={() => setFocusConfirm((n) => n + 1)} />
        <PinBoxes value={confirm} onChange={setConfirm} label="Confirm" autoFocus={false} focusSignal={focusConfirm} />
      </>
    );
  }
  const rowBoxes = (tree: ReactTestRenderer, label: string) =>
    boxes(tree).filter((box) => String(box.props.accessibilityLabel).startsWith(`${label} `));
  const digits = (tree: ReactTestRenderer, label: string) => rowBoxes(tree, label).map((box) => box.props.value).join("");

  async function mount() {
    const focused: string[] = [];
    let tree!: ReactTestRenderer;
    await act(async () => {
      tree = create(<TwoRows />);
    });
    // Each box's ref is the TextInput instance: record which box is asked to take focus.
    for (const node of tree.root.findAll((n) => typeof n.type !== "string" && String(n.props.testID ?? "").startsWith("pin-box-") && n.instance)) {
      node.instance.focus = () => focused.push(String(node.props.accessibilityLabel));
    }
    return { tree, focused };
  }

  it("keeps digits typed faster than a re-render in their own boxes", async () => {
    const { tree } = await mount();
    // Both keystrokes land before React re-renders, so the second box still sees the old (empty) value prop.
    act(() => {
      rowBoxes(tree, "PIN")[0].props.onChangeText("1");
      rowBoxes(tree, "PIN")[1].props.onChangeText("2");
    });
    expect(digits(tree, "PIN")).toBe("12");
    expect(digits(tree, "Confirm")).toBe("");
  });

  it("moves focus to Confirm only when the PIN row is full", async () => {
    const { tree, focused } = await mount();
    for (const [index, digit] of ["1", "2", "3", "4", "5"].entries()) act(() => rowBoxes(tree, "PIN")[index].props.onChangeText(digit));
    expect(focused.some((label) => label.startsWith("Confirm"))).toBe(false);
    await act(async () => rowBoxes(tree, "PIN")[5].props.onChangeText("6"));
    expect(digits(tree, "PIN")).toBe("123456");
    expect(focused.at(-1)).toBe("Confirm 1 / 6");
    act(() => rowBoxes(tree, "Confirm")[0].props.onChangeText("9"));
    expect(digits(tree, "Confirm")).toBe("9");
    expect(digits(tree, "PIN")).toBe("123456");
  });

  it("does not jump to Confirm again when a digit of the full PIN row is replaced", async () => {
    const { tree, focused } = await mount();
    await act(async () => rowBoxes(tree, "PIN")[0].props.onChangeText("123456"));
    const jumps = () => focused.filter((label) => label.startsWith("Confirm")).length;
    expect(jumps()).toBe(1);
    await act(async () => rowBoxes(tree, "PIN")[2].props.onChangeText("38"));
    expect(digits(tree, "PIN")).toBe("128456");
    expect(jumps()).toBe(1);
  });

  it("puts the show/hide eye in the same row as the boxes", async () => {
    const { tree } = await mount();
    const toggle = tree.root.findAll((node) => node.props.accessibilityLabel === "pinShow" && typeof node.props.onPress === "function")[0];
    expect(toggle).toBeDefined();
    const row = toggle.parent!;
    expect(row.findAll((node) => String(node.props.testID ?? "").startsWith("pin-box-") && typeof node.type === "string")).toHaveLength(6);
    expect(row.props.style).toMatchObject({ flexDirection: "row" });
  });
});
