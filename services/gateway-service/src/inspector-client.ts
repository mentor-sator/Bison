import { request } from "undici";
import { config } from "./config.js";

export interface InspectionEvidence {
  kind: string;
  excerpt: string | null;
}

export interface InspectionResult {
  criterion_id: string;
  task_id: string;
  statement: string;
  check_kind: string;
  verdict: string;
  reasoning: string;
  evidence: InspectionEvidence[];
  status_before: string;
  status_after: string;
}

export interface InspectionReport {
  project_id: string;
  workspace: string;
  inspected_at: string;
  verified: number;
  failed: number;
  inconclusive: number;
  changed: number;
  results: InspectionResult[];
}

export class InspectorError extends Error {
  constructor(
    readonly status: number,
    readonly detail: unknown,
  ) {
    super(`inspector-service responded ${status}`);
    this.name = "InspectorError";
  }
}

function readDetail(text: string): unknown {
  try {
    const parsed: unknown = JSON.parse(text);
    if (typeof parsed === "object" && parsed !== null && "detail" in parsed) {
      return (parsed as { detail: unknown }).detail;
    }
    return parsed;
  } catch {
    return text;
  }
}

async function send<T>(method: "GET" | "POST", path: string): Promise<T> {
  const response = await request(`${config.inspectorUrl}${path}`, { method });
  const text = await response.body.text();

  if (response.statusCode >= 400) {
    throw new InspectorError(response.statusCode, readDetail(text));
  }

  return JSON.parse(text) as T;
}

export async function inspectProject(projectId: string): Promise<InspectionReport> {
  return send<InspectionReport>("POST", `/projects/${encodeURIComponent(projectId)}/inspect`);
}

export async function inspectTask(projectId: string, taskId: string): Promise<InspectionReport> {
  return send<InspectionReport>(
    "POST",
    `/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(taskId)}/inspect`,
  );
}

export async function inspectorHealthy(): Promise<boolean> {
  try {
    await send<unknown>("GET", "/health");
    return true;
  } catch {
    return false;
  }
}
