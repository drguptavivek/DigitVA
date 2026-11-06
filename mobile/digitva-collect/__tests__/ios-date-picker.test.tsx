/**
 * pickDate on iOS (src/platform.ts -> src/iosDatePicker.ts -> IosDatePickerHost): Done resolves the picked day,
 * Cancel and dismissal resolve undefined, a second request resolves the first with undefined, and Android keeps
 * DateTimePickerAndroid.open.
 */
import React from "react";
import { Platform } from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

const mockAndroidOpen = jest.fn();
jest.mock("@react-native-community/datetimepicker", () => {
  const { createElement } = require("react");
  return {
    __esModule: true,
    default: (props: Record<string, unknown>) => createElement("DateTimePicker", props),
    DateTimePickerAndroid: { open: (...args: unknown[]) => mockAndroidOpen(...args) },
  };
});

import { IosDatePickerHost } from "../src/IosDatePickerHost";
import { finishIosDate, requestIosDate, subscribeIosDate, type DateRequest } from "../src/iosDatePicker";
import { platformServices } from "../src/platform";
import en from "../src/strings/en.json";

const realOs = Platform.OS;
const setOs = (os: string) => Object.defineProperty(Platform, "OS", { value: os, configurable: true });
const pickDate = (value?: string) => platformServices.pickDate!({} as never, {} as never, value);

beforeEach(() => {
  setOs("ios");
  mockAndroidOpen.mockReset();
});
afterAll(() => setOs(realOs));

describe("the request store", () => {
  it("resolves the picked day as ISO on Done and closes the request", async () => {
    const seen: Array<DateRequest | undefined> = [];
    const stop = subscribeIosDate((request) => seen.push(request));
    const answer = requestIosDate("2024-02-29");
    const open = seen.at(-1)!;
    expect(open).toBeDefined();
    expect(open.initial).toEqual(new Date(2024, 1, 29));
    finishIosDate(open.id, new Date(2024, 2, 5));
    await expect(answer).resolves.toBe("2024-03-05");
    expect(seen.at(-1)).toBeUndefined();
    stop();
  });

  it("resolves undefined on Cancel", async () => {
    let open: DateRequest | undefined;
    const stop = subscribeIosDate((request) => { open = request; });
    const answer = requestIosDate(undefined);
    expect(open).toBeDefined();
    finishIosDate(open!.id, undefined);
    await expect(answer).resolves.toBeUndefined();
    stop();
  });

  it("resolves the first request with undefined when a second opens, and ignores the stale id", async () => {
    let open: DateRequest | undefined;
    const stop = subscribeIosDate((request) => { open = request; });
    const first = requestIosDate("2020-01-01");
    const firstId = open!.id;
    const second = requestIosDate("2021-06-15");
    await expect(first).resolves.toBeUndefined();
    expect(open!.id).not.toBe(firstId);
    finishIosDate(firstId, new Date(2000, 0, 1)); // stale: does nothing
    expect(open).toBeDefined();
    finishIosDate(open!.id, new Date(2021, 5, 16));
    await expect(second).resolves.toBe("2021-06-16");
    stop();
  });
});

describe("platformServices.pickDate", () => {
  it("keeps the Android system dialog on Android", async () => {
    setOs("android");
    const answer = pickDate("2023-07-04");
    expect(mockAndroidOpen).toHaveBeenCalledTimes(1);
    const options = mockAndroidOpen.mock.calls[0][0];
    expect(options).toMatchObject({ mode: "date", value: new Date(2023, 6, 4) });
    options.onValueChange({}, new Date(2023, 6, 9));
    await expect(answer).resolves.toBe("2023-07-09");
  });

  it("asks the iOS host instead of DateTimePickerAndroid on iOS", async () => {
    let open: DateRequest | undefined;
    const stop = subscribeIosDate((request) => { open = request; });
    const answer = pickDate("2023-07-04");
    expect(open).toBeDefined();
    expect(mockAndroidOpen).not.toHaveBeenCalled();
    finishIosDate(open!.id, undefined);
    await expect(answer).resolves.toBeUndefined();
    stop();
  });
});

describe("IosDatePickerHost", () => {
  let tree: ReactTestRenderer;
  afterEach(() => act(() => tree.unmount()));
  const button = (label: string) =>
    tree.root.findAll((node) => node.props.accessibilityLabel === label && typeof node.props.onPress === "function")[0];

  it("renders nothing until a date is asked for", () => {
    act(() => { tree = create(<IosDatePickerHost />); });
    expect(tree.toJSON()).toBeNull();
  });

  it("shows the inline picker and resolves the changed day on Done", async () => {
    act(() => { tree = create(<IosDatePickerHost />); });
    let answer!: Promise<string | undefined>;
    act(() => { answer = pickDate("2022-12-30"); });
    const picker = tree.root.findByProps({ testID: "ios-date-picker" });
    expect(picker.props).toMatchObject({ mode: "date", display: "inline", value: new Date(2022, 11, 30) });
    act(() => picker.props.onChange({ type: "set" }, new Date(2022, 11, 31)));
    expect(button(en.datePickerDone)).toBeDefined();
    act(() => button(en.datePickerDone).props.onPress());
    await expect(answer).resolves.toBe("2022-12-31");
    expect(tree.toJSON()).toBeNull();
  });

  it("resolves undefined on Cancel", async () => {
    act(() => { tree = create(<IosDatePickerHost />); });
    let answer!: Promise<string | undefined>;
    act(() => { answer = pickDate(undefined); });
    expect(button(en.cancel)).toBeDefined();
    act(() => button(en.cancel).props.onPress());
    await expect(answer).resolves.toBeUndefined();
    expect(tree.toJSON()).toBeNull();
  });

  it("stays empty on Android even when asked", () => {
    setOs("android");
    act(() => { tree = create(<IosDatePickerHost />); });
    void pickDate("2022-01-01");
    expect(mockAndroidOpen).toHaveBeenCalledTimes(1);
    expect(tree.toJSON()).toBeNull();
  });
});
