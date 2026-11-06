const { setColor, setPickerColors, setPickerTheme, PICKER_COLORS, LIGHT_ACCENT, NIGHT_ACCENT } = require("../plugins/with-android-theme");
const appJson = require("../app.json");

const styles = () => ({ resources: { style: [{ $: { name: "AppTheme", parent: "Theme.AppCompat.DayNight.NoActionBar" }, item: [] }] } });

it("points the app theme's date picker at a dialog style that sets colorAccent", () => {
  const { resources } = setPickerTheme(styles());
  const app = resources.style.find((s) => s.$.name === "AppTheme");
  expect(app.item).toContainEqual({ $: { name: "android:datePickerDialogTheme" }, _: "@style/DigitvaPickerDialog" });
  const dialog = resources.style.find((s) => s.$.name === "DigitvaPickerDialog");
  // A theme overlay, not a full AppCompat dialog theme: the full theme left the dark calendar body white.
  expect(dialog.$.parent).toBe("android:ThemeOverlay.Material.Dialog");
  expect(dialog.item.map((i) => i._)).toEqual([
    "@color/digitva_picker_accent", "@color/digitva_picker_accent", "@color/digitva_picker_surface", "@color/digitva_picker_header_secondary", "@style/DigitvaPickerDatePicker",
  ]);
  const picker = resources.style.find((s) => s.$.name === "DigitvaPickerDatePicker");
  expect(picker.item.map((i) => i._)).toEqual(["@color/digitva_picker_header"]);
});

it("gives night the app card and onPrimary ink, and keeps light white on the accent header", () => {
  expect(PICKER_COLORS.light).toEqual({ digitva_picker_surface: "#ffffff", digitva_picker_header: "#1f4d60", digitva_picker_header_secondary: "#b3ffffff" });
  expect(PICKER_COLORS.night).toEqual({ digitva_picker_surface: "#1a2127", digitva_picker_header: "#6fb6d6", digitva_picker_header_secondary: "#cc0e181c" });
  const night = setPickerColors({ resources: {} }, NIGHT_ACCENT, PICKER_COLORS.night).resources.color;
  expect(night.map((c) => c.$.name)).toEqual(["digitva_picker_accent", "digitva_picker_surface", "digitva_picker_header", "digitva_picker_header_secondary"]);
});

it("is idempotent", () => {
  const once = setPickerTheme(styles());
  const twice = setPickerTheme(JSON.parse(JSON.stringify(once)));
  expect(twice).toEqual(once);
});

it("writes the light and night accents, replacing an existing entry", () => {
  expect(setColor({ resources: {} }, LIGHT_ACCENT).resources.color).toEqual([{ $: { name: "digitva_picker_accent" }, _: "#1f4d60" }]);
  expect(NIGHT_ACCENT).toBe("#6fb6d6");
  expect(setColor(setColor({ resources: {} }, "#000000"), NIGHT_ACCENT).resources.color).toHaveLength(1);
});

it("fails clearly without AppTheme and is registered in app.json", () => {
  expect(() => setPickerTheme({ resources: { style: [] } })).toThrow(/AppTheme/);
  expect(appJson.expo.plugins).toContain("./plugins/with-android-theme");
});
