import { useCallback, useEffect, useState } from "react";
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

const POLL_MS = 3000;

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
  generation: number;
  unreachable: DownstreamName[];
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

export function useReach(httpUrl: string): ReachView {
  const [reach, setReach] = useState<Reach>("reaching");
  const [unreachable, setUnreachable] = useState<DownstreamName[]>([]);
  const [generation, setGeneration] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let timer: number | null = null;

    fetchHealth(httpUrl)
      .then((report) => {
        if (cancelled) {
          return;
        }
        setUnreachable(DOWNSTREAM_NAMES.filter((name) => report[name] !== "ok"));
        setReach("answering");
      })
      .catch(() => {
        if (cancelled) {
          return;
        }
        setUnreachable([]);
        setReach("silent");

        timer = window.setTimeout(() => {
          setGeneration((count) => count + 1);
        }, POLL_MS);
      });

    return () => {
      cancelled = true;

      if (timer !== null) {
        window.clearTimeout(timer);
      }
    };
  }, [httpUrl, generation]);

  const retry = useCallback(() => {
    setReach("reaching");
    setGeneration((count) => count + 1);
  }, []);

  return { reach, origin: originOf(httpUrl), generation, unreachable, retry };
}
