import { beforeEach, describe, expect, it, vi } from "vitest";
import { request } from "undici";
import { buildTree, mediatorHealthy, openRun } from "./mediator-client.js";

vi.mock("undici", () => ({ request: vi.fn() }));

function answer(statusCode: number, body: unknown) {
  return {
    statusCode,
    body: { text: async () => JSON.stringify(body) },
  } as unknown as Awaited<ReturnType<typeof request>>;
}

function optionsOfCall(index: number): Record<string, unknown> {
  const call = vi.mocked(request).mock.calls[index];
  return (call?.[1] ?? {}) as Record<string, unknown>;
}

beforeEach(() => {
  vi.mocked(request).mockReset();
});

describe("mediator timeouts", () => {
  it("waits for as long as a tree build takes", async () => {
    vi.mocked(request).mockResolvedValue(answer(200, { tasks: [] }));

    await buildTree("p1", null);

    expect(optionsOfCall(0)).toMatchObject({
      method: "POST",
      headersTimeout: 0,
      bodyTimeout: 0,
    });
  });

  it("waits for as long as a run stream stays open", async () => {
    vi.mocked(request).mockResolvedValue(answer(200, {}));

    await openRun("p1", "r1");

    expect(optionsOfCall(0)).toMatchObject({ headersTimeout: 0, bodyTimeout: 0 });
  });

  it("keeps the default timeouts on a health check", async () => {
    vi.mocked(request).mockResolvedValue(answer(200, { status: "ok" }));

    await mediatorHealthy();

    expect(optionsOfCall(0)).toEqual({ method: "GET" });
  });

  it("still reports a refused tree with its status", async () => {
    vi.mocked(request).mockResolvedValue(answer(502, { detail: "tree_rejected" }));

    await expect(buildTree("p1", null)).rejects.toMatchObject({
      status: 502,
      detail: "tree_rejected",
    });
  });
});
