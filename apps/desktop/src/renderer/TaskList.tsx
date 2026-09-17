import { formatPercentage, type ProgressSnapshot, type Task } from "./tasks";
import type { TasksState } from "./useTasks";

interface TaskListProps {
  tasksState: TasksState;
  tasks: Task[];
  progress: ProgressSnapshot | null;
  onTransition: (taskId: string, state: string, reason: string | null) => void;
}

const SETTLED = new Set(["completed", "skipped", "ignored", "failed"]);
const DIMMED = new Set(["skipped", "ignored"]);

const PANEL =
  "flex flex-col gap-0.5 border-b border-line-subtle px-3 py-2.5 text-[12px] text-ink-muted";
const ROW = "flex items-center gap-2.5 rounded-tag border px-2 py-1.5";
const CONTROL =
  "rounded-tag border border-line bg-surface-2 px-2.5 py-0.5 text-[11px] text-ink-muted transition-colors duration-[140ms] ease-ui hover:border-line-strong hover:text-ink disabled:text-ink-faint disabled:opacity-40";

function stateTone(state: string): string {
  if (state === "completed") {
    return "text-status-ok";
  }

  if (state === "failed") {
    return "text-status-fail";
  }

  return state === "awaiting_confirmation" ? "text-status-wait" : "text-ink-muted";
}

function rowTone(state: string): string {
  const border = state === "failed" ? "border-(--line-accent)" : "border-line";

  return DIMMED.has(state) ? `${border} opacity-45` : border;
}

function depthOf(task: Task, byId: Map<string, Task>): number {
  let depth = 0;
  let parentId = task.parent_id;
  const seen = new Set<string>([task.id]);

  while (parentId !== null && !seen.has(parentId)) {
    const parent = byId.get(parentId);
    if (parent === undefined) {
      break;
    }
    seen.add(parentId);
    parentId = parent.parent_id;
    depth += 1;
  }

  return depth;
}

export function TaskList({ tasksState, tasks, progress, onTransition }: TaskListProps) {
  if (tasksState === "loading") {
    return <div className={PANEL}>loading the task tree</div>;
  }

  if (tasksState === "failed") {
    return <div className={PANEL}>task tree unavailable</div>;
  }

  if (tasks.length === 0) {
    return <div className={PANEL}>no tasks yet</div>;
  }

  const byId = new Map(tasks.map((task) => [task.id, task]));
  const ordered = [...tasks].sort((left, right) => left.position - right.position);
  const percentageFor = (taskId: string): number | null =>
    progress?.per_task.find((entry) => entry.task_id === taskId)?.percentage ?? null;

  return (
    <div className={PANEL}>
      <div className="flex items-baseline justify-between pb-1.5">
        <span className="text-[11.5px] font-medium text-ink-faint">Task tree</span>

        <span className="tabular-nums text-ink">
          {progress === null
            ? "progress unavailable"
            : `${formatPercentage(progress.overall.percentage)} overall`}
        </span>
      </div>

      {ordered.map((task) => {
        const percentage = percentageFor(task.id);
        const restorable = task.state === "skipped" || task.state === "ignored";

        return (
          <div
            className={`${ROW} ${rowTone(task.state)}`}
            key={task.id}
            style={{ marginLeft: `${depthOf(task, byId) * 16}px` }}
          >
            <span className="flex-1 truncate text-ink" title={task.description}>
              {task.title}
            </span>

            <span className={`min-w-[96px] text-[11px] ${stateTone(task.state)}`}>
              {task.state.replace("_", " ")}
            </span>

            <span className="min-w-[40px] text-right tabular-nums">
              {percentage === null ? "—" : formatPercentage(percentage)}
            </span>

            <span className="inline-flex gap-1">
              {restorable ? (
                <button
                  type="button"
                  className={CONTROL}
                  onClick={() => onTransition(task.id, "pending", null)}
                >
                  Restore
                </button>
              ) : (
                <>
                  <button
                    type="button"
                    className={CONTROL}
                    disabled={SETTLED.has(task.state)}
                    onClick={() => onTransition(task.id, "skipped", "skipped by user")}
                  >
                    Skip
                  </button>

                  <button
                    type="button"
                    className={CONTROL}
                    disabled={SETTLED.has(task.state)}
                    onClick={() => onTransition(task.id, "ignored", "ignored by user")}
                  >
                    Ignore
                  </button>
                </>
              )}
            </span>
          </div>
        );
      })}
    </div>
  );
}
