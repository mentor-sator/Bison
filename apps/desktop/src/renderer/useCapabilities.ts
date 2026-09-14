import { useCallback, useEffect, useState } from "react";
import { fetchManifest, type CapabilityManifest } from "./capabilities";

export type ManifestState = "loading" | "ready" | "failed";

export interface CapabilitiesView {
  manifestState: ManifestState;
  manifest: CapabilityManifest | null;
  refresh: () => void;
}

export function useCapabilities(httpUrl: string): CapabilitiesView {
  const [manifestState, setManifestState] = useState<ManifestState>("loading");
  const [manifest, setManifest] = useState<CapabilityManifest | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;

    setManifestState("loading");

    fetchManifest(httpUrl)
      .then((loaded) => {
        if (cancelled) {
          return;
        }
        setManifest(loaded);
        setManifestState("ready");
      })
      .catch(() => {
        if (!cancelled) {
          setManifestState("failed");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [httpUrl, attempt]);

  const refresh = useCallback(() => {
    setAttempt((count) => count + 1);
  }, []);

  return { manifestState, manifest, refresh };
}
