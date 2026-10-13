/** My organization calls over the browser session, through the shared JSON requester. Names and role labels only (cadre stays in the API, unshown). */
import type { JsonRequester } from "../workspace/api";

const ORG_API = "/api/v1/organization";

export interface OrgPerson {
  name: string;
  cadre: string;
  roles?: string[];
}

export interface MyUnit {
  org_unit_id: string;
  unit_name: string;
  level_name: string;
  cadres: string[];
}

export interface AboveUnit {
  org_unit_id: string;
  unit_name: string;
  level_name: string;
  /** Absent on an older server; the tree then falls back to a flat layout. */
  parent_org_unit_id?: string | null;
  people: OrgPerson[];
}

export interface LevelUnit {
  org_unit_id: string;
  unit_name: string;
  parent_org_unit_id?: string | null;
  people: OrgPerson[];
}

/** A child unit one level below; its people load when it is opened. */
export interface BelowUnit {
  org_unit_id: string;
  unit_name: string;
  level_name: string;
  parent_org_unit_id?: string | null;
  people_count: number;
  has_children: boolean;
}

export interface OrgProject {
  project_id: string;
  project_name: string;
  my_units: MyUnit[];
  above: AboveUnit[];
  my_level: LevelUnit[];
  below: BelowUnit[];
}

/** An opened unit: its people and its child units (same shape as `below`). */
export interface UnitPeople {
  unit: { org_unit_id: string; unit_name: string; level_name: string };
  people: OrgPerson[];
  children: BelowUnit[];
}

export async function getMyOrganization(request: JsonRequester): Promise<OrgProject[]> {
  const reply = (await request(`${ORG_API}/me`)) as { projects: OrgProject[] };
  return reply.projects;
}

export function getUnitPeople(request: JsonRequester, orgUnitId: string): Promise<UnitPeople> {
  return request(`${ORG_API}/units/${encodeURIComponent(orgUnitId)}/people`) as Promise<UnitPeople>;
}
