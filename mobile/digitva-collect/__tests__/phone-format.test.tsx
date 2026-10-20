import React from "react";
import { act, create } from "react-test-renderer";

jest.mock("../src/i18n", () => ({ t: (key: string) => key }));
jest.mock("../src/ui", () => ({
  Button: ({ label, onPress }: { label: string; onPress: () => void }) => <button data-label={label} onClick={onPress} />,
  useUiStyles: () => ({ error: {}, input: {}, fieldLabel: {} })
}));

import { PhoneNumbers } from "../src/PhoneInput";
import { formatPhone, normalisePhone, PHONE_PLACEHOLDER, phoneDigits, phoneDisplay } from "../src/phoneFormat";
import { cleanRegistration, validateRegistration } from "../src/cases";

describe("phone format", () => {
  it("accepts exactly 10 digits, any first digit, with or without separators", () => {
    expect(normalisePhone("9876543210")).toBe("9876543210");
    expect(normalisePhone("987 654 3210")).toBe("9876543210");
    expect(normalisePhone("0123456789")).toBe("0123456789");
    expect(normalisePhone("5123456789")).toBe("5123456789");
  });

  it("rejects anything that is not 10 digits", () => {
    for (const bad of ["987654321", "98765432101", "98765 4321a", "+929876543210", "phone me", "123"]) {
      expect(normalisePhone(bad)).toBeNull();
    }
    expect(validateRegistration({ deceased_name: "A", deceased_sex: "male", date_of_death: "2026-09-29", informant_phone: "12345" }, "2026-10-20")).toMatchObject({
      informant_phone: "errPhone"
    });
  });

  it("allows empty numbers, both optional", () => {
    expect(validateRegistration({ deceased_name: "A", deceased_sex: "male", date_of_death: "2026-09-29", informant_phone: "", informant_phone_2: "" }, "2026-10-20")).toEqual({});
  });

  it("formats as typed in groups 3-3-4 and keeps only digits", () => {
    let typed = "";
    const seen: string[] = [];
    for (const key of "9876543210") {
      typed = phoneDigits(phoneDisplay(typed) + key, typed);
      seen.push(phoneDisplay(typed));
    }
    expect(seen).toEqual(["9", "98", "987", "987 6", "987 65", "987 654", "987 654 3", "987 654 32", "987 654 321", "987 654 3210"]);
    expect(phoneDigits("987-654 (3210)x")).toBe("9876543210");
    expect(phoneDigits("987 654 32101", "9876543210")).toBe("9876543210");
    expect(formatPhone("")).toBe("");
    expect(PHONE_PLACEHOLDER).toBe("___ ___ ____");
  });

  it("drops +91, 91 or 0 on paste but never from typed digits", () => {
    expect(phoneDigits("+91 98765 43210")).toBe("9876543210");
    expect(phoneDigits("919876543210")).toBe("9876543210");
    expect(phoneDigits("09876543210")).toBe("9876543210");
    expect(phoneDigits("91234 56789")).toBe("9123456789");
    // an 11th typed digit on a number starting 0 is cut off, not read as a prefix
    expect(phoneDigits("0123456789" + "5", "0123456789")).toBe("0123456789");
  });

  it("shows an older stored value that is not plain digits as it is, and sends plain digits", () => {
    expect(phoneDisplay("+91 98765-43210")).toBe("+91 98765-43210");
    expect(cleanRegistration({ deceased_name: " A ", informant_phone: "+91 98765-43210", informant_phone_2: " 987 654 3210 " } as never)).toEqual({
      deceased_name: "A",
      informant_phone: "9876543210",
      informant_phone_2: "9876543210"
    });
  });
});

describe("PhoneNumbers", () => {
  function render(values: { informant_phone: string; informant_phone_2: string }, onChange = jest.fn(), onValidity = jest.fn(), errors = {}) {
    let tree!: ReturnType<typeof create>;
    act(() => {
      tree = create(<PhoneNumbers values={values} errors={errors} onChange={onChange} onValidity={onValidity} />);
    });
    return { tree, onChange, onValidity };
  }

  it("shows one grouped input with the placeholder, and reveals a second on request", () => {
    const { tree, onChange, onValidity } = render({ informant_phone: "9876543", informant_phone_2: "" });
    const inputs = () => tree.root.findAllByType("TextInput" as never);
    expect(inputs()).toHaveLength(1);
    expect(inputs()[0].props).toMatchObject({ value: "987 654 3", placeholder: "___ ___ ____", inputMode: "tel" });
    act(() => inputs()[0].props.onChangeText("987 654 32-10"));
    expect(onChange).toHaveBeenCalledWith("informant_phone", "9876543210");
    act(() => inputs()[0].props.onBlur());
    expect(onValidity).toHaveBeenCalledWith("informant_phone", false);
    act(() => tree.root.findByProps({ "data-label": "addAnotherNumber" }).props.onClick());
    expect(inputs()).toHaveLength(2);
  });

  it("shows the second input when it already has a value and reports a valid blur", () => {
    const { tree, onValidity } = render({ informant_phone: "", informant_phone_2: "9876543210" }, jest.fn(), jest.fn(), { informant_phone_2: "errPhone" });
    const inputs = tree.root.findAllByType("TextInput" as never);
    expect(inputs).toHaveLength(2);
    expect(inputs[1].props.value).toBe("987 654 3210");
    expect(tree.root.findAllByProps({ accessibilityRole: "alert" }).length).toBeGreaterThan(0);
    act(() => inputs[1].props.onBlur());
    expect(onValidity).toHaveBeenCalledWith("informant_phone_2", true);
    act(() => inputs[0].props.onBlur());
    expect(onValidity).toHaveBeenCalledWith("informant_phone", true);
  });
});
