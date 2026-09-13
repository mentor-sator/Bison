import { describeFailure } from "./broker";
import { isHaltSignal, isHaltStateReport, type HaltSignal, type HaltStateReport } from "./halt";

export const PROJECT_STATES = ["draft", "active", "paused", "archived"] as const;

export type ProjectState = (typeof PROJECT_STATES)[number];

export interface Project {
  id: string;
  name: string;
  goal: string;
  project_type: string;
  state: ProjectState;
  description: string | null;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

export interface ProjectList {
  projects: Project[];
  open_projects: number;
  max_projects: number;
}

export interface SwitchOutcome {
  switched: boolean;
  activated: Project;
  paused: string | null;
  signal: HaltSignal | null;
  halt: HaltStateReport;
}

const asRecord = (value: unknown): Record<string, unknown> | null => {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : null;
};

export const isProjectState = (value: unknown): value is ProjectState => {
  return typeof value === "string" && PROJECT_STATES.includes(value as ProjectState);
};

export const isProject = (value: unknown): value is Project => {
  const candidate = asRecord(value);

  if (candidate === null) {
    return false;
  }

  return (
    typeof candidate["id"] === "string" &&
    typeof candidate["name"] === "string" &&
    typeof candidate["goal"] === "string" &&
    isProjectState(candidate["state"])
  );
};

export const isProjectList = (value: unknown): value is ProjectList => {
  const candidate = asRecord(value);

  if (candidate === null) {
    return false;
  }

  return (
    Array.isArray(candidate["projects"]) &&
    candidate["projects"].every(isProject) &&
    typeof candidate["open_projects"] === "number" &&
    typeof candidate["max_projects"] === "number"
  );
};

export const isSwitchOutcome = (value: unknown): value is SwitchOutcome => {
  const candidate = asRecord(value);

  if (candidate === null) {
    return false;
  }

  const signal = candidate["signal"];

  return (
    typeof candidate["switched"] === "boolean" &&
    isProject(candidate["activated"]) &&
    (candidate["paused"] === null || typeof candidate["paused"] === "string") &&
    (signal === null || isHaltSignal(signal)) &&
    isHaltStateReport(candidate["halt"])
  );
};

export function activeProject(list: ProjectList): Project | null {
  return list.projects.find((project) => project.state === "active") ?? null;
}

export function switchTargets(list: ProjectList): Project[] {
  return list.projects.filter(
    (project) => project.state !== "archived" && project.state !== "active",
  );
}

export function describeCapacity(list: ProjectList): string {
  return `${list.open_projects} of ${list.max_projects} open`;
}

export async function fetchProjects(baseUrl: string): Promise<ProjectList> {
  const response = await fetch(`${baseUrl}/projects`);

  if (!response.ok) {
    throw await describeFailure(response);
  }

  const parsed: unknown = await response.json();

  if (!isProjectList(parsed)) {
    throw new Error("project list response did not match the expected shape");
  }

  return parsed;
}

export async function requestSwitch(
  baseUrl: string,
  projectId: string,
  actor = "user",
): Promise<SwitchOutcome> {
  const response = await fetch(`${baseUrl}/projects/${encodeURIComponent(projectId)}/activate`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ reason: "project switch", actor }),
  });

  if (!response.ok) {
    throw await describeFailure(response);
  }

  const parsed: unknown = await response.json();

  if (!isSwitchOutcome(parsed)) {
    throw new Error("project switch response did not match the expected shape");
  }

  return parsed;
}
