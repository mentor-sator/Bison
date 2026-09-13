import type { ProjectState } from "./projects";
import type { ProjectsView } from "./useProjects";

interface ProjectBarProps {
  projects: ProjectsView;
}

const STATE_LABEL: Record<ProjectState, string> = {
  draft: "not started",
  active: "active",
  paused: "paused",
  archived: "archived",
};

export function ProjectBar({ projects }: ProjectBarProps) {
  const { projectsState, current, targets, capacity, pending, error } = projects;

  if (projectsState === "loading") {
    return <div className="project">reading the project list</div>;
  }

  if (projectsState === "failed") {
    return (
      <div className="project failed">
        <span>the project list is unavailable</span>
        <button type="button" className="project-retry" onClick={projects.refresh}>
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="project">
      <div className="project-head">
        <span className="project-label">project</span>

        <span className="project-name">{current === null ? "none active" : current.name}</span>

        <span className="project-goal">
          {current === null ? "nothing is being worked on" : current.goal}
        </span>

        {capacity !== null && <span className="project-capacity">{capacity}</span>}

        <select
          className="project-switch"
          value=""
          disabled={pending || targets.length === 0}
          onChange={(changeEvent) => projects.switchTo(changeEvent.target.value)}
        >
          <option value="" disabled>
            {targets.length === 0 ? "nothing to switch to" : "switch project — stops all work"}
          </option>
          {targets.map((project) => (
            <option key={project.id} value={project.id}>
              {project.name} — {STATE_LABEL[project.state]}
            </option>
          ))}
        </select>
      </div>

      {error !== null && <div className="project-error">{error}</div>}
    </div>
  );
}
