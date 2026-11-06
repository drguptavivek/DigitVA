const { withAndroidColors, withAndroidColorsNight, withAndroidStyles } = require("@expo/config-plugins");

const COLOR_NAME = "digitva_picker_accent";
const DIALOG_STYLE = "DigitvaPickerDialog";
const PICKER_STYLE = "DigitvaPickerDatePicker";
const LIGHT_ACCENT = "#1f4d60";
const NIGHT_ACCENT = "#6fb6d6";
// Dialog body and header: light is white text on the primary header as before; night is the app card (ui.card)
// with the light primary header. The header text is the framework's inverse text (android:headerTextColor is
// private): white in light, dark ink in night, so night needs the light primary behind it (checked on the emulator).
const PICKER_COLORS = {
  light: { digitva_picker_surface: "#ffffff", digitva_picker_header: "#1f4d60", digitva_picker_header_secondary: "#b3ffffff" },
  night: { digitva_picker_surface: "#1a2127", digitva_picker_header: "#6fb6d6", digitva_picker_header_secondary: "#cc0e181c" },
};

/**
 * The system date picker (register.tsx, DORIS DateField) takes its header, buttons and selected day from colorAccent;
 * unthemed it is Material teal. Light uses the primary accent, night the light primary from the token table.
 * Replaces an existing entry by name so reruns stay idempotent.
 */
function setColor(colors, value, name = COLOR_NAME) {
  const list = ((colors.resources ??= {}).color ??= []);
  const entry = { $: { name }, _: value };
  const index = list.findIndex((item) => item.$?.name === name);
  if (index >= 0) list[index] = entry;
  else list.push(entry);
  return colors;
}

function setPickerColors(colors, accent, palette) {
  setColor(colors, accent);
  for (const [name, value] of Object.entries(palette)) setColor(colors, value, name);
  return colors;
}

function upsert(list, entry, key = (item) => item.$?.name) {
  const index = list.findIndex((item) => key(item) === key(entry));
  if (index >= 0) list[index] = entry;
  else list.push(entry);
}

function setPickerTheme(styles) {
  const list = ((styles.resources ??= {}).style ??= []);
  upsert(list, {
    $: { name: DIALOG_STYLE, parent: "android:ThemeOverlay.Material.Dialog" },
    item: [
      { $: { name: "colorAccent" }, _: `@color/${COLOR_NAME}` },
      { $: { name: "android:colorAccent" }, _: `@color/${COLOR_NAME}` },
      { $: { name: "android:colorBackground" }, _: "@color/digitva_picker_surface" },
      // The header year: light keeps the framework value (white 70%); night is ink 80%, 5.4:1 on the light primary.
      { $: { name: "android:textColorSecondaryInverse" }, _: "@color/digitva_picker_header_secondary" },
      { $: { name: "android:datePickerStyle" }, _: `@style/${PICKER_STYLE}` },
    ],
  });
  // The header follows colorAccent in light already; naming it gives night the light primary.
  upsert(list, {
    $: { name: PICKER_STYLE, parent: "android:Widget.Material.Light.DatePicker" },
    item: [
      { $: { name: "android:headerBackground" }, _: "@color/digitva_picker_header" },
    ],
  });

  const appTheme = list.find((item) => item.$?.name === "AppTheme");
  if (!appTheme) throw new Error("Android styles.xml has no AppTheme style");
  upsert((appTheme.item ??= []), { $: { name: "android:datePickerDialogTheme" }, _: `@style/${DIALOG_STYLE}` });
  return styles;
}

module.exports = (config) => {
  config = withAndroidColors(config, (c) => {
    c.modResults = setPickerColors(c.modResults, LIGHT_ACCENT, PICKER_COLORS.light);
    return c;
  });
  config = withAndroidColorsNight(config, (c) => {
    c.modResults = setPickerColors(c.modResults, NIGHT_ACCENT, PICKER_COLORS.night);
    return c;
  });
  return withAndroidStyles(config, (c) => {
    c.modResults = setPickerTheme(c.modResults);
    return c;
  });
};
module.exports.setColor = setColor;
module.exports.setPickerColors = setPickerColors;
module.exports.PICKER_COLORS = PICKER_COLORS;
module.exports.setPickerTheme = setPickerTheme;
module.exports.LIGHT_ACCENT = LIGHT_ACCENT;
module.exports.NIGHT_ACCENT = NIGHT_ACCENT;
