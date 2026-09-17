import { useCallback, useEffect, useState } from "react";
import { bindRole, fetchBindings, fetchInstalled, type Role, type RoleBinding } from "./broker";

export type BindingsState = "loading" | "ready" | "failed";

export interface BindingsView {
  bindingsState: BindingsState;
  bindings: RoleBinding[];
  installed: Set<string>;
  rebind: (role: Role, modelId: string) => Promise<void>;
  refreshInstalled: () => Promise<void>;
  reload: () => void;
}

export function useBindings(httpUrl: string, projectId: string | null): BindingsView {
  const [bindingsState, setBindingsState] = useState<BindingsState>("loading");
  const [bindings, setBindings] = useState<RoleBinding[]>([]);
  const [installed, setInstalled] = useState<Set<string>>(new Set());
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (projectId === null) {
      return;
    }

    let cancelled = false;

    Promise.all([fetchBindings(httpUrl, projectId), fetchInstalled(httpUrl)])
      .then(([loadedBindings, loadedInstalled]) => {
        if (cancelled) {
          return;
        }
        setBindings(loadedBindings);
        setInstalled(loadedInstalled);
        setBindingsState("ready");
      })
      .catch(() => {
        if (!cancelled) {
          setBindingsState("failed");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [httpUrl, projectId, attempt]);

  const rebind = useCallback(
    async (role: Role, modelId: string) => {
      if (projectId === null) {
        return;
      }

      const bound = await bindRole(httpUrl, projectId, role, modelId);

      setBindings((current) => {
        const others = current.filter((binding) => binding.role !== bound.role);
        return [...others, bound];
      });
    },
    [httpUrl, projectId],
  );

  const refreshInstalled = useCallback(async () => {
    setInstalled(await fetchInstalled(httpUrl));
  }, [httpUrl]);

  const reload = useCallback(() => {
    setAttempt((count) => count + 1);
  }, []);

  return { bindingsState, bindings, installed, rebind, refreshInstalled, reload };
}
