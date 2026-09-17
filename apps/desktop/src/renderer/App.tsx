import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { ActivityBar } from "./ActivityBar";
import { AddTask } from "./AddTask";
import { CapabilityBar } from "./CapabilityBar";
import { HaltBanner } from "./HaltBanner";
import { ModelPicker } from "./ModelPicker";
import { ProjectBar } from "./ProjectBar";
import { ReachBanner } from "./ReachBanner";
import { RoleBar } from "./RoleBar";
import { RunPanel } from "./RunPanel";
import { ServiceBar } from "./ServiceBar";
import { silentServices } from "./halt";
import { Shell } from "./Shell";
import { TaskList } from "./TaskList";
import markUrl from "./brand/mark-128.png";
import type { Role } from "./broker";
import type { TaskDraft } from "./tasks";
import { button, mark, notice } from "./ui";
import type { HaltView } from "./useGateway";
import { useBindings } from "./useBindings";
import { useCapabilities } from "./useCapabilities";
import { useGateway } from "./useGateway";
import { useProjects } from "./useProjects";
import { useReach } from "./useReach";
import { useRun } from "./useRun";
import { useTasks } from "./useTasks";

const MESSAGE =
  "flex max-w-[720px] flex-col gap-1 rounded-control border border-line bg-surface-1 px-4 py-3";
const COMPOSER =
  "flex-1 rounded-control border border-line bg-surface-2 px-3.5 py-2.5 text-[14px] text-ink outline-none transition-colors duration-[140ms] ease-ui placeholder:text-ink-faint focus:border-red-500 disabled:text-ink-faint";

function blockedReason(mediatorSilent: boolean, halt: HaltView): string | null {
  if (mediatorSilent) {
    return "the mediator is not answering";
  }

  if (halt.halted) {
    return "work is halted";
  }

  if (halt.report === null) {
    return "the halt state has not been read";
  }

  const silent = silentServices(halt.report);

  return silent.length === 0 ? null : `a halt could not reach ${silent.join(", ")}`;
}

function connectionTone(state: string): string {
  if (state === "open") {
    return "bg-status-ok";
  }

  if (state === "connecting") {
    return "bg-status-wait";
  }

  return state === "closed" ? "bg-status-fail" : "bg-status-idle";
}

