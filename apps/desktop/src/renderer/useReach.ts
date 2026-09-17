import { useCallback, useEffect, useRef, useState } from "react";
import { request } from "./http";

export const DOWNSTREAM_NAMES = [
  "task_store",
  "bootstrap",
  "model_broker",
  "project_service",
  "mediator",
] as const;

export type DownstreamName = (typeof DOWNSTREAM_NAMES)[number];

export type Reach = "reaching" | "answering" | "silent";

const GATEWAY = "gateway";
const ANSWERING_POLL_MS = 10_000;
const SILENT_POLL_FLOOR_MS = 3_000;
const SILENT_POLL_CEILING_MS = 30_000;

export interface HealthReport {
  status: string;
  task_store: string;
  bootstrap: string;
  model_broker: string;
  project_service: string;
  mediator: string;
}

export interface ReachView {
  reach: Reach;
  origin: string;
  unreachable: DownstreamName[];
  recovery: number;
  retry: () => void;
}

const isHealthReport = (value: unknown): value is HealthReport => {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const candidate = value as Record<string, unknown>;

  return (
    typeof candidate["status"] === "string" &&
    DOWNSTREAM_NAMES.every((name) => typeof candidate[name] === "string")
  );
};

export function originOf(url: string): string {
  try {
    return new URL(url).origin;
  } catch {
    return url;
  }
}

export async function fetchHealth(baseUrl: string): Promise<HealthReport> {
  const response = await request(`${baseUrl}/health`);

  if (!response.ok) {
    throw new Error(`health request failed: ${response.status}`);
  }

  const parsed: unknown = await response.json();

  if (!isHealthReport(parsed)) {
    throw new Error("health response did not match the expected shape");
  }

  return parsed;
}

export function silentDelay(failures: number): number {
  return Math.min(SILENT_POLL_FLOOR_MS * 2 ** Math.max(failures - 1, 0), SILENT_POLL_CEILING_MS);
}

function sameNames(left: readonly DownstreamName[], right: readonly DownstreamName[]): boolean {
  return left.length === right.length && left.every((name, index) => name === right[index]);
}

export function useReach(httpUrl: string): ReachView {
  const [reach, setReach] = useState<Reach>("reaching");
  const [unreachable, setUnreachable] = useState<DownstreamName[]>([]);
  const [recovery, setRecovery] = useState(0);
  const [read, setRead] = useState(0);
  const failures = useRef(0);
  const silenced = useRef<ReadonlySet<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    let timer: number | null = null;

    const schedule = (delay: number) => {
      timer = window.setTimeout(() => {
        setRead((count) => count + 1);
      }, delay);
    };

    fetchHealth(httpUrl)
      .then((report) => {
        if (cancelled) {
          return;
        }

        const silent = DOWNSTREAM_NAMES.filter((name) => report[name] !== "ok");
        const stillSilent = new Set<string>(silent);
        const recovered = [...silenced.current].some((name) => !stillSilent.has(name));

        silenced.current = stillSilent;
        failures.current = 0;
        setUnreachable((current) => (sameNames(current, silent) ? current : silent));
        setReach("answering");

        if (recovered) {
          setRecovery((count) => count + 1);
        }

        schedule(ANSWERING_POLL_MS);
      })
      .catch(() => {
        if (cancelled) {
          return;
        }

        failures.current += 1;
        silenced.current = new Set([GATEWAY]);
        setUnreachable((current) => (current.length === 0 ? current : []));
        setReach("silent");
        schedule(silentDelay(failures.current));
      });

    return () => {
      cancelled = true;

      if (timer !== null) {
        window.clearTimeout(timer);
      }
    };
  }, [httpUrl, read]);

  const retry = useCallback(() => {
    failures.current = 0;
    setReach("reaching");
    setRead((count) => count + 1);
  }, []);

  return { reach, origin: originOf(httpUrl), unreachable, recovery, retry };
}
