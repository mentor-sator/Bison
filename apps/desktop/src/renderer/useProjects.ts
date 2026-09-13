import { useCallback, useEffect, useReducer } from "react";
import {
  activeProject,
  describeCapacity,
  fetchProjects,
  requestSwitch,
  switchTargets,
  type Project,
  type ProjectList,
} from "./projects";

export type ProjectsState = "loading" | "ready" | "failed";

export interface ProjectsView {
  projectsState: ProjectsState;
  projects: Project[];
  current: Project | null;
  targets: Project[];
  capacity: string | null;
  pending: boolean;
  error: string | null;
  refresh: () => void;
  switchTo: (projectId: string) => void;
}

interface ProjectsData {
  list: ProjectList | null;
  projectsState: ProjectsState;
  pending: boolean;
  error: string | null;
}

type ProjectsAction =
  { kind: "pending" } | { kind: "read"; list: ProjectList } | { kind: "failed"; message: string };

const PROJECTS_IDLE: ProjectsData = {
  list: null,
  projectsState: "loading",
  pending: false,
  error: null,
};

const describe = (error: unknown): string => {
  return error instanceof Error ? error.message : String(error);
};

function reduceProjects(state: ProjectsData, action: ProjectsAction): ProjectsData {
  switch (action.kind) {
    case "pending":
      return { ...state, pending: true, error: null };
    case "read":
      return { list: action.list, projectsState: "ready", pending: false, error: null };
    case "failed":
      return {
        ...state,
        projectsState: state.list === null ? "failed" : state.projectsState,
        pending: false,
        error: action.message,
      };
  }
}

export function useProjects(httpUrl: string): ProjectsView {
  const [projects, dispatch] = useReducer(reduceProjects, PROJECTS_IDLE);

  const read = useCallback(async (): Promise<void> => {
    dispatch({ kind: "pending" });

    try {
      dispatch({ kind: "read", list: await fetchProjects(httpUrl) });
    } catch (error) {
      dispatch({ kind: "failed", message: describe(error) });
    }
  }, [httpUrl]);

  useEffect(() => {
    void read();
  }, [read]);

  const refresh = useCallback(() => {
    void read();
  }, [read]);

  const switchTo = useCallback(
    (projectId: string) => {
      dispatch({ kind: "pending" });

      requestSwitch(httpUrl, projectId)
        .then(() => read())
        .catch((error: unknown) => {
          dispatch({ kind: "failed", message: describe(error) });
        });
    },
    [httpUrl, read],
  );

  const list = projects.list;

  return {
    projectsState: projects.projectsState,
    projects: list?.projects ?? [],
    current: list === null ? null : activeProject(list),
    targets: list === null ? [] : switchTargets(list),
    capacity: list === null ? null : describeCapacity(list),
    pending: projects.pending,
    error: projects.error,
    refresh,
    switchTo,
  };
}
