import { useEffect, useRef, useState } from "react";
import {
  pullModel,
  searchCatalog,
  type CatalogEntry,
  type PullProgress,
  type Role,
} from "./broker";
import { notice } from "./ui";

const SEARCH_LIMIT = 40;
const DEBOUNCE_MS = 200;
const BYTES_PER_GB = 1024 ** 3;

const BACKDROP = "fixed inset-0 flex items-center justify-center bg-sunken/80";
const PANEL =
  "flex max-h-[70vh] w-[min(640px,90vw)] flex-col gap-3 rounded-overlay border border-line bg-surface-2 p-5 shadow-overlay";
const SEARCH =
  "rounded-control border border-line bg-surface-3 px-3.5 py-2.5 text-[14px] text-ink outline-none transition-colors duration-[140ms] ease-ui focus:border-red-500";
const ENTRY =
  "grid grid-cols-[1fr_auto_auto] items-center gap-2 rounded-tag border px-3 py-2 transition-colors duration-[140ms] ease-ui hover:bg-surface-3";
const SMALL =
  "rounded-tag border border-line px-2.5 py-1 text-[11px] text-ink-muted transition-colors duration-[140ms] ease-ui";
const CAPTION = "text-[11px] text-ink-faint";

interface ModelPickerProps {
  httpUrl: string;
  role: Role;
  boundModelId: string | null;
  installed: Set<string>;
  onSelect: (modelId: string) => Promise<void>;
  onPulled: () => Promise<void>;
  onClose: () => void;
}

function describeProgress(progress: PullProgress): string {
  if (progress.completedBytes === null || progress.totalBytes === null) {
    return progress.status;
  }

  const done = (progress.completedBytes / BYTES_PER_GB).toFixed(2);
  const total = (progress.totalBytes / BYTES_PER_GB).toFixed(2);

  return `${progress.status} · ${done} / ${total} GB`;
}

function percentOf(progress: PullProgress): number {
  if (
    progress.completedBytes === null ||
    progress.totalBytes === null ||
    progress.totalBytes === 0
  ) {
    return 0;
  }

  return Math.min(100, (progress.completedBytes / progress.totalBytes) * 100);
}

export function ModelPicker({
  httpUrl,
  role,
  boundModelId,
  installed,
  onSelect,
  onPulled,
  onClose,
}: ModelPickerProps) {
  const [query, setQuery] = useState("");
  const [entries, setEntries] = useState<CatalogEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [binding, setBinding] = useState<string | null>(null);
  const [pullingId, setPullingId] = useState<string | null>(null);
  const [progress, setProgress] = useState<PullProgress | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const locked = binding !== null || pullingId !== null;

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    const timer = window.setTimeout(() => {
      searchCatalog(httpUrl, query, SEARCH_LIMIT)
        .then((found) => {
          if (!cancelled) {
            setEntries(found);
          }
        })
        .catch((reason: unknown) => {
          if (!cancelled) {
            setError(reason instanceof Error ? reason.message : String(reason));
          }
        });
    }, DEBOUNCE_MS);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [httpUrl, query]);

  const choose = (modelId: string): void => {
    setBinding(modelId);
    setError(null);

    void onSelect(modelId)
      .then(() => {
        onClose();
      })
      .catch((reason: unknown) => {
        setBinding(null);
        setError(reason instanceof Error ? reason.message : String(reason));
      });
  };

  const download = (modelId: string): void => {
    const controller = new AbortController();
    abortRef.current = controller;

    setPullingId(modelId);
    setProgress(null);
    setError(null);

    void pullModel(httpUrl, modelId, setProgress, controller.signal)
      .then(async () => {
        await onPulled();
        setPullingId(null);
        setProgress(null);
      })
      .catch((reason: unknown) => {
        setPullingId(null);
        setProgress(null);

        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      });
  };

  const dismiss = (): void => {
    abortRef.current?.abort();
    onClose();
  };

  return (
    <div className={BACKDROP} onClick={dismiss}>
      <div className={PANEL} onClick={(clickEvent) => clickEvent.stopPropagation()}>
        <div className="flex items-center">
          <span className="text-[11px] uppercase tracking-[0.06em] text-ink-muted">
            bind {role}
          </span>

          <button type="button" className={`${SMALL} ml-auto hover:text-ink`} onClick={dismiss}>
            {pullingId !== null ? "cancel" : "close"}
          </button>
        </div>

        <input
          className={SEARCH}
          value={query}
          onChange={(changeEvent) => setQuery(changeEvent.target.value)}
          placeholder="search the catalog"
          autoFocus
        />

        {error !== null && <div className={notice.error}>{error}</div>}

        <div className="flex flex-col gap-1 overflow-y-auto">
          {entries.length === 0 && (
            <div className="p-3 text-[12px] text-ink-faint">nothing matches</div>
          )}

          {entries.map((entry) => {
            const onDisk = installed.has(entry.model_id);
            const pullable = entry.locality === "local" && !onDisk;
            const active = pullingId === entry.model_id;

            return (
              <div
                className={`${ENTRY} ${entry.model_id === boundModelId ? "border-red-500" : "border-transparent"}`}
                key={entry.model_id}
              >
                <button
                  type="button"
                  className="flex flex-col gap-0.5 py-0.5 text-left disabled:opacity-50"
                  disabled={locked}
                  onClick={() => choose(entry.model_id)}
                >
                  <span className="text-[13px] text-ink">{entry.model_id}</span>
                  <span className={CAPTION}>{entry.capability_tags.join(" · ")}</span>
                </button>

                <span className={CAPTION}>
                  {entry.locality === "local"
                    ? `${entry.size_gb ?? "?"} GB${onDisk ? " · on disk" : ""}`
                    : entry.provider}
                </span>

                {pullable && (
                  <button
                    type="button"
                    className={`${SMALL} hover:border-red-500 hover:text-red-300 disabled:opacity-40`}
                    disabled={locked}
                    onClick={() => download(entry.model_id)}
                  >
                    download
                  </button>
                )}

                {active && progress !== null && (
                  <div className="col-span-full flex items-center gap-2.5">
                    <div className="h-1 flex-1 overflow-hidden rounded-[2px] bg-line">
                      <span
                        className="block h-full bg-red-500 transition-[width] duration-200 ease-linear"
                        style={{ width: `${percentOf(progress)}%` }}
                      />
                    </div>

                    <span className={`${CAPTION} tabular-nums`}>{describeProgress(progress)}</span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
