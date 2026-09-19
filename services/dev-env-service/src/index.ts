import Fastify, { type FastifyInstance } from "fastify";
import { EditorUnavailableError, vsCode, type Editor } from "./editor.js";
import { HaltState, HaltedError, parseSignal, type Boundary } from "./halt.js";
import {
  InvalidStepError,
  StepRefusedError,
  admit,
  diskFiles,
  ndjson,
  parseRequest,
  perform,
  type Files,
} from "./steps.js";

export const SERVICE_NAME = "dev-env-service";

const BOUNDARY: Boundary = "between_actions";
const NDJSON = "application/x-ndjson";

function intFromEnv(name: string, fallback: number): number {
  const raw = process.env[name];
  if (raw === undefined || raw === "") return fallback;

  const parsed = Number.parseInt(raw, 10);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error(`${name} must be a positive integer, received "${raw}"`);
  }

  return parsed;
}

export const config = {
  port: intFromEnv("BISON_DEV_ENV_PORT", 9000),
  host: process.env.BISON_DEV_ENV_HOST ?? "127.0.0.1",
  logLevel: process.env.BISON_LOG_LEVEL ?? "info",
  editorTimeoutMs: intFromEnv("BISON_DEV_ENV_EDITOR_TIMEOUT_MS", 30000),
} as const;

export interface Ports {
  editor: Editor;
  files: Files;
  timeoutMs: number;
}

export function defaultPorts(): Ports {
  return {
    editor: vsCode(process.env, config.editorTimeoutMs),
    files: diskFiles,
    timeoutMs: config.editorTimeoutMs,
  };
}

export function buildServer(ports: Ports = defaultPorts()): FastifyInstance {
  const app = Fastify({ logger: { level: config.logLevel } });
  const haltState = new HaltState(SERVICE_NAME, BOUNDARY);

  app.get("/health", async () => ({
    service: SERVICE_NAME,
    status: haltState.halted ? "halted" : "ok",
    boundary: BOUNDARY,
    halted: haltState.halted,
  }));

  app.post("/halt", async (request, reply) => {
    let signal;

    try {
      signal = parseSignal(request.body);
    } catch (error) {
      return reply.status(422).send({ error: (error as Error).message });
    }

    const acknowledgement = haltState.accept(signal);

    app.log.warn({ halt: signal.id, reason: signal.reason, boundary: BOUNDARY }, "HALT accepted");

    return acknowledgement;
  });

  app.get("/halt/state", async () => haltState.status());

  app.post("/halt/resume", async (request, reply) => {
    const actor = (request.body as { actor?: unknown } | null)?.actor;

    if (typeof actor !== "string" || actor.length === 0) {
      return reply.status(422).send({ error: "resume requires a non-empty actor" });
    }

    return haltState.resume(actor);
  });

  app.post<{ Params: { stepId: string } }>("/steps/:stepId/run", async (request, reply) => {
    const { stepId } = request.params;

    try {
      haltState.guard();

      const step = parseRequest(request.body);
      const target = admit(step);
      const events = await perform(
        stepId,
        target,
        step.action,
        ports.editor,
        ports.files,
        ports.timeoutMs,
      );

      app.log.info({ step: stepId, target, task: step.taskId }, "dev-env step finished");

      return reply.type(NDJSON).send(ndjson(events));
    } catch (error) {
      if (error instanceof HaltedError) {
        return reply.status(409).send({ detail: error.message });
      }

      if (error instanceof StepRefusedError) {
        return reply.status(403).send({ detail: error.message });
      }

      if (error instanceof InvalidStepError) {
        return reply.status(422).send({ detail: error.message });
      }

      if (error instanceof EditorUnavailableError) {
        return reply.status(503).send({ detail: error.message });
      }

      throw error;
    }
  });

  return app;
}

async function start(): Promise<void> {
  const app = buildServer();

  try {
    await app.listen({ port: config.port, host: config.host });
  } catch (error) {
    app.log.error(error);
    process.exit(1);
  }
}

if (process.argv[1]?.endsWith("index.js")) {
  await start();
}
