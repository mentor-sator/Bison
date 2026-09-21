import { beforeEach, describe, expect, it, vi } from "vitest";
import { bootstrapHealthy } from "./bootstrap-client.js";
import { brokerHealthy } from "./broker-client.js";
import { readState } from "./halt.js";
import { buildServer } from "./index.js";
import {
  InspectorError,
  inspectProject,
  inspectTask,
  inspectorHealthy,
} from "./inspector-client.js";
import { mediatorHealthy } from "./mediator-client.js";
import {
  ProjectError,
  fetchPlan,
  listCriteria,
  moveTask,
  projectHealthy,
} from "./project-client.js";
import { taskStoreHealthy } from "./task-store-client.js";

vi.mock("./bootstrap-client.js", async (importActual) => ({
  ...(await importActual<typeof import("./bootstrap-client.js")>()),
  bootstrapHealthy: vi.fn(),
}));

vi.mock("./broker-client.js", async (importActual) => ({
  ...(await importActual<typeof import("./broker-client.js")>()),
  brokerHealthy: vi.fn(),
}));

vi.mock("./mediator-client.js", async (importActual) => ({
  ...(await importActual<typeof import("./mediator-client.js")>()),
  mediatorHealthy: vi.fn(),
}));

vi.mock("./task-store-client.js", async (importActual) => ({
  ...(await importActual<typeof import("./task-store-client.js")>()),
  taskStoreHealthy: vi.fn(),
}));

vi.mock("./project-client.js", async (importActual) => ({
  ...(await importActual<typeof import("./project-client.js")>()),
  projectHealthy: vi.fn(),
  listCriteria: vi.fn(),
  fetchPlan: vi.fn(),
  moveTask: vi.fn(),
}));

vi.mock("./inspector-client.js", async (importActual) => ({
  ...(await importActual<typeof import("./inspector-client.js")>()),
  inspectorHealthy: vi.fn(),
  inspectProject: vi.fn(),
  inspectTask: vi.fn(),
}));

vi.mock("./halt.js", async (importActual) => ({
  ...(await importActual<typeof import("./halt.js")>()),
  readState: vi.fn(),
}));

const criterion = {
  id: "c1",
  task_id: "t1",
  statement: "the port answers",
  check_kind: "deterministic",
  check_spec: null,
  weight: 1,
  status: "verified",
  status_reason: null,
  verified_by: "inspector",
};

async function withServer<T>(run: (app: ReturnType<typeof buildServer>) => Promise<T>): Promise<T> {
  const app = buildServer();

  try {
    await app.ready();
    return await run(app);
  } finally {
    await app.close();
  }
}

beforeEach(() => {
  vi.mocked(taskStoreHealthy).mockResolvedValue(true);
  vi.mocked(bootstrapHealthy).mockResolvedValue(false);
  vi.mocked(brokerHealthy).mockResolvedValue(false);
  vi.mocked(projectHealthy).mockResolvedValue(true);
  vi.mocked(mediatorHealthy).mockResolvedValue(true);
  vi.mocked(inspectorHealthy).mockResolvedValue(false);
});

describe("GET /health", () => {
  it("reports each downstream separately", async () => {
    const body = await withServer(async (app) => {
      const response = await app.inject({ method: "GET", url: "/health" });
      return response.json();
    });

    expect(body).toMatchObject({
      status: "ok",
      task_store: "ok",
      bootstrap: "unreachable",
      model_broker: "unreachable",
      project_service: "ok",
      mediator: "ok",
      inspector: "unreachable",
    });
  });
});

describe("GET /tasks/:taskId/criteria", () => {
  it("returns what project-service returned", async () => {
    vi.mocked(listCriteria).mockResolvedValue([criterion]);

    const response = await withServer((app) =>
      app.inject({ method: "GET", url: "/tasks/t1/criteria" }),
    );

    expect(response.statusCode).toBe(200);
    expect(response.json()).toEqual([criterion]);
    expect(vi.mocked(listCriteria)).toHaveBeenCalledWith("t1");
  });

  it("keeps a refusal's status and detail", async () => {
    vi.mocked(listCriteria).mockRejectedValue(new ProjectError(404, "task not found"));

    const response = await withServer((app) =>
      app.inject({ method: "GET", url: "/tasks/missing/criteria" }),
    );

    expect(response.statusCode).toBe(404);
    expect(response.json()).toEqual({ error: "task not found" });
  });

  it("answers 503 when project-service is unreachable", async () => {
    vi.mocked(listCriteria).mockRejectedValue(new Error("connect ECONNREFUSED"));

    const response = await withServer((app) =>
      app.inject({ method: "GET", url: "/tasks/t1/criteria" }),
    );

    expect(response.statusCode).toBe(503);
    expect(response.json()).toEqual({ error: "project-service unavailable" });
  });
});

