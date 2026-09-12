import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { IntentDetailResult } from "@/shared/types/intent";
import { PathEvidencePanel } from "./PathEvidencePanel";

const detail = { status: "execution_completed", execution_provenance: { phase: "completed", plan_hash: "a".repeat(64), approved_plan: { operation: "reroute", source_host: "h1", destination_host: "h2", paths: [["s1", "s3", "s4"]], weights: [1], rate_mbps: null, dscp: null }, verification: { readback_verified: true, readback_sha256: "b".repeat(64) } } } as unknown as IntentDetailResult;

describe("persisted path evidence", () => {
  it("renders ordered approved steps and real hashes with limited verification claims", () => {
    render(<PathEvidencePanel detail={detail} />);
    expect(screen.getByRole("heading")).toHaveTextContent("Configuration-verified path evidence");
    expect(screen.getAllByRole("listitem").map((item) => item.textContent)).toEqual(["s1", "s3", "s4"]);
    expect(screen.getByText(/Readback evidence SHA-256/)).toHaveTextContent("b".repeat(64));
    expect(screen.getByText(/Observed packet traversal unavailable/)).toBeInTheDocument();
  });
  it.each([{ approved_plan: undefined }, { verification: { status: "passed" } }, { uncertain: true }, { rollback: { verified: true, readback_sha256: "c".repeat(64) } }])("does not infer verified paths from missing or superseded evidence: %j", (change) => {
    render(<PathEvidencePanel detail={{ ...detail, execution_provenance: { ...detail.execution_provenance, ...change } }} />);
    expect(screen.getByRole("heading")).toHaveTextContent("Configuration path evidence unavailable");
  });
});
