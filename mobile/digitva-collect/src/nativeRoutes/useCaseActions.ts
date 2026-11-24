/**
 * The case screen's actions, moved out of its component unchanged: queue a contact attempt or visit, discard a queued
 * action or a refused registration, call an informant, open directions, share the location. They share the screen's
 * busy flag and message, and drop late answers by the request generation and route identity the screen keeps.
 */
import { randomUUID } from "expo-crypto";
import type { useRouter } from "expo-router";
import { Alert, Linking, Platform, Share } from "react-native";
import type { MutableRefObject } from "react";

import {
  deleteAction,
  discardRegistration,
  queueAction,
  visitAt,
  type CaseAction,
  type CaseDetail,
  type ContactOutcome,
  type Registration,
} from "../cases";
import { canFollowUpDeath, deathDirectionsUrls, deathPhoneUrl, deathShareUrl, type DeathFix } from "../deathWorkflow";
import type { Db } from "../drafts";
import { t } from "../i18n";
import { errorText } from "../ui";

export interface CaseActionsContext {
  db: Db | undefined;
  found: CaseDetail | undefined;
  registration: Registration | undefined;
  mode: "attempt" | "visit" | undefined;
  editingId: string | undefined;
  outcome: ContactOutcome | undefined;
  date: string;
  actionBusy: boolean;
  params: { projectId?: string };
  deathId: string | undefined;
  clientDeathId: string | undefined;
  requestGeneration: MutableRefObject<number>;
  routeIdentityRef: MutableRefObject<string>;
  routeIdentity: string;
  router: ReturnType<typeof useRouter>;
  load(handle: Db, isCurrent?: () => boolean): Promise<void>;
  setActionBusy(busy: boolean): void;
  setMessage(message: string): void;
  setMode(mode: "attempt" | "visit" | undefined): void;
}

export function useCaseActions(ctx: CaseActionsContext) {
  const { db, found, registration, mode, editingId, outcome, date, actionBusy, params, deathId, clientDeathId, requestGeneration, routeIdentityRef, routeIdentity, router, load, setActionBusy, setMessage, setMode } = ctx;
  async function saveAction() {
    if (!db || !mode || actionBusy) return;
    if (
      !(found
        ? canFollowUpDeath(found.state)
        : registration?.state === "pending")
    ) {
      setMessage(t("caseActionsUnavailable"));
      return;
    }
    const generation = requestGeneration.current;
    const identity = routeIdentity;
    const isCurrent = () =>
      requestGeneration.current === generation &&
      routeIdentityRef.current === identity;
    setActionBusy(true);
    setMessage("");
    const at = date.trim() ? visitAt(date.trim()) : null;
    const day = 86_400_000;
    const time = at ? new Date(at).getTime() : 0;
    // The server takes yesterday to 366 days ahead (web_intake_service._clean_visit_at).
    if (
      (date.trim() && !at) ||
      (mode === "visit" && !at) ||
      (at && (time < Date.now() - day || time > Date.now() + 366 * day))
    ) {
      setMessage(t("errVisitDate"));
      setActionBusy(false);
      return;
    }
    if (mode === "attempt" && !outcome) {
      setMessage(t("errRequired"));
      setActionBusy(false);
      return;
    }
    try {
      await queueAction(db, {
        project_id:
          found?.project_id ??
          registration?.project_id ??
          params.projectId ??
          "",
        client_id: editingId ?? randomUUID(),
        kind: mode,
        death_id: deathId ?? null,
        client_death_id: clientDeathId ?? null,
        body:
          mode === "attempt"
            ? {
                outcome,
                ...(at && outcome !== "refused" ? { next_visit_at: at } : {}),
              }
            : { next_visit_at: at },
      });
      if (!isCurrent()) return;
      setMode(undefined);
      setMessage(t("queued"));
      await load(db, isCurrent);
    } catch (error) {
      if (isCurrent()) setMessage(errorText(error));
    } finally {
      if (isCurrent()) setActionBusy(false);
    }
  }

  async function discard(action: CaseAction) {
    if (!db || actionBusy) return;
    const generation = requestGeneration.current;
    const identity = routeIdentity;
    const isCurrent = () =>
      requestGeneration.current === generation &&
      routeIdentityRef.current === identity;
    setActionBusy(true);
    setMessage("");
    try {
      await deleteAction(db, action.client_id);
      if (!isCurrent()) return;
      await load(db, isCurrent);
    } catch (error) {
      if (isCurrent()) setMessage(errorText(error));
    } finally {
      if (isCurrent()) setActionBusy(false);
    }
  }

  async function discardThisRegistration() {
    if (!db || !clientDeathId || actionBusy) return;
    const generation = requestGeneration.current;
    const identity = routeIdentity;
    const isCurrent = () =>
      requestGeneration.current === generation &&
      routeIdentityRef.current === identity;
    setActionBusy(true);
    setMessage("");
    try {
      await discardRegistration(db, clientDeathId);
      if (isCurrent()) router.back();
    } catch (error) {
      if (isCurrent()) setMessage(errorText(error));
    } finally {
      if (isCurrent()) setActionBusy(false);
    }
  }

  async function callPhone(phone: string) {
    const url = deathPhoneUrl(phone);
    if (!url || actionBusy) return;
    const generation = requestGeneration.current;
    const identity = routeIdentity;
    const isCurrent = () =>
      requestGeneration.current === generation &&
      routeIdentityRef.current === identity;
    setActionBusy(true);
    setMessage("");
    try {
      await Linking.openURL(url);
    } catch (error) {
      if (isCurrent()) setMessage(errorText(error));
    } finally {
      if (isCurrent()) setActionBusy(false);
    }
  }

  // Same busy and error handling as callPhone. Coordinates are never logged.
  async function openDirections(fix: DeathFix, iosApp?: "apple" | "google") {
    if (actionBusy) return;
    if (Platform.OS === "ios" && !iosApp) {
      // Map app names are brand names, the same in every language.
      Alert.alert(t("directions"), undefined, [
        { text: "Google Maps", onPress: () => void openDirections(fix, "google") },
        { text: "Apple Maps", onPress: () => void openDirections(fix, "apple") },
        { text: t("cancel"), style: "cancel" },
      ]);
      return;
    }
    setActionBusy(true);
    setMessage("");
    let failure: unknown;
    try {
      for (const url of deathDirectionsUrls(fix, Platform.OS, iosApp)) {
        try {
          await Linking.openURL(url);
          failure = undefined;
          break;
        } catch (error) {
          failure = error;
        }
      }
      if (failure) setMessage(errorText(failure));
    } finally {
      setActionBusy(false);
    }
  }

  async function shareLocation(fix: DeathFix) {
    if (actionBusy) return;
    setActionBusy(true);
    setMessage("");
    try {
      await Share.share({ message: deathShareUrl(fix) });
    } catch (error) {
      setMessage(errorText(error));
    } finally {
      setActionBusy(false);
    }
  }

  return { saveAction, discard, discardThisRegistration, callPhone, openDirections, shareLocation };
}
