import { codingReceiptSha256 } from "../src/codingReceipt";

const vectors: Array<{ name: string; value: unknown; sha256: string }> = require("../../../tests/fixtures/offline_coding_receipts.json");

describe("exact coding receipt identity", () => {
  it.each(vectors)("matches shared Python vector $name", ({ value, sha256 }) => {
    expect(codingReceiptSha256(value)).toBe(sha256);
  });

  it("ignores object insertion order and numeric spelling, but preserves missing and array order", () => {
    expect(codingReceiptSha256({ b: 1.0, a: -0 })).toBe(codingReceiptSha256({ a: 0, b: 1 }));
    expect(codingReceiptSha256({})).not.toBe(codingReceiptSha256({ a: null }));
    expect(codingReceiptSha256([1, 2])).not.toBe(codingReceiptSha256([2, 1]));
  });

  it.each([NaN, Infinity, undefined])("rejects non-JSON values %s", (value) => {
    expect(() => codingReceiptSha256({ value })).toThrow();
  });
});
