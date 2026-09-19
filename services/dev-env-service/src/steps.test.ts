import { describe, expect, it, vi } from "vitest";
import { EditorUnavailableError, type Editor, type EditorRun } from "./editor.js";
import { buildServer } from "./index.js";
import type { Files } from "./steps.js";

const SCOPE = "C:\\Users\\dev\\bison\\projects\\demo";
const FILE = `${SCOPE}\\src\\app.py`;
const HALT = {
  id: "h1",
  reason: "kill_switch",
  issued_at: "2026-09-19T10:00:00.000Z",
};

interface Setup {
  run?: EditorRun | Error;
  exists?: boolean;
}

function setup({ run = succeeded(), exists = true }: Setup = {}) {
  const open = vi.fn<Editor["open"]>(async () => {
    if (run instanceof Error) throw run;
    return run;
  });
  const isFile = vi.fn<Files["isFile"]>(async () => exists);
  const app = buildServer({ editor: { open }, files: { isFile }, timeoutMs: 30000 });

  return { app, open, isFile };
}

function succeeded(overrides: Partial<EditorRun> = {}): EditorRun {
  return { exitCode: 0, timedOut: false, stdout: "", stderr: "", ...overrides };
}

function body(overrides: Record<string, unknown> = {}) {
  return {
    scope_root: SCOPE,
    task_id: "t1",
    confirmed: false,
    action: { type: "open_in_editor", path: FILE, line: 7 },
    ...overrides,
  };
}

function lines(payload: string): Record<string, unknown>[] {
  return payload
    .split("\n")
    .filter((line) => line.trim())
    .map((line) => JSON.parse(line) as Record<string, unknown>);
}

