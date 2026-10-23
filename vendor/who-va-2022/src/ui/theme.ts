/**
 * Form colour theme. The one file of the engine UI that may hold colour literals: every style, icon stroke
 * and backdrop reads from a `FormTheme`, either `defaultFormTheme` (today's palette, rendered when the host
 * passes no theme) or the `theme` prop of the form. Hosts supply their light and dark variants themselves.
 */
import React from "react";

export interface FormTheme {
  /** Selected option, Next/Complete button fill, progress dots and lines, section headings. */
  primary: string;
  /** Text and icons on a `primary` (or `danger`) fill. */
  onPrimary: string;
  /** Selected-row fill, note and tag backgrounds. */
  primarySoft: string;
  /** Interviewer instructions and guidance text. */
  accent: string;
  /** Cards, inputs and choice rows. */
  surface: string;
  /** Page behind the cards, code chips, read-only inputs, image backdrops. */
  surfaceAlt: string;
  /** Card and divider hairlines. */
  border: string;
  /** The edge of every control and choice row (>= 3:1 against `surface`). */
  borderStrong: string;
  text: string;
  textMuted: string;
  /** Error text, error edges and destructive fills. */
  danger: string;
  dangerSoft: string;
  /** The answered check badge. */
  success: string;
  focus: string;
  /** Modal and drawer backdrop. */
  scrim: string;
}

export const defaultFormTheme: FormTheme = {
  primary: "#147d64",
  onPrimary: "#ffffff",
  primarySoft: "#e3f4ee",
  accent: "#315e73",
  surface: "#ffffff",
  surfaceAlt: "#eef3f0",
  border: "#dce6e1",
  borderStrong: "#9fb4ad",
  text: "#142a24",
  textMuted: "#536b64",
  danger: "#a23a2a",
  dangerSoft: "#fff8f6",
  success: "#147d64",
  focus: "#147d64",
  scrim: "rgba(15, 23, 42, 0.45)"
};

/** The native select's own dark default, used only when the host passes no theme and the device is dark. */
export const defaultDarkFormTheme: FormTheme = {
  ...defaultFormTheme,
  primarySoft: "#374151",
  surface: "#1f2937",
  border: "#4b5563",
  text: "#f9fafb",
  scrim: "rgba(0, 0, 0, 0.45)"
};

/** `undefined` means the host passed no theme: web keeps its CSS variables, native its default palette. */
export const FormThemeContext = React.createContext<FormTheme | undefined>(undefined);

export function useFormTheme(): FormTheme | undefined {
  return React.useContext(FormThemeContext);
}

/** Browser fallbacks of the `--who-2022-web-*` custom properties, rendered when the host sets neither. */
export const webDefaults = {
  canvas: "#f5f7fa",
  surface: "#ffffff",
  ink: "#1f2937",
  inkSubtle: "#374151",
  muted: "#667085",
  brandDeep: "#004687",
  brand: "#1b4f9c",
  brandSoft: "#eaf1fa",
  border: "#e2e8f0",
  controlBorder: "#b8c2d1",
  guidance: "#475569",
  danger: "#b42318",
  dangerBorder: "#d92d20",
  dangerStrong: "#912018",
  dangerSoft: "#fff1f0",
  imageBackground: "#111827",
  backdrop: "rgba(31, 41, 55, 0.45)"
} as const;
