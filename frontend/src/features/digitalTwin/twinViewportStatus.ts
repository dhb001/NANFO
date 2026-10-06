import { describeApiError } from "@/shared/lib/errors";

/** Data state of the Twin view. The Canvas stays mounted; anything but `ready` is an overlay. */
export type ViewportStatus =
  | { kind: "ready" }
  | { kind: "no-network" | "loading" | "empty" | "error"; title: string; description: string };

export interface ViewportStatusInput {
  networkSelected: boolean;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  hasData: boolean;
  /** Any device (REST or live) or canonical geometry to draw. */
  hasContent: boolean;
}

export const READY_STATUS: ViewportStatus = Object.freeze({ kind: "ready" });

export function resolveViewportStatus(input: ViewportStatusInput): ViewportStatus {
  if (!input.networkSelected) {
    return { kind: "no-network", title: "No network selected", description: "Select a network to load its topology and spatial scene." };
  }
  if (input.isLoading) {
    return { kind: "loading", title: "Loading topology", description: "The scene fills in as soon as topology data arrives." };
  }
  if (input.isError) {
    const kept = input.hasData ? " The last loaded topology stays visible." : "";
    return { kind: "error", title: "Topology request failed", description: `${describeApiError(input.error)}${kept}` };
  }
  if (!input.hasContent) {
    return { kind: "empty", title: "Topology graph is empty", description: "Add devices and wait for topology websocket deltas." };
  }
  return READY_STATUS;
}