describe("GET /tasks/:taskId/plan", () => {
  const plan = {
    id: "p1",
    task_id: "t1",
    intent: "make the port answer",
    rationale: "the criterion needs a running service",
    steps_total: 1,
    gated_count: 1,
    created_at: "2026-09-18T10:00:00Z",
    steps: [
      {
        id: "s1",
        plan_id: "p1",
        position: 1,
        description: "start the service",
        service: "dev-env-service",
        requires_confirmation: true,
        confirmation_reason: "it writes outside the scope root",
        on_failure: "halt",
        reversible: false,
        criterion_refs: ["c1"],
        state: "pending",
      },
    ],
  };

  it("returns the plan project-service holds", async () => {
    vi.mocked(fetchPlan).mockResolvedValue(plan);

    const response = await withServer((app) =>
      app.inject({ method: "GET", url: "/tasks/t1/plan" }),
    );

    expect(response.statusCode).toBe(200);
    expect(response.json()).toEqual(plan);
  });

  it("says null rather than inventing an empty plan", async () => {
    vi.mocked(fetchPlan).mockResolvedValue(null);

    const response = await withServer((app) =>
      app.inject({ method: "GET", url: "/tasks/t1/plan" }),
    );

    expect(response.statusCode).toBe(200);
    expect(response.json()).toBeNull();
  });

  it("answers 503 when project-service is unreachable", async () => {
    vi.mocked(fetchPlan).mockRejectedValue(new Error("connect ECONNREFUSED"));

    const response = await withServer((app) =>
      app.inject({ method: "GET", url: "/tasks/t1/plan" }),
    );

    expect(response.statusCode).toBe(503);
    expect(response.json()).toEqual({ error: "project-service unavailable" });
  });
});

describe("POST inspections", () => {
  const report = {
    project_id: "p1",
    workspace: "C:\\workspace",
    inspected_at: "2026-09-21T10:00:00+00:00",
    verified: 1,
    failed: 0,
    inconclusive: 1,
    changed: 1,
    results: [
      {
        criterion_id: "c1",
        task_id: "t1",
        statement: "main.py exists",
        check_kind: "deterministic",
        verdict: "verified",
        reasoning: "the file is there",
        evidence: [{ kind: "file_hash", excerpt: "sha256 a1b2" }],
        status_before: "unverified",
        status_after: "verified",
      },
      {
        criterion_id: "c2",
        task_id: "t1",
        statement: "port 9101 answers",
        check_kind: "deterministic",
        verdict: "inconclusive",
        reasoning: "nothing answered yet",
        evidence: [],
        status_before: "unverified",
        status_after: "unverified",
      },
    ],
  };

  it("inspects a whole project and returns every verdict", async () => {
    vi.mocked(inspectProject).mockResolvedValue(report);

    const response = await withServer((app) =>
      app.inject({ method: "POST", url: "/projects/p1/inspect" }),
    );

    expect(response.statusCode).toBe(200);
    expect(response.json()).toEqual(report);
    expect(vi.mocked(inspectProject)).toHaveBeenCalledWith("p1");
  });

  it("inspects one task of a project", async () => {
    vi.mocked(inspectTask).mockResolvedValue(report);

    const response = await withServer((app) =>
      app.inject({ method: "POST", url: "/projects/p1/tasks/t1/inspect" }),
    );

    expect(response.statusCode).toBe(200);
    expect(vi.mocked(inspectTask)).toHaveBeenCalledWith("p1", "t1");
  });

  it("keeps a refusal's status and detail", async () => {
    vi.mocked(inspectTask).mockRejectedValue(new InspectorError(404, "t9"));

    const response = await withServer((app) =>
      app.inject({ method: "POST", url: "/projects/p1/tasks/t9/inspect" }),
    );

    expect(response.statusCode).toBe(404);
    expect(response.json()).toEqual({ error: "t9" });
  });

  it("answers 503 when the inspector is unreachable", async () => {
    vi.mocked(inspectProject).mockRejectedValue(new Error("connect ECONNREFUSED"));

    const response = await withServer((app) =>
      app.inject({ method: "POST", url: "/projects/p1/inspect" }),
    );

    expect(response.statusCode).toBe(503);
    expect(response.json()).toEqual({ error: "inspector-service unavailable" });
  });
});

describe("request validation", () => {
  it("refuses a task with no title", async () => {
    const response = await withServer((app) =>
      app.inject({ method: "POST", url: "/projects/p1/tasks", payload: { kind: "code" } }),
    );

    expect(response.statusCode).toBe(400);
    expect(response.json()).toEqual({ error: "title is required" });
  });

  it("refuses a task with no kind", async () => {
    const response = await withServer((app) =>
      app.inject({ method: "POST", url: "/projects/p1/tasks", payload: { title: "Alpha" } }),
    );

    expect(response.statusCode).toBe(400);
    expect(response.json()).toEqual({ error: "kind is required" });
  });

  it("refuses a transition with no state", async () => {
    const response = await withServer((app) =>
      app.inject({ method: "POST", url: "/tasks/t1/state", payload: { reason: "because" } }),
    );

    expect(response.statusCode).toBe(400);
    expect(response.json()).toEqual({ error: "state is required" });
  });

  it("refuses an unknown halt reason", async () => {
    const response = await withServer((app) =>
      app.inject({ method: "POST", url: "/halt", payload: { reason: "because I said so" } }),
    );

    expect(response.statusCode).toBe(422);
    expect(response.json()).toEqual({ error: 'unknown halt reason "because I said so"' });
  });

  it("defaults the actor when a transition omits it", async () => {
    vi.mocked(moveTask).mockResolvedValue({ id: "t1" } as never);

    await withServer((app) =>
      app.inject({ method: "POST", url: "/tasks/t1/state", payload: { state: "skipped" } }),
    );

    expect(vi.mocked(moveTask)).toHaveBeenCalledWith("t1", {
      state: "skipped",
      reason: null,
      actor: "user",
    });
  });
});

describe("GET /halt/state", () => {
  it("passes the report through untouched", async () => {
    const report = {
      halted: false,
      halted_count: 0,
      reachable_count: 4,
      silent_count: 0,
      recipients: [],
    };

    vi.mocked(readState).mockResolvedValue(report as never);

    const response = await withServer((app) => app.inject({ method: "GET", url: "/halt/state" }));

    expect(response.json()).toEqual(report);
  });
});
