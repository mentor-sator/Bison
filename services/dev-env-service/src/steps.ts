import { stat } from "node:fs/promises";
import { win32 } from "node:path";
import { DevEnvActionSpecSchema, type DevEnvActionSpec } from "@bison/contracts";
import type { Editor, EditorRun } from "./editor.js";

const MAX_DETAIL_CHARS = 500;

export interface StepRequest {
  scopeRoot: string;
  taskId: string | null;
  confirmed: boolean;
  action: DevEnvActionSpec;
}

export interface OutputEvent {
  event: "output";
  step_id: string;
  stream: "stdout" | "stderr";
  sequence: number;
  text: string;
}

export interface ResultEvent {
  event: "result";
  step_id: string;
  exit_code: number | null;
  terminated_by: string | null;
  error_message: string | null;
  files_written: never[];
  files_deleted: never[];
  ports_opened: never[];
  started_at: string;
  ended_at: string;
}

export type StepEvent = OutputEvent | ResultEvent;

export class InvalidStepError extends Error {
  constructor(detail: string) {
    super(detail);
    this.name = "InvalidStepError";
  }
}

export class StepRefusedError extends Error {
  constructor(detail: string) {
    super(detail);
    this.name = "StepRefusedError";
  }
}

export interface Files {
  isFile(path: string): Promise<boolean>;
}

export const diskFiles: Files = {
  async isFile(path) {
    try {
      return (await stat(path)).isFile();
    } catch {
      return false;
    }
  },
};

export function parseRequest(body: unknown): StepRequest {
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    throw new InvalidStepError("the request body must be a JSON object");
  }

  const candidate = body as Record<string, unknown>;
  const scopeRoot = candidate.scope_root;
  const taskId = candidate.task_id;
  const confirmed = candidate.confirmed;

  if (typeof scopeRoot !== "string" || !win32.isAbsolute(scopeRoot)) {
    throw new InvalidStepError("scope_root must be an absolute path");
  }

  if (taskId !== undefined && taskId !== null && typeof taskId !== "string") {
    throw new InvalidStepError("task_id must be a string or null");
  }

  if (typeof confirmed !== "boolean") {
    throw new InvalidStepError("confirmed must be true or false");
  }

  const parsed = DevEnvActionSpecSchema.safeParse(candidate.action);

  if (!parsed.success) {
    const issue = parsed.error.issues[0];
    const where = issue && issue.path.length > 0 ? `action.${issue.path.join(".")}` : "action";
    throw new InvalidStepError(`${where}: ${issue?.message ?? "is not a dev-env action"}`);
  }

  return {
    scopeRoot,
    taskId: typeof taskId === "string" ? taskId : null,
    confirmed,
    action: parsed.data,
  };
}

export function resolveTarget(path: string, scopeRoot: string): string {
  return win32.resolve(scopeRoot, path);
}

export function within(target: string, scopeRoot: string): boolean {
  const root = win32.resolve(scopeRoot).replace(/\\+$/, "").toLowerCase();
  const candidate = win32.resolve(target).toLowerCase();

  return candidate === root || candidate.startsWith(`${root}\\`);
}

export function admit(request: StepRequest): string {
  const target = resolveTarget(request.action.path, request.scopeRoot);

  if (!within(target, request.scopeRoot) && !request.confirmed) {
    throw new StepRefusedError(
      `${target} is outside the project directory and the step was not confirmed`,
    );
  }

  return target;
}

function trimmed(text: string): string {
  const flat = text.trim();

  return flat.length > MAX_DETAIL_CHARS ? `${flat.slice(0, MAX_DETAIL_CHARS)}...` : flat;
}

export function failureOf(outcome: EditorRun, timeoutMs: number): string | null {
  if (outcome.timedOut) {
    return `the editor did not return within ${Math.round(timeoutMs / 1000)}s`;
  }

  if (outcome.exitCode === 0) return null;

  const detail = trimmed(outcome.stderr) || trimmed(outcome.stdout);
  const code = outcome.exitCode === null ? "without an exit code" : `with code ${outcome.exitCode}`;

  return detail ? `the editor exited ${code}: ${detail}` : `the editor exited ${code}`;
}

export function outputEvents(stepId: string, outcome: EditorRun): OutputEvent[] {
  const events: OutputEvent[] = [];
  let sequence = 0;

  for (const [stream, text] of [
    ["stdout", outcome.stdout],
    ["stderr", outcome.stderr],
  ] as const) {
    for (const line of text.split(/\r?\n/)) {
      if (line.trim()) {
        events.push({ event: "output", step_id: stepId, stream, sequence, text: line });
        sequence += 1;
      }
    }
  }

  return events;
}

function result(
  stepId: string,
  startedAt: string,
  exitCode: number | null,
  errorMessage: string | null,
): ResultEvent {
  return {
    event: "result",
    step_id: stepId,
    exit_code: exitCode,
    terminated_by: null,
    error_message: errorMessage,
    files_written: [],
    files_deleted: [],
    ports_opened: [],
    started_at: startedAt,
    ended_at: new Date().toISOString(),
  };
}

export async function perform(
  stepId: string,
  target: string,
  action: DevEnvActionSpec,
  editor: Editor,
  files: Files,
  timeoutMs: number,
): Promise<StepEvent[]> {
  const startedAt = new Date().toISOString();

  if (!(await files.isFile(target))) {
    return [
      result(stepId, startedAt, null, `${target} does not exist, so there is nothing to open`),
    ];
  }

  const outcome = await editor.open(target, action.line);

  return [
    ...outputEvents(stepId, outcome),
    result(stepId, startedAt, outcome.exitCode, failureOf(outcome, timeoutMs)),
  ];
}

export function ndjson(events: readonly StepEvent[]): string {
  return events.map((event) => `${JSON.stringify(event)}\n`).join("");
}
