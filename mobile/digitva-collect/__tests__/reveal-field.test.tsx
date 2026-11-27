import React from "react";
import { Modal, View } from "react-native";
import { act, create } from "react-test-renderer";

jest.mock("react-native/Libraries/Utilities/useWindowDimensions", () => ({
  __esModule: true,
  default: () => ({ width: 1024, height: 800, scale: 1, fontScale: 1 }),
}));
jest.mock("../src/i18n", () => ({ t: (key: string) => key }));

import { RevealFieldContext, revealOnWeb, useRevealField } from "../src/ui/revealField";
import { Select } from "../src/ui/Select";
import { spacing } from "../src/theme";

test("Select reveals its field first and anchors the menu in done", async () => {
  const order: string[] = [];
  let finish!: () => void;
  const reveal = jest.fn((_field: unknown, done: () => void) => { order.push("reveal"); finish = done; });
  const measure = jest.fn((cb: (x: number, y: number, w: number, h: number) => void) => { order.push("measure"); cb(10, 20, 200, 40); });
  const proto = (View as unknown as { prototype: Record<string, unknown> }).prototype;
  Object.assign(proto, { measureInWindow: measure });
  let tree: any;
  await act(async () => {
    tree = create(
      <RevealFieldContext.Provider value={reveal}>
        <Select label="Unit" placeholder="Pick" options={[{ value: "a", label: "A" }]} value="" onChange={jest.fn()} searchable />
      </RevealFieldContext.Provider>,
    );
  });
  await act(async () => tree.root.findAll((n: any) => n.props.accessibilityLabel === "Unit" && typeof n.props.onPress === "function")[0].props.onPress());
  expect(reveal).toHaveBeenCalledTimes(1);
  expect(measure).not.toHaveBeenCalled();
  await act(async () => finish());
  expect(order).toEqual(["reveal", "measure"]);
  expect(tree.root.findByType(Modal).props.visible).toBe(true);
  delete proto.measureInWindow;
});

function setup(scrollTo = jest.fn()) {
  const scroll = { measureInWindow: (cb: any) => cb(0, 100, 300, 500), scrollTo };
  let hook!: ReturnType<typeof useRevealField>;
  function Probe() { hook = useRevealField({ current: scroll as any }); return null; }
  act(() => { create(<Probe />); });
  const scrolled = (y: number) => hook.onScroll({ nativeEvent: { contentOffset: { y } } } as any);
  return { hook: () => hook, scrollTo, scrolled };
}
const fieldAt = (y: number) => ({ measureInWindow: (cb: any) => cb(0, y, 200, 40) }) as any;

describe("useRevealField", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    jest.spyOn(global, "requestAnimationFrame").mockImplementation((f: any) => { f(0); return 0; });
  });
  afterEach(() => { jest.useRealTimers(); jest.restoreAllMocks(); });

  test("scrolls the field to the top, then calls done once after the scroll event", () => {
    const { hook, scrollTo, scrolled } = setup();
    scrolled(50);
    const done = jest.fn();
    hook().reveal(fieldAt(400), done);
    expect(scrollTo).toHaveBeenCalledWith({ y: 50 + 300 - spacing.sm, animated: false });
    expect(done).not.toHaveBeenCalled();
    scrolled(342);
    expect(done).toHaveBeenCalledTimes(1);
    scrolled(342);
    jest.advanceTimersByTime(500);
    expect(done).toHaveBeenCalledTimes(1);
  });

  test("falls back to a timer when no scroll event comes", () => {
    const { hook } = setup();
    const done = jest.fn();
    hook().reveal(fieldAt(400), done);
    jest.advanceTimersByTime(149);
    expect(done).not.toHaveBeenCalled();
    jest.advanceTimersByTime(2);
    expect(done).toHaveBeenCalledTimes(1);
  });

  test("clamps at zero and to the scrollable range", () => {
    const { hook, scrollTo } = setup();
    hook().reveal(fieldAt(100), jest.fn());
    expect(scrollTo).toHaveBeenLastCalledWith({ y: 0, animated: false });
    act(() => {
      hook().onLayout({ nativeEvent: { layout: { height: 500 } } } as any);
      hook().onContentSizeChange(0, 900);
    });
    hook().reveal(fieldAt(1000), jest.fn());
    expect(scrollTo).toHaveBeenLastCalledWith({ y: 400, animated: false });
  });

  test("reset forgets the offset of a remounted ScrollView", () => {
    const { hook, scrollTo, scrolled } = setup();
    scrolled(600);
    hook().reset();
    hook().reveal(fieldAt(400), jest.fn());
    expect(scrollTo).toHaveBeenLastCalledWith({ y: 300 - spacing.sm, animated: false });
  });

  test("done runs at once without layout", () => {
    const { hook } = setup();
    const done = jest.fn();
    hook().reveal({} as any, done);
    expect(done).toHaveBeenCalledTimes(1);
  });
});

test("revealOnWeb scrolls the DOM node into view, then calls done", () => {
  jest.spyOn(global, "requestAnimationFrame").mockImplementation((f: any) => { f(0); return 0; });
  const scrollIntoView = jest.fn();
  const done = jest.fn();
  revealOnWeb({ scrollIntoView } as any, done);
  expect(scrollIntoView).toHaveBeenCalledWith({ block: "start" });
  expect(done).toHaveBeenCalledTimes(1);
  jest.restoreAllMocks();
});

test("Select without a provider never calls scrollIntoView", async () => {
  const scrollIntoView = jest.fn();
  const proto = (View as unknown as { prototype: Record<string, unknown> }).prototype;
  Object.assign(proto, { scrollIntoView });
  let tree: any;
  await act(async () => { tree = create(<Select label="Unit" placeholder="Pick" options={[]} value="" onChange={jest.fn()} />); });
  await act(async () => tree.root.findAll((n: any) => n.props.accessibilityLabel === "Unit" && typeof n.props.onPress === "function")[0].props.onPress());
  delete proto.scrollIntoView;
  expect(scrollIntoView).not.toHaveBeenCalled();
});
