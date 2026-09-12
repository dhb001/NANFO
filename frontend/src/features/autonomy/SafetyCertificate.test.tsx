import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SafetyCertificate } from "./SafetyCertificate";
import { certificateFixture } from "./fixtures";
import type { AutonomyDecision } from "./types";

const safety: NonNullable<AutonomyDecision["safety"]> = {
  admissible: true, action_id: "route-1", model_version: "test-only", reasons: [], evidence: [],
};

describe("reported structured safety certificate", () => {
  it("never derives a certificate or hashes from unstructured evidence", () => {
    render(<SafetyCertificate safety={{ ...safety, evidence: ["approved, expires tomorrow, sha256: unverified"] }} now={0} />);
    expect(screen.queryByRole("region")).not.toBeInTheDocument();
  });
  it("shows exact returned units, expiry and hashes without implying current authorization", () => {
    render(<SafetyCertificate safety={{ ...safety, certificate: certificateFixture(), binding: {
      workspace_id: "workspace", observation_sha256: "b".repeat(64), proposal_sha256: "c".repeat(64),
      calibration_sha256: "d".repeat(64), selected_action_sha256: "e".repeat(64), evaluated_at_unix_seconds: 1_001,
    } }} now={1_005_000} />);
    expect(screen.getByText("a".repeat(64))).toBeInTheDocument();
    expect(screen.getByText("e".repeat(64))).toBeInTheDocument();
    expect(screen.getByText(/1970-01-01T00:16:45.000Z. Expired by browser clock/)).toBeInTheDocument();
    expect(screen.getByText("-18 / 0")).toBeInTheDocument();
    expect(screen.getByText(/not signatures or independently verified provenance/)).toBeInTheDocument();
  });
  it("does not fill absent binding hashes or call an unexpired certificate authorized", () => {
    render(<SafetyCertificate safety={{ ...safety, certificate: certificateFixture() }} now={1_001_000} />);
    expect(screen.getByText(/server must recheck/)).toBeInTheDocument();
    expect(screen.queryByText("Observation SHA-256")).not.toBeInTheDocument();
  });
});
