import { useRouter } from "expo-router";
import * as FileSystem from "expo-file-system/legacy";
import { useState } from "react";
import { Pressable, Text, View } from "react-native";

import { DemoChrome, EmptyState, ScreenHeader, ScreenScroll, styles } from "../components/DemoLayout";
import type { CompletedSubmission } from "../components/DemoState";
import { formatDateTime, useDemoState } from "../components/DemoState";

const EXPORT_DIR = `${FileSystem.documentDirectory ?? ""}who-va-exports/`;

function caseUidFromCompleted(submission: CompletedSubmission): string {
  const caseUid = submission.result.data.__caseUid;
  return typeof caseUid === "string" ? caseUid : (submission.caseEntry?.uid ?? submission.id);
}

async function exportCompletedSubmission(submission: CompletedSubmission): Promise<string> {
  if (!FileSystem.documentDirectory) throw new Error("Expo document storage is unavailable.");
  await FileSystem.makeDirectoryAsync(EXPORT_DIR, { intermediates: true });
  const uid = caseUidFromCompleted(submission).replace(/[^A-Za-z0-9._-]/gu, "_");
  const path = `${EXPORT_DIR}${uid}.json`;
  await FileSystem.writeAsStringAsync(path, JSON.stringify(submission, null, 2), {
    encoding: FileSystem.EncodingType.UTF8
  });
  return path;
}

export default function CompletedRoute() {
  const router = useRouter();
  const { beginNewInterview, completed } = useDemoState();
  const [exportMessage, setExportMessage] = useState("");

  return (
    <DemoChrome>
      <ScreenScroll>
        <ScreenHeader
          actionLabel="Start New"
          onAction={() => {
            beginNewInterview();
            router.push("/start");
          }}
          title="Completed"
        />
        {completed.length === 0 ? (
          <EmptyState message="Completed submissions will appear here after the final section validates." />
        ) : (
          <>
            {exportMessage ? <Text style={styles.validText}>{exportMessage}</Text> : null}
            {completed.map((submission) => (
              <View key={submission.id} style={styles.listItem}>
                <View style={styles.listItemText}>
                  <Text style={styles.listItemTitle}>
                    {submission.caseEntry?.deceasedFullName ?? caseUidFromCompleted(submission)}
                  </Text>
                  <Text style={styles.listItemMeta}>
                    {Object.keys(submission.result.data).length} answers
                  </Text>
                  <Text style={styles.listItemMeta}>Completed {formatDateTime(submission.completedAt)}</Text>
                  <Text style={submission.result.valid ? styles.validText : styles.invalidText}>
                    {submission.result.valid
                      ? "Valid submission"
                      : `${submission.result.issues.length} issues`}
                  </Text>
                  <Text style={submission.syncStatus === "pending" ? styles.pendingText : styles.validText}>
                    {submission.syncStatus === "pending" ? "Pending server push" : "Pushed to server"}
                  </Text>
                </View>
                <Pressable
                  accessibilityRole="button"
                  onPress={() => {
                    setExportMessage("");
                    void exportCompletedSubmission(submission)
                      .then((path) => setExportMessage(`Saved JSON: ${path}`))
                      .catch((error: unknown) => setExportMessage((error as Error).message));
                  }}
                  style={styles.smallPrimaryButton}
                >
                  <Text style={styles.smallPrimaryButtonText}>Save JSON</Text>
                </Pressable>
              </View>
            ))}
          </>
        )}
      </ScreenScroll>
    </DemoChrome>
  );
}
