/**
 * Square tag for a role (small corner radius, not a pill): a colour per role from the theme tokens, and the
 * role name always written. `label` overrides the name (grant grid verbs); `cadre` is appended in brackets.
 * Filter chips are a different control and stay rounded.
 */
import type { ReactNode } from "react";
import { Text, View, type StyleProp, type TextStyle } from "react-native";

import { t, type StringKey } from "../i18n";
import { roleLabelKey } from "../web/roleHome";
import { controlText, fontSize, radius, roleTone, spacing, useTheme } from "../theme";

export function RoleChip({ role, label, cadre }: { role: string; label?: string; cadre?: string | null }) {
  const { mode } = useTheme();
  const tone = roleTone(mode, role);
  const name = label ?? t(roleLabelKey(role));
  return (
    <View
      testID={`role-chip-${role}`}
      style={{ alignSelf: "flex-start", backgroundColor: tone.bg, borderColor: tone.border, borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: spacing.xs, paddingVertical: 2 }}
    >
      <Text style={[controlText, { color: tone.fg, fontSize: fontSize.caption, lineHeight: 18, fontWeight: "600" }]}>
        {cadre ? t("orgRoleCadre", { role: name, cadre }) : name}
      </Text>
    </View>
  );
}

/** Chips (and short text) side by side, wrapping. */
export function RoleChips({ children }: { children: ReactNode }) {
  return <View style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: spacing.xxs }}>{children}</View>;
}

const SPLIT = "\u0001";

/**
 * A translated sentence with a `{roles}` slot filled by role chips: text before, chips, text after. Splitting the
 * translation at the slot keeps every language's word order. `textStyle` colours the surrounding words.
 */
export function RoleSentence({ k, params, roles, textStyle }: {
  k: StringKey;
  params?: Record<string, string | number>;
  roles: { role: string; cadre?: string | null; label?: string }[];
  textStyle: StyleProp<TextStyle>;
}) {
  const [before, after] = t(k, { ...params, roles: SPLIT }).split(SPLIT);
  return (
    <RoleChips>
      {before.trim() ? <Text style={textStyle}>{before.trim()}</Text> : null}
      {roles.map((r, index) => <RoleChip key={index} role={r.role} cadre={r.cadre} label={r.label} />)}
      {after?.trim() ? <Text style={textStyle}>{after.trim()}</Text> : null}
    </RoleChips>
  );
}
