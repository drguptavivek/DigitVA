import React, { useEffect, useRef, useState } from "react";
import { Pressable, Text, View } from "react-native";

import { useAppState } from "../AppState";
import { requestClientJson } from "../api";
import { useTheme } from "../theme";

type ProfileField = "job_title" | "year_of_birth" | "sex";
type ProfileNudgeResponse = { profile_nudge: boolean; missing_profile_fields: ProfileField[] };

const FIELD_LABELS: Record<ProfileField, string> = {
  job_title: "job title",
  year_of_birth: "year of birth",
  sex: "sex",
};
const PROFILE_FIELDS = new Set<ProfileField>(["job_title", "year_of_birth", "sex"]);

function parseProfileNudge(value: unknown): ProfileNudgeResponse {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("malformed_profile_nudge");
  const body = value as { profile_nudge?: unknown; missing_profile_fields?: unknown };
  if (typeof body.profile_nudge !== "boolean" || !Array.isArray(body.missing_profile_fields)) {
    throw new Error("malformed_profile_nudge");
  }
  const missing = body.missing_profile_fields.filter((field): field is ProfileField =>
    typeof field === "string" && PROFILE_FIELDS.has(field as ProfileField),
  );
  return { profile_nudge: body.profile_nudge, missing_profile_fields: missing };
}

function parseDismissResponse(value: unknown): boolean {
  if (!value || typeof value !== "object" || Array.isArray(value) || typeof (value as { profile_nudge?: unknown }).profile_nudge !== "boolean") {
    throw new Error("malformed_profile_nudge");
  }
  return (value as { profile_nudge: boolean }).profile_nudge;
}

/** One browser-only profile reminder; the server session flag limits it to once per login. */
export default function ProfileNudge() {
  const { bootstrap } = useAppState();
  const theme = useTheme();
  const [missing, setMissing] = useState<ProfileField[] | undefined>();
  const [dismissing, setDismissing] = useState(false);
  const loadedUser = useRef<string | undefined>(undefined);
  const userId = bootstrap?.user.user_id;

  useEffect(() => {
    if (!userId || !bootstrap?.csrf || loadedUser.current === userId) return;
    loadedUser.current = userId;
    let active = true;
    setMissing(undefined);
    void requestClientJson<unknown>("/api/v1/profile/", { csrf: bootstrap.csrf })
      .then((value) => {
        if (!active) return;
        const result = parseProfileNudge(value);
        setMissing(result.profile_nudge ? result.missing_profile_fields : []);
      })
      .catch(() => {
        // A reminder must never prevent access to the app. A fresh login can retry the read.
        if (active) loadedUser.current = undefined;
      });
    return () => { active = false; };
  }, [bootstrap?.csrf, userId]);

  if (!userId || !bootstrap?.csrf || !missing?.length) return null;

  const labels = missing.map((field) => FIELD_LABELS[field]);
  const labelText = labels.length === 1
    ? labels[0]
    : `${labels.slice(0, -1).join(", ")} and ${labels[labels.length - 1]}`;
  const dismiss = async () => {
    if (dismissing) return;
    setDismissing(true);
    try {
      const result = await requestClientJson<unknown>("/api/v1/profile/nudge/dismiss", {
        method: "POST",
        csrf: bootstrap.csrf,
      });
      if (parseDismissResponse(result) === false) setMissing([]);
    } catch {
      // Keep the reminder visible so a transient refusal can be retried.
    } finally {
      setDismissing(false);
    }
  };

  return <View
    accessibilityRole="alert"
    aria-live="polite"
    style={{
      alignItems: "center",
      backgroundColor: theme.ui.warning,
      borderBottomColor: theme.ui.warningBorder,
      borderBottomWidth: 1,
      flexDirection: "row",
      flexWrap: "wrap",
      gap: 8,
      justifyContent: "center",
      paddingHorizontal: 16,
      paddingVertical: 8,
    }}
  >
    <Text style={{ color: theme.ui.warningForeground, fontSize: 14, lineHeight: 20 }}>
      Please complete your profile ({labelText}).
    </Text>
    <a href="/profile/" style={{ color: theme.ui.warningForeground, fontSize: 14, fontWeight: "600" }}>
      My Profile
    </a>
    <Pressable
      accessibilityRole="button"
      accessibilityLabel="Dismiss profile reminder"
      disabled={dismissing}
      onPress={() => void dismiss()}
      style={{ borderColor: theme.ui.warningBorder, borderRadius: 4, borderWidth: 1, minHeight: 32, paddingHorizontal: 10, justifyContent: "center", opacity: dismissing ? 0.6 : 1 }}
    >
      <Text style={{ color: theme.ui.warningForeground, fontSize: 14, fontWeight: "600" }}>Dismiss</Text>
    </Pressable>
  </View>;
}
