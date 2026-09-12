import { beforeEach, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReportsPage } from "./ReportsPage";
import { useAuthStore } from "@/shared/state/auth-store";
import { operatorProfile } from "@/test/profile";
import { useUiStore } from "@/shared/state/ui-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";

const mocks = vi.hoisted(() => ({ generate: vi.fn(), detail: vi.fn(), history: vi.fn() }));
vi.mock("./hooks", () => ({
  useGenerateReport: () => ({ mutateAsync: mocks.generate }),
  useReportDetail: mocks.detail, useReportHistory: mocks.history,
}));
const record = { report_id: "r1", workspace_id: "w1", network_id: "n1", report_type: "executive_summary", format: "csv", status: "failed",
  artifacts: [], requested_at: "2026-09-11T00:00:00Z", completed_at: null, queue_status: "deferred", error: { code: "REPORT_GENERATION_FAILED", message: "Worker failed" } };

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ accessToken: "token", profile: operatorProfile });
  useWorkspaceStore.setState({ workspaceId: "w1", networkId: "n1" });
  useUiStore.setState({ toasts: [] });
  mocks.detail.mockReturnValue({ data: null, refetch: vi.fn() });
  mocks.history.mockReturnValue({ data: { items: [], total: 0, page: 1, page_size: 20 }, refetch: vi.fn() });
  mocks.generate.mockResolvedValue({ ...record, status: "requested" });
});

it("submits only documented fields with sensible current dates and explicit scope", async () => {
  render(<ReportsPage />);
  await userEvent.click(screen.getByRole("button", { name: "Generate Report" }));
  const { request } = mocks.generate.mock.calls[0][0];
  expect(request).toMatchObject({ workspace_id: "w1", network_id: "n1", scope: {}, filters: { max_rows: 100 }, report_type: "executive_summary" });
  expect(Date.now() - Date.parse(request.date_range.end)).toBeLessThan(10_000);
  expect(Date.parse(request.date_range.end) - Date.parse(request.date_range.start)).toBeCloseTo(86400_000, -3);
  expect(screen.queryByLabelText("Filters JSON")).not.toBeInTheDocument();
  expect(useUiStore.getState().toasts.at(-1)?.title).toBe("Report request accepted");
});

it("does not claim generated for failed or artifact-free responses", async () => {
  mocks.generate.mockResolvedValue(record);
  mocks.detail.mockReturnValue({ data: { ...record, status: "generated", error: null }, refetch: vi.fn() });
  render(<ReportsPage />);
  await userEvent.click(screen.getByRole("button", { name: "Generate Report" }));
  expect(useUiStore.getState().toasts.at(-1)?.tone).toBe("danger");
  expect(screen.getByText("Artifact unavailable / unverified")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Download/ })).not.toBeInTheDocument();
});

it("hides legacy artifact references and never renders them as links or success", () => {
  mocks.detail.mockReturnValue({ data: { ...record, status: "generated", artifacts: [{ uri: "s3://historical-invalid/ref.pdf", checksum_sha256: "fake", size_bytes: 16384 }] }, refetch: vi.fn() });
  render(<ReportsPage />);
  expect(screen.queryByText(/s3:\/\//)).not.toBeInTheDocument();
  expect(screen.getByText("No verified artifacts available")).toBeInTheDocument();
});

it("shows backend validation and failed generation diagnostics; retry uses a new key after review", async () => {
  mocks.detail.mockReturnValue({ data: record, refetch: vi.fn() });
  render(<ReportsPage />);
  expect(screen.getByText("Worker failed")).toBeInTheDocument();
  const before = (screen.getByLabelText("Idempotency Key") as HTMLInputElement).value;
  await userEvent.click(screen.getByRole("button", { name: "Retry Failed Report" }));
  expect(screen.getByLabelText("Idempotency Key")).not.toHaveValue(before);
  expect(mocks.generate).not.toHaveBeenCalled();
  mocks.generate.mockRejectedValueOnce(new Error("simulation_ids require a simulation or summary report"));
  await userEvent.click(screen.getByRole("button", { name: "Generate Report" }));
  expect(screen.getByText("simulation_ids require a simulation or summary report")).toBeInTheDocument();
});

it("paginates history, selects records and resets selection on workspace change", async () => {
  mocks.history.mockReturnValue({ data: { items: [record], total: 21, page: 1, page_size: 20 }, refetch: vi.fn() });
  const view = render(<ReportsPage />);
  await userEvent.click(screen.getByRole("button", { name: /executive_summary \/ csv/ }));
  expect(mocks.detail).toHaveBeenLastCalledWith("token", "r1", "w1");
  await userEvent.click(screen.getByRole("button", { name: "Next Reports" }));
  expect(mocks.history).toHaveBeenLastCalledWith("token", "w1", 2);
  act(() => useWorkspaceStore.setState({ workspaceId: "w2" }));
  view.rerender(<ReportsPage />);
  expect(mocks.detail).toHaveBeenLastCalledWith("token", null, "w2");
  expect(mocks.history).toHaveBeenLastCalledWith("token", "w2", 1);
});

it("blocks generation and retries for a read-only user", () => {
  useAuthStore.setState({ profile: { ...operatorProfile, permissions: ["read:telemetry"] } });
  mocks.detail.mockReturnValue({ data: record, refetch: vi.fn() });
  render(<ReportsPage />);
  expect(screen.getByRole("button", { name: "Generate Report" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Retry Failed Report" })).toBeDisabled();
});
