/** Home KPI strip call over the browser session, through the shared JSON requester. */
import type { JsonRequester } from "../workspace/api";

const KPI_API = "/api/v1/me/kpis";

/** One project's counts. Percentages are of deaths reported and null when none are reported. */
export interface ProjectKpi {
  project_id: string;
  project_name: string;
  deaths_reported: number;
  interviews_done: number;
  coded: number;
  interviews_pct: number | null;
  coded_pct: number | null;
}

export async function getHomeKpis(request: JsonRequester): Promise<ProjectKpi[]> {
  const reply = (await request(KPI_API)) as { projects: ProjectKpi[] };
  return reply.projects;
}
