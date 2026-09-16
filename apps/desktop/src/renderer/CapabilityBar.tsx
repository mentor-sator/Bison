import {
  CAPABILITY_NAMES,
  isDegraded,
  type Capability,
  type CapabilityManifest,
} from "./capabilities";
import type { ManifestState } from "./useCapabilities";

interface CapabilityBarProps {
  manifestState: ManifestState;
  manifest: CapabilityManifest | null;
}

const BAR = "flex flex-wrap items-center gap-2 border-b border-line-subtle px-3 py-2 text-[11px]";
const CHIP = "inline-flex items-baseline gap-1.5 rounded-tag border px-2 py-0.5";

function backendTone(capability: Capability): string {
  if (capability.backend === null) {
    return "text-status-fail";
  }

  return isDegraded(capability) ? "text-status-wait" : "text-status-ok";
}

function describe(capability: Capability): string {
  const fallbacks = capability.available.slice(1);

  return fallbacks.length > 0
    ? `${capability.strength} · fallbacks: ${fallbacks.join(", ")}`
    : capability.strength;
}

export function CapabilityBar({ manifestState, manifest }: CapabilityBarProps) {
  if (manifestState === "loading") {
    return <div className={`${BAR} text-ink-faint`}>detecting machine capabilities</div>;
  }

  if (manifestState === "failed" || manifest === null) {
    return <div className={`${BAR} text-ink-faint`}>capability manifest unavailable</div>;
  }

  return (
    <div className={BAR}>
      {CAPABILITY_NAMES.map((name) => {
        const capability = manifest[name];

        return (
          <span
            className={`${CHIP} ${capability.backend === null ? "border-(--line-accent)" : "border-line"}`}
            key={name}
            title={describe(capability)}
          >
            <span className="text-[10px] uppercase tracking-[0.04em] text-ink-muted">
              {name.replace("_", " ")}
            </span>

            <span className={backendTone(capability)}>{capability.backend ?? "unavailable"}</span>
          </span>
        );
      })}

      <span className="ml-auto text-ink-faint">
        {manifest.budgets.local_model_gb} GB models · {manifest.budgets.max_projects} projects
      </span>
    </div>
  );
}
