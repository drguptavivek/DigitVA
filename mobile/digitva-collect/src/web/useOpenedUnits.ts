import { useState } from "react";

import { ClientApiError } from "../client/api";
import { t } from "../i18n";
import { getUnitPeople } from "../organization/api";
import type { JsonRequester } from "../workspace/api";
import { browserErrorText } from "./common";
import { dropUnitAndBelow, type OpenedUnit } from "./OrgTree";

function unitErrorText(error: unknown): string {
  if (error instanceof ClientApiError && error.status === 404) return t("orgUnitNotAllowed");
  return browserErrorText(error);
}

/** The units opened in an OrgTree and the toggle that opens (loads their people) or closes one; shared by My organization and the Users page. */
export function useOpenedUnits(request: JsonRequester | undefined) {
  const [opened, setOpened] = useState<Record<string, OpenedUnit>>({});

  async function toggle(orgUnitId: string) {
    const state = opened[orgUnitId];
    if (state && !state.error) {
      setOpened((current) => dropUnitAndBelow(current, orgUnitId));
      return;
    }
    if (!request) return;
    setOpened((current) => ({ ...current, [orgUnitId]: { loading: true, error: "" } }));
    try {
      const detail = await getUnitPeople(request, orgUnitId);
      // Skip the reply when the unit was closed while it loaded.
      setOpened((current) => (current[orgUnitId] ? { ...current, [orgUnitId]: { loading: false, error: "", detail } } : current));
    } catch (caught) {
      setOpened((current) => (current[orgUnitId] ? { ...current, [orgUnitId]: { loading: false, error: unitErrorText(caught) } } : current));
    }
  }

  return { opened, toggle };
}