describe("POST /steps/:stepId/run", () => {
  it("opens the file at its line and reports success as ndjson", async () => {
    const { app, open } = setup();
    const response = await app.inject({ method: "POST", url: "/steps/s1/run", payload: body() });

    expect(response.statusCode).toBe(200);
    expect(response.headers["content-type"]).toContain("application/x-ndjson");
    expect(open).toHaveBeenCalledWith(FILE, 7);

    const [result] = lines(response.payload);
    expect(result).toMatchObject({
      event: "result",
      step_id: "s1",
      exit_code: 0,
      terminated_by: null,
      error_message: null,
      files_written: [],
    });
  });

  it("resolves a relative path against the project directory", async () => {
    const { app, open } = setup();
    await app.inject({
      method: "POST",
      url: "/steps/s1/run",
      payload: body({ action: { type: "open_in_editor", path: "src\\app.py", line: null } }),
    });

    expect(open).toHaveBeenCalledWith(FILE, null);
  });

  it("streams what the editor printed before the result", async () => {
    const { app } = setup({ run: succeeded({ stderr: "warming up\r\nready\n" }) });
    const response = await app.inject({ method: "POST", url: "/steps/s1/run", payload: body() });

    expect(lines(response.payload).map((event) => event.event)).toEqual([
      "output",
      "output",
      "result",
    ]);
    expect(lines(response.payload)[1]).toMatchObject({
      stream: "stderr",
      sequence: 1,
      text: "ready",
    });
  });

  it("fails the step with the editor's own words when it exits badly", async () => {
    const { app } = setup({ run: succeeded({ exitCode: 1, stderr: "cannot open profile" }) });
    const response = await app.inject({ method: "POST", url: "/steps/s1/run", payload: body() });

    expect(lines(response.payload).at(-1)).toMatchObject({
      exit_code: 1,
      error_message: "the editor exited with code 1: cannot open profile",
    });
  });

  it("fails the step when the editor never returns", async () => {
    const { app } = setup({ run: succeeded({ exitCode: null, timedOut: true }) });
    const response = await app.inject({ method: "POST", url: "/steps/s1/run", payload: body() });

    expect(lines(response.payload).at(-1)).toMatchObject({
      error_message: "the editor did not return within 30s",
    });
  });

  it("fails the step without launching anything when the file is missing", async () => {
    const { app, open } = setup({ exists: false });
    const response = await app.inject({ method: "POST", url: "/steps/s1/run", payload: body() });

    expect(response.statusCode).toBe(200);
    expect(open).not.toHaveBeenCalled();
    expect(lines(response.payload)).toHaveLength(1);
    expect(String(lines(response.payload)[0]?.error_message)).toContain("does not exist");
  });

  it("refuses a file outside the project unless the step was confirmed", async () => {
    const outside = { type: "open_in_editor", path: "C:\\Users\\dev\\.ssh\\config", line: null };
    const { app, open } = setup();

    const refused = await app.inject({
      method: "POST",
      url: "/steps/s1/run",
      payload: body({ action: outside }),
    });

    expect(refused.statusCode).toBe(403);
    expect(refused.json()).toEqual({
      detail:
        "C:\\Users\\dev\\.ssh\\config is outside the project directory and the step was not confirmed",
    });
    expect(open).not.toHaveBeenCalled();

    const confirmed = await app.inject({
      method: "POST",
      url: "/steps/s1/run",
      payload: body({ action: outside, confirmed: true }),
    });

    expect(confirmed.statusCode).toBe(200);
    expect(open).toHaveBeenCalledOnce();
  });

  it("treats a climb out of the project as outside it", async () => {
    const { app } = setup();
    const response = await app.inject({
      method: "POST",
      url: "/steps/s1/run",
      payload: body({ action: { type: "open_in_editor", path: "..\\other\\app.py", line: 1 } }),
    });

    expect(response.statusCode).toBe(403);
  });

  it("does not mistake a sibling folder sharing a prefix for the project", async () => {
    const { app } = setup();
    const response = await app.inject({
      method: "POST",
      url: "/steps/s1/run",
      payload: body({ action: { type: "open_in_editor", path: `${SCOPE}-old\\app.py`, line: 1 } }),
    });

    expect(response.statusCode).toBe(403);
  });

  it("matches the project directory without regard to case", async () => {
    const { app } = setup();
    const response = await app.inject({
      method: "POST",
      url: "/steps/s1/run",
      payload: body({ action: { type: "open_in_editor", path: FILE.toUpperCase(), line: 1 } }),
    });

    expect(response.statusCode).toBe(200);
  });

  it.each([
    [{ type: "write_file", path: FILE, content: "" }, "action.type"],
    [{ type: "open_in_editor", path: FILE, line: 0 }, "action.line"],
    [{ type: "open_in_editor", path: "", line: 1 }, "action.path"],
    [null, "action"],
  ])("rejects an action that is not a dev-env action %#", async (action, where) => {
    const { app, open } = setup();
    const response = await app.inject({
      method: "POST",
      url: "/steps/s1/run",
      payload: body({ action }),
    });

    expect(response.statusCode).toBe(422);
    expect(String(response.json().detail).startsWith(`${where}:`)).toBe(true);
    expect(open).not.toHaveBeenCalled();
  });

  it.each([
    [{ scope_root: "projects\\demo" }, "scope_root must be an absolute path"],
    [{ confirmed: "yes" }, "confirmed must be true or false"],
    [{ task_id: 4 }, "task_id must be a string or null"],
  ])("rejects a malformed request %#", async (overrides, detail) => {
    const { app } = setup();
    const response = await app.inject({
      method: "POST",
      url: "/steps/s1/run",
      payload: body(overrides),
    });

    expect(response.statusCode).toBe(422);
    expect(response.json()).toEqual({ detail });
  });

  it("answers 503 and says where it looked when VS Code is not installed", async () => {
    const { app } = setup({
      run: new EditorUnavailableError(["C:\\Program Files\\Microsoft VS Code"]),
    });
    const response = await app.inject({ method: "POST", url: "/steps/s1/run", payload: body() });

    expect(response.statusCode).toBe(503);
    expect(response.json()).toEqual({
      detail: "VS Code was not found in C:\\Program Files\\Microsoft VS Code",
    });
  });

  it("accepts no work while halted and accepts it again after resume", async () => {
    const { app, open } = setup();

    await app.inject({ method: "POST", url: "/halt", payload: HALT });
    const halted = await app.inject({ method: "POST", url: "/steps/s1/run", payload: body() });

    expect(halted.statusCode).toBe(409);
    expect(halted.json()).toEqual({
      detail: "dev-env-service is halted by kill_switch and accepts no new work",
    });
    expect(open).not.toHaveBeenCalled();

    await app.inject({ method: "POST", url: "/halt/resume", payload: { actor: "user" } });
    const resumed = await app.inject({ method: "POST", url: "/steps/s1/run", payload: body() });

    expect(resumed.statusCode).toBe(200);
  });
});
