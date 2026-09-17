import { useEffect, useRef } from "react";
import type { RunPhase, RunState } from "./useRun";

interface RunPanelProps {
  run: RunState;
  onStart: () => void;
  onConfirm: (stepId: string) => void;
}

const PHASE_LABEL: Record<RunPhase, string> = {
  idle: "not started",
  starting: "opening the stream",
  running: "running",
  awaiting: "waiting for you",
  finished: "finished",
  halted: "halted",
};

const PANEL =
  "flex flex-col gap-1.5 border-b border-line-subtle px-3 py-2.5 text-[12px] text-ink-muted";
const CAPTION = "text-[10px] uppercase tracking-[0.04em] text-ink-faint";
const CONTROL =
  "rounded-tag border border-line bg-surface-2 px-3 py-0.5 text-[11px] text-ink-muted transition-colors duration-[140ms] ease-ui hover:border-line-strong hover:text-ink disabled:text-ink-faint disabled:opacity-40";
const CONTINUE =
  "shrink-0 rounded-tag border border-status-wait bg-status-wait/15 px-5 py-1.5 text-[12px] font-semibold text-status-wait transition-colors duration-[140ms] ease-ui hover:bg-status-wait/25 disabled:opacity-40";

function phaseTone(phase: RunPhase, failed: boolean): string {
  if (failed || phase === "halted") {
    return "text-status-fail";
  }

  if (phase === "finished") {
    return "text-status-ok";
  }

  return phase === "awaiting" ? "text-status-wait" : "text-ink";
}

export function RunPanel({ run, onStart, onConfirm }: RunPanelProps) {
  const tailRef = useRef<HTMLDivElement>(null);
  const busy = run.phase === "starting" || run.phase === "running";
  const awaiting = run.awaiting;

  useEffect(() => {
    tailRef.current?.scrollIntoView({ block: "end" });
  }, [run.lines]);

  return (
    <div className={PANEL}>
      <div className="flex items-baseline gap-2.5">
        <span className={CAPTION}>orchestration</span>

        <span className={phaseTone(run.phase, run.failed)}>{PHASE_LABEL[run.phase]}</span>

        <span className="flex-1 tabular-nums">
          {run.tasksTotal === 0
            ? "no run yet"
            : `${run.tasksCompleted} done, ${run.tasksFailed} failed, ${run.tasksTotal} total`}
        </span>

        <span className="tabular-nums text-ink">
          {run.percentage === null ? "—" : `${run.percentage}%`}
        </span>

        <button type="button" className={CONTROL} disabled={busy} onClick={onStart}>
          {run.phase === "idle" ? "Run" : "Run again"}
        </button>
      </div>

      {run.task !== null && (
        <div className="flex items-baseline gap-2.5 rounded-tag border border-line px-2 py-1.5">
          <span className="whitespace-nowrap text-ink">{run.task.title}</span>

          <span className="flex-1 truncate">
            {run.step === null
              ? "planning"
              : run.stepsTotal === null
                ? run.step.description
                : `step ${run.step.position + 1} of ${run.stepsTotal} — ${run.step.description}`}
          </span>
        </div>
      )}

      {awaiting !== null && (
        <div className="flex items-center gap-3 rounded-tag border border-status-wait/40 bg-status-wait/10 px-3 py-2.5">
          <div className="flex flex-1 flex-col gap-0.5">
            <span className="text-[10px] uppercase tracking-[0.04em] text-status-wait">
              this step needs your approval
            </span>

            <span className="text-[13px] text-ink">{awaiting.description}</span>

            {awaiting.reason !== null && <span>{awaiting.reason}</span>}
          </div>

          <button
            type="button"
            className={CONTINUE}
            disabled={busy}
            onClick={() => {
              onConfirm(awaiting.step_id);
            }}
          >
            Continue
          </button>
        </div>
      )}

      {run.lines.length > 0 && (
        <div className="max-h-[180px] overflow-y-auto rounded-tag border border-line-subtle bg-sunken px-2.5 py-2 font-mono text-[11px] leading-relaxed">
          {run.lines.map((line) => (
            <div
              className={`break-words whitespace-pre-wrap ${line.stream === "stderr" ? "text-status-fail" : "text-ink-muted"}`}
              key={`${line.step_id}:${line.stream}:${line.step_sequence}`}
            >
              {line.text}
            </div>
          ))}
          <div ref={tailRef} />
        </div>
      )}

      {run.detail !== null && (
        <div className={run.failed ? "text-status-fail" : undefined}>{run.detail}</div>
      )}
    </div>
  );
}
