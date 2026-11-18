// iOS Safari 15.0-15.3 lacks `.at()` and `Object.hasOwn`; src/polyfills.ts supplies them.
test("polyfills .at() and Object.hasOwn where missing, with the native semantics", () => {
  const saved = { array: Array.prototype.at, string: String.prototype.at, hasOwn: Object.hasOwn };
  try {
    delete (Array.prototype as { at?: unknown }).at;
    delete (String.prototype as { at?: unknown }).at;
    delete (Object as { hasOwn?: unknown }).hasOwn;
    jest.isolateModules(() => require("../src/polyfills"));
    expect([1, 2, 3].at(-1)).toBe(3);
    expect([1, 2, 3].at(0)).toBe(1);
    expect([1, 2, 3].at(3)).toBeUndefined();
    expect([1, 2, 3].at(-4)).toBeUndefined();
    expect("a/b".split("/").at(-1)).toBe("b");
    expect("abc".at(-1)).toBe("c");
    expect(Object.hasOwn({ a: 1 }, "a")).toBe(true);
    expect(Object.hasOwn({ a: 1 }, "toString")).toBe(false);
  } finally {
    Object.defineProperty(Array.prototype, "at", { value: saved.array, writable: true, configurable: true });
    Object.defineProperty(String.prototype, "at", { value: saved.string, writable: true, configurable: true });
    Object.defineProperty(Object, "hasOwn", { value: saved.hasOwn, writable: true, configurable: true });
  }
});
