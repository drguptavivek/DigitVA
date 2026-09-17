import { useRouter } from "expo-router";
import { Pressable, Text, View } from "react-native";

import { DemoChrome, EmptyState, ScreenHeader, ScreenScroll, styles } from "../components/DemoLayout";
import { countAnswers, formatDateTime, useDemoState } from "../components/DemoState";

export default function DraftsRoute() {
  const router = useRouter();
  const { cases, drafts } = useDemoState();
  const caseUids = new Set(cases.map((entry) => entry.uid));
  const standaloneDrafts = drafts.filter((draft) => !caseUids.has(draft.id));

  return (
    <DemoChrome>
      <ScreenScroll>
        <ScreenHeader
          actionLabel="Case Entry"
          onAction={() => {
            router.push("/case-entry");
          }}
          title="Cases"
        />
        {cases.length === 0 ? (
          <EmptyState message="No local SQLite cases saved on this device." />
        ) : (
          cases.map((entry) => {
            const matchingDraft = drafts.find((draft) => draft.id === entry.uid);
            return (
              <Pressable
                accessibilityRole="button"
                key={entry.uid}
                onPress={() => router.push({ pathname: "/start", params: { caseUid: entry.uid } })}
                style={styles.listItem}
              >
                <View style={styles.listItemText}>
                  <Text style={styles.listItemTitle}>{entry.caseEntry.deceasedFullName}</Text>
                  <Text style={styles.listItemMeta}>
                    {matchingDraft
                      ? `${countAnswers(matchingDraft)} draft answers, updated ${formatDateTime(matchingDraft.updatedAt)}`
                      : `Case updated ${formatDateTime(entry.updatedAt)}`}
                  </Text>
                  <Text numberOfLines={1} style={styles.listItemId}>
                    {entry.uid}
                  </Text>
                </View>
                <Text style={styles.listItemAction}>{matchingDraft ? "Continue" : "Open"}</Text>
              </Pressable>
            );
          })
        )}
        <Text style={[styles.screenTitleCompact, { marginTop: 24 }]}>Questionnaire Drafts</Text>
        {standaloneDrafts.length === 0 ? (
          <EmptyState message="No WHO VA questionnaire drafts saved on this device." />
        ) : (
          standaloneDrafts.map((draft) => (
            <Pressable
              accessibilityRole="button"
              key={draft.id}
              onPress={() => router.push({ pathname: "/continue", params: { draftId: draft.id } })}
              style={styles.listItem}
            >
              <View style={styles.listItemText}>
                <Text style={styles.listItemTitle}>{countAnswers(draft)} answers</Text>
                <Text style={styles.listItemMeta}>Updated {formatDateTime(draft.updatedAt)}</Text>
                <Text numberOfLines={1} style={styles.listItemId}>
                  {draft.id}
                </Text>
              </View>
              <Text style={styles.listItemAction}>Open</Text>
            </Pressable>
          ))
        )}
      </ScreenScroll>
    </DemoChrome>
  );
}
