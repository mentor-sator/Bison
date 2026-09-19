import { useEffect, useState } from "react";
import {
  criterionNote,
  fetchCriteria,
  fetchPlan,
  planCaption,
  type Criterion,
  type Plan,
} from "./tasks";
import { mark } from "./ui";

interface TaskDetailProps {
  httpUrl: string;
  taskId: string;
}

type DetailState = "loading" | "ready" | "failed";

const PANEL = "flex flex-col gap-1.5 rounded-tag border border-line bg-sunken px-2.5 py-2";
const ROW = "flex items-baseline gap-2";
const NOTE = "pl-4 text-[11px] text-ink-muted";
const HEADING = "text-[11.5px] font-medium text-ink-faint";

const STATUS_TONE: Record<string, { dot: string; word: string }> = {
  verified: { dot: "bg-status-ok", word: "text-status-ok" },
  failed: { dot: "bg-status-fail", word: "text-status-fail" },
  unverified: { dot: "bg-status-idle", word: "text-ink-muted" },
  ignored: { dot: "bg-status-idle", word: "text-ink-muted" },
  skipped: { dot: "bg-status-idle", word: "text-ink-muted" },
  inconclusive: { dot: "bg-status-wait", word: "text-status-wait" },
  succeeded: { dot: "bg-status-ok", word: "text-status-ok" },
  running: { dot: "bg-status-wait", word: "text-status-wait" },
  awaiting_confirmation: { dot: "bg-status-wait", word: "text-status-wait" },
  aborted: { dot: "bg-status-fail", word: "text-status-fail" },
  pending: { dot: "bg-status-idle", word: "text-ink-muted" },
  never_attempted: { dot: "bg-status-idle", word: "text-ink-muted" },
};

const UNKNOWN_TONE = { dot: "bg-status-idle", word: "text-ink-muted" };

function statusTone(status: string): { dot: string; word: string } {
  return STATUS_TONE[status] ?? UNKNOWN_TONE;
}

export function TaskDetail({ httpUrl, taskId }: TaskDetailProps) {
  const [detailState, setDetailState] = useState<DetailState>("loading");
  const [criteria, setCriteria] = useState<Criterion[]>([]);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [planFailed, setPlanFailed] = useState(false);
  const [planOpen, setPlanOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;

    setDetailState("loading");
    setPlanFailed(false);
    setPlanOpen(false);

    fetchCriteria(httpUrl, taskId)
      .then((loaded) => {
        if (cancelled) {
          return;
        }
        setCriteria(loaded);
        setDetailState("ready");
      })
      .catch(() => {
        if (!cancelled) {
          setDetailState("failed");
        }
      });

    fetchPlan(httpUrl, taskId)
      .then((loaded) => {
        if (!cancelled) {
          setPlan(loaded);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setPlan(null);
          setPlanFailed(true);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [httpUrl, taskId]);

  if (detailState === "loading") {
    return <div className={PANEL}>reading the criteria</div>;
  }

  if (detailState === "failed") {
    return <div className={PANEL}>the criteria could not be read</div>;
  }

  return (
    <div className={PANEL}>
      {criteria.length === 0 ? (
        <p className="text-ink-muted">this task carries no criteria</p>
      ) : (
        criteria.map((criterion) => {
          const tone = statusTone(criterion.status);
          const note = criterionNote(criterion);

          return (
            <div className="flex flex-col gap-0.5" key={criterion.id}>
              <div className={ROW}>
                <span className={`${mark.dot} ${tone.dot} translate-y-[3px]`} />

                <span className="flex-1 text-ink">{criterion.statement}</span>

                <span className="shrink-0 text-[11px]">{criterion.check_kind}</span>

                <span className={`w-14 shrink-0 text-right text-[11px] ${tone.word}`}>
                  {criterion.status}
                </span>
              </div>

              {note !== null && <p className={NOTE}>{note}</p>}
            </div>
          );
        })
      )}

      <div className="mt-1 flex items-baseline gap-2 border-t border-line-subtle pt-2">
        <span className={HEADING}>Plan</span>

        {plan === null ? (
          <span className="text-[11px] text-ink-muted">
            {planFailed ? "the plan could not be read" : "no plan yet"}
          </span>
        ) : (
          <button
            type="button"
            className="text-[11px] text-ink-muted transition-colors duration-[140ms] ease-ui hover:text-ink"
            onClick={() => setPlanOpen(!planOpen)}
          >
            {planCaption(plan)}
            {planOpen ? " — hide" : " — show"}
          </button>
        )}
      </div>

      {plan !== null && planOpen && (
        <>
          <p className={NOTE}>{plan.intent}</p>

          {plan.steps.map((step) => {
            const tone = statusTone(step.state);

            return (
              <div className="flex flex-col gap-0.5" key={step.id}>
                <div className={ROW}>
                  <span className={`${mark.dot} ${tone.dot} translate-y-[3px]`} />

                  <span className="w-4 shrink-0 text-[11px] text-ink-faint tabular-nums">
                    {step.position}
                  </span>

                  <span className="flex-1 text-ink">{step.description}</span>

                  <span className="shrink-0 text-[11px]">{step.service}</span>

                  <span className={`w-14 shrink-0 text-right text-[11px] ${tone.word}`}>
                    {step.state.replace("_", " ")}
                  </span>
                </div>

                {step.requires_confirmation && (
                  <p className={NOTE}>
                    {step.confirmation_reason === null
                      ? "waits for your confirmation"
                      : `waits for your confirmation: ${step.confirmation_reason}`}
                  </p>
                )}
              </div>
            );
          })}
        </>
      )}
    </div>
  );
}
