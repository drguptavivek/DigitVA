import { mobileDigitsFromInput, nextMobileDigits, normalizeMobileIdentifier } from "../src/nativeAuthLinks";

describe("native sign-in identifier", () => {
  it("normalizes India mobile pastes to the API identifier", () => {
    expect(mobileDigitsFromInput("+91 987 654 3210")).toBe("9876543210");
    expect(mobileDigitsFromInput("91-9876543210")).toBe("9876543210");
    expect(normalizeMobileIdentifier("+91 987 654 3210")).toBe("+919876543210");
    expect(normalizeMobileIdentifier("987654321")).toBeUndefined();
    expect(normalizeMobileIdentifier("1234567890")).toBeUndefined();
    expect(normalizeMobileIdentifier("98765432101")).toBeUndefined();
  });

  it("holds the country code's 10 digits and refuses anything that would exceed them", () => {
    expect(nextMobileDigits("", "987654321")).toBe("987654321");
    expect(nextMobileDigits("987654321", "9876543210")).toBe("9876543210");
    // An 11th digit is refused; the field keeps its value.
    expect(nextMobileDigits("9876543210", "98765432101")).toBe("9876543210");
    // A paste with the country code still fits.
    expect(nextMobileDigits("", "+91 98765 43210")).toBe("9876543210");
    // A malformed long paste is refused, not cut.
    expect(nextMobileDigits("98", "  9 8 7 6 5 4 3 2 1 0 1 2 3  ")).toBe("98");
  });
});