export function App() {
  const { state, historyState, messages, activity, halt, send, reloadHistory } = useGateway(
    window.bison.gatewayWebSocketUrl,
    window.bison.gatewayHttpUrl,
  );
  const reach = useReach(window.bison.gatewayHttpUrl);
  const capabilities = useCapabilities(window.bison.gatewayHttpUrl);
  const { manifestState, manifest } = capabilities;
  const projects = useProjects(window.bison.gatewayHttpUrl);
  const projectId = projects.current?.id ?? null;
  const {
    bindingsState,
    bindings,
    installed,
    rebind,
    refreshInstalled,
    reload: reloadBindings,
  } = useBindings(window.bison.gatewayHttpUrl, projectId);
  const { tasksState, tasks, progress, refresh, addTask, transition } = useTasks(
    window.bison.gatewayHttpUrl,
    projectId,
  );
  const [draft, setDraft] = useState("");
  const [taskError, setTaskError] = useState<string | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [pickerRole, setPickerRole] = useState<Role | null>(null);
  const handledRecovery = useRef(0);
  const bottomRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLInputElement>(null);

  const settle = useCallback(() => {
    void refresh().catch(() => {
      setTaskError("the task tree could not be refreshed");
    });
  }, [refresh]);

  const { run, start, confirm } = useRun(window.bison.gatewayHttpUrl, projectId, settle);

  const busy = activity.phase === "invoking";
  const pickerBinding = bindings.find((binding) => binding.role === pickerRole);
  const haltSignalId = halt.signal?.id ?? null;
  const refreshProjects = projects.refresh;
  const refreshManifest = capabilities.refresh;
  const refreshHalt = halt.refresh;
  const answering = reach.reach === "answering";
  const reachRecovery = reach.recovery;
  const canSend = answering && state === "open" && !busy && draft.trim().length > 0;
  const runBlocked = blockedReason(reach.unreachable.includes("mediator"), halt);

  useEffect(() => {
    if (reachRecovery === handledRecovery.current) {
      return;
    }

    handledRecovery.current = reachRecovery;
    refreshProjects();
    reloadHistory();
    refreshManifest();
    refreshHalt();
    reloadBindings();
    void refresh().catch(() => undefined);
  }, [
    reachRecovery,
    refreshProjects,
    reloadHistory,
    refreshManifest,
    refreshHalt,
    reloadBindings,
    refresh,
  ]);

  useEffect(() => {
    if (haltSignalId !== null) {
      refreshProjects();
    }
  }, [haltSignalId, refreshProjects]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages]);

  useEffect(() => {
    const reachForComposer = (keyEvent: KeyboardEvent) => {
      const target = keyEvent.target;
      const editing =
        target instanceof HTMLElement &&
        (target.isContentEditable ||
          target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.tagName === "SELECT");

      if (editing || keyEvent.ctrlKey || keyEvent.altKey || keyEvent.metaKey) {
        return;
      }

      if (keyEvent.key === "/") {
        keyEvent.preventDefault();
        composerRef.current?.focus();
        return;
      }

      if (keyEvent.key.length === 1) {
        composerRef.current?.focus();
      }
    };

    window.addEventListener("keydown", reachForComposer);

    return () => {
      window.removeEventListener("keydown", reachForComposer);
    };
  }, []);

  useEffect(() => {
    if (!busy) {
      setElapsedSeconds(0);
      return;
    }

    const startedAt = Date.now();
    setElapsedSeconds(0);

    const timer = window.setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);

    return () => {
      window.clearInterval(timer);
    };
  }, [busy]);

  const move = (taskId: string, state: string, reason: string | null) => {
    setTaskError(null);
    transition(taskId, state, reason).catch((error: unknown) => {
      setTaskError(error instanceof Error ? error.message : String(error));
    });
  };

  const add = async (draft: TaskDraft): Promise<boolean> => {
    setTaskError(null);

    try {
      await addTask(draft);

      return true;
    } catch (error) {
      setTaskError(error instanceof Error ? error.message : String(error));

      return false;
    }
  };

  const submit = (submitEvent: FormEvent) => {
    submitEvent.preventDefault();
    const content = draft.trim();
    if (content.length === 0 || busy) {
      return;
    }
    if (send(content)) {
      setDraft("");
    }
  };

  return (
    <>
      <Shell
        topBar={
          <>
            <div className="flex items-center gap-4 px-5 py-3">
              <img
                src={markUrl}
                alt=""
                className="h-8 w-8 shrink-0 rounded-control border border-line-subtle"
              />

              <div className="min-w-0 flex-1">
                {answering ? (
                  <ProjectBar projects={projects} />
                ) : (
                  <ReachBanner reach={reach} onRetry={reach.retry} />
                )}
              </div>

              {answering && (
                <div className="flex shrink-0 items-center gap-2 text-[13px] text-ink-faint">
                  <span className={`${mark.dot} ${connectionTone(state)}`} />
                  <span>{state}</span>
                  <span>
                    {historyState === "loading" && "loading history"}
                    {historyState === "ready" && `${messages.length} messages`}
                  </span>
                </div>
              )}
            </div>

            {answering && <HaltBanner halt={halt} />}
          </>
        }
        sidebar={
          <div className="flex flex-col gap-4 py-2">
            {projectId !== null && (
              <RoleBar bindingsState={bindingsState} bindings={bindings} onPick={setPickerRole} />
            )}

            {answering && <ServiceBar unreachable={reach.unreachable} />}

            {answering && <CapabilityBar manifestState={manifestState} manifest={manifest} />}
          </div>
        }
        main={
          <>
            <div className="flex flex-1 flex-col gap-1.5 overflow-y-auto p-5">
              {messages.length === 0 ? (
                <div className="m-auto max-w-[48ch] text-center">
                  {answering &&
                    (historyState === "failed" ? (
                      <p className="text-[13px] text-ink-muted">
                        The conversation could not be read
                      </p>
                    ) : (
                      <>
                        <p className="text-[13px] text-ink-muted">
                          {historyState === "loading"
                            ? "Reading the conversation"
                            : "Nothing has been said yet"}
                        </p>

                        <p className="mt-1 text-[13px] text-ink-faint">
                          {historyState === "loading"
                            ? "One moment"
                            : "Type to start, or press / to reach the message box"}
                        </p>
                      </>
                    ))}
                </div>
              ) : (
                messages.map((message) => (
                  <div className={MESSAGE} key={message.id}>
                    <div className="flex gap-2.5 text-[11.5px] font-medium text-ink-faint">
                      <span className="text-red-300">{message.role}</span>
                      <span>{new Date(message.created_at).toLocaleTimeString()}</span>
                    </div>

                    <div className="text-[14px] leading-relaxed whitespace-pre-wrap">
                      {message.content}
                    </div>
                  </div>
                ))
              )}
              <div ref={bottomRef} />
            </div>

            {projectId !== null && (
              <RunPanel run={run} blocked={runBlocked} onStart={start} onConfirm={confirm} />
            )}

            {taskError !== null && <div className={notice.error}>{taskError}</div>}

            <ActivityBar activity={activity} elapsedSeconds={elapsedSeconds} />

            <form className="flex gap-3 border-t border-line-subtle px-5 py-4" onSubmit={submit}>
              <input
                ref={composerRef}
                className={COMPOSER}
                value={draft}
                onChange={(changeEvent) => setDraft(changeEvent.target.value)}
                placeholder={busy ? "waiting for the model" : "Send a message"}
                disabled={busy}
              />

              <button type="submit" className={button.primary} disabled={!canSend}>
                Send
              </button>
            </form>
          </>
        }
        tracker={
          projectId === null ? (
            <p className="px-4 py-3 text-[13px] text-ink-faint">No project is active.</p>
          ) : (
            <div className="flex flex-col gap-3 py-2">
              <TaskList
                tasksState={tasksState}
                tasks={tasks}
                progress={progress}
                onTransition={move}
              />

              <AddTask onAdd={add} />
            </div>
          )
        }
      />

      {pickerRole !== null && (
        <ModelPicker
          httpUrl={window.bison.gatewayHttpUrl}
          role={pickerRole}
          boundModelId={pickerBinding?.model_id ?? null}
          installed={installed}
          onSelect={(modelId) => rebind(pickerRole, modelId)}
          onPulled={refreshInstalled}
          onClose={() => setPickerRole(null)}
        />
      )}
    </>
  );
}
