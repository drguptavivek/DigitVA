/**
 * ES2022 methods the app and the WHO engine call that iOS Safari only gained in 15.4 (March 2022): `.at()` and
 * `Object.hasOwn`. An iPhone left on iOS 15.0-15.3 would otherwise throw mid-interview. Imported first by
 * app/_layout.tsx. ponytail: only the methods in use; add others here if a newer API slips in.
 */
function at<T>(this: ArrayLike<T>, index: number): T | undefined {
  const length = this.length;
  let i = Math.trunc(index) || 0;
  if (i < 0) i += length;
  return i < 0 || i >= length ? undefined : this[i];
}

for (const proto of [Array.prototype, String.prototype, Object.getPrototypeOf(Int8Array.prototype)]) {
  if (!proto.at) Object.defineProperty(proto, "at", { value: at, writable: true, configurable: true });
}

if (!Object.hasOwn) {
  Object.defineProperty(Object, "hasOwn", {
    value: (object: object, key: PropertyKey) => Object.prototype.hasOwnProperty.call(object, key),
    writable: true,
    configurable: true,
  });
}

export {};
