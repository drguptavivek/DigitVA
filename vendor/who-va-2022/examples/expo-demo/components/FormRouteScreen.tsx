import { AppState, Pressable, Text, View, type AppStateStatus } from "react-native";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useRef } from "react";

import type {
  SubmissionData,
  SubmissionValidationResult,
  WhoVaDraft,
  WhoVaDraftController
} from "@drguptavivek/who-2022-va";
import { WhoVaForm } from "@drguptavivek/who-2022-va/native";

import { DemoChrome, EmptyState, styles } from "./DemoLayout";
import { countAnswers, useDemoState, type CaseEntryData } from "./DemoState";
import { useExpoWhoVaPlatformServices } from "./ExpoPlatformServices";

export function FormRouteScreen({
  caseEntry,
  draft,
  draftId,
  emptyMessage,
  formKey,
  initialData,
  lockedQuestionNames,
  title
}: {
  caseEntry?: CaseEntryData;
  draft?: WhoVaDraft;
  draftId?: string;
  emptyMessage?: string;
  formKey: string;
  initialData?: SubmissionData;
  lockedQuestionNames?: string[];
  title: string;
}) {
  const router = useRouter();
  const { addCompleted, draftStore, setLastUpdate } = useDemoState();
  const platform = useExpoWhoVaPlatformServices();
  const draftControllerRef = useRef<WhoVaDraftController | undefined>(undefined);
  const appStateRef = useRef<AppStateStatus>(AppState.currentState);
  const saveBeforeRoute = useCallback(
    async (route: Parameters<typeof router.push>[0]) => {
      try {
        await draftControllerRef.current?.saveDraft();
      } catch (error) {
        setLastUpdate(`Draft save failed: ${(error as Error).message}`);
      }
      router.push(route);
    },
    [router, setLastUpdate]
  );
  const saveCurrentDraft = useCallback(async () => {
    if (!draftControllerRef.current) {
      setLastUpdate("Draft is not ready yet");
      return;
    }
    try {
      await draftControllerRef.current.saveDraft();
    } catch (error) {
      setLastUpdate(`Draft save failed: ${(error as Error).message}`);
    }
  }, [setLastUpdate]);

  useEffect(() => {
    const subscription = AppState.addEventListener("change", (nextState) => {
      const wasActive = appStateRef.current === "active";
      appStateRef.current = nextState;
      if (!wasActive || nextState === "active") return;
      setLastUpdate("Saving draft before app backgrounding");
      void draftControllerRef.current?.saveDraft();
    });

    return () => subscription.remove();
  }, [setLastUpdate]);

  if (emptyMessage) {
    return (
      <DemoChrome>
        <View style={styles.formToolbar}>
          <Pressable
            accessibilityRole="button"
            onPress={() => void saveBeforeRoute("/")}
            style={styles.backButton}
          >
            <Text style={styles.backButtonText}>Home</Text>
          </Pressable>
          <Text style={styles.formToolbarTitle}>{title}</Text>
          <Pressable
            accessibilityRole="button"
            onPress={() => void saveCurrentDraft()}
            style={styles.backButton}
          >
            <Text style={styles.backButtonText}>Save</Text>
          </Pressable>
        </View>
        <View style={styles.screen}>
          <EmptyState message={emptyMessage} />
        </View>
      </DemoChrome>
    );
  }

  return (
    <DemoChrome>
      <View style={styles.formShell}>
        <View style={styles.formToolbar}>
          <Pressable
            accessibilityRole="button"
            onPress={() => void saveBeforeRoute("/")}
            style={styles.backButton}
          >
            <Text style={styles.backButtonText}>Home</Text>
          </Pressable>
          <Text style={styles.formToolbarTitle}>{title}</Text>
          <Pressable
            accessibilityRole="button"
            onPress={() => void saveCurrentDraft()}
            style={styles.backButton}
          >
            <Text style={styles.backButtonText}>Save</Text>
          </Pressable>
        </View>
        <WhoVaForm
          key={formKey}
          draftId={draft?.id ?? draftId}
          draftStore={draftStore}
          initialData={draft?.data ?? initialData}
          lockedQuestionNames={lockedQuestionNames}
          platform={platform}
          autoSaveDraftIntervalMs={false}
          onChange={(data) => {
            setLastUpdate(`${Object.keys(data).length} draft answers captured`);
          }}
          onComplete={(result: SubmissionValidationResult) => {
            addCompleted(result, caseEntry);
            router.push("/completed");
          }}
          onDraftController={(controller) => {
            draftControllerRef.current = controller;
          }}
          onDraftError={(error) => {
            setLastUpdate(`Draft save failed: ${error.message}`);
          }}
          onDraftSaved={(savedDraft) => {
            setLastUpdate(`Draft saved: ${countAnswers(savedDraft)} answers`);
          }}
        />
      </View>
    </DemoChrome>
  );
}
