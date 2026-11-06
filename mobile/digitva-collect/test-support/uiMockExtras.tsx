/**
 * The form and link pieces src/ui.tsx added for the design review (FieldLabel, FieldHint, SectionLabel, TextField,
 * TextLink), for tests that mock "../src/ui" with a hand-written object. `withUiExtras(mock)` adds the ones the mock
 * lacks: TextLink is a Pressable with the real one's role, name and handler, TextField is React Native's TextInput,
 * and the labels render their text.
 */
import type { ReactNode } from "react";

type Mock = Record<string, unknown>;

export function withUiExtras(mock: Mock): Mock {
  const ReactActual = jest.requireActual("react") as typeof import("react");
  const { Pressable, Text, TextInput } = jest.requireActual("react-native") as typeof import("react-native");
  const { t } = require("../src/i18n") as { t: (key: string) => string };
  return {
    FieldLabel: ({ label, required, testID }: { label: string; required?: boolean; testID?: string }) =>
      required
        ? ReactActual.createElement(Text, { testID }, label, ReactActual.createElement(Text, null, `  ${t("fieldRequiredMark")}`))
        : ReactActual.createElement(Text, { testID }, label),
    FieldHint: ({ children, testID }: { children?: ReactNode; testID?: string }) => ReactActual.createElement(Text, { testID }, children),
    SectionLabel: ({ children }: { children?: ReactNode }) => ReactActual.createElement(Text, null, children),
    TextField: ({ onCard: _onCard, invalid: _invalid, ...props }: Record<string, unknown>) => ReactActual.createElement(TextInput, props),
    TextLink: ({ label, onPress, disabled, accessibilityLabel, testID }: { label: string; onPress: () => void; disabled?: boolean; accessibilityLabel?: string; testID?: string }) =>
      ReactActual.createElement(Pressable, { testID, accessibilityRole: "button", accessibilityLabel: accessibilityLabel ?? label, accessibilityState: { disabled }, disabled, onPress }, ReactActual.createElement(Text, null, label)),
    ...mock,
  };
}
