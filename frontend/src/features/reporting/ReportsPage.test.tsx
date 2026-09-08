import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ReportsPage } from "@/features/reporting/ReportsPage";
import { useAuthStore } from "@/shared/state/auth-store";
import { operatorProfile } from "@/test/profile";
import { useUiStore } from "@/shared/state/ui-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";

const mockUseGenerateReport = vi.fn();
const mockUseReportDetail = vi.fn();

vi.mock("@/features/reporting/hooks", () => ({
  useGenerateReport: (...args: unknown[]) => mockUseGenerateReport(...args),
  useReportDetail: (...args: unknown[]) => mockUseReportDetail(...args),
}));

const mutateAsync = vi.fn();
const detailRefetch = vi.fn();

function queryResult<T>(data: T | null) {
  return {
    isLoading: false,
    isError: false,
    data,
    refetch: detailRefetch,
  };
}

describe("ReportsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();

    useAuthStore.setState({
      profile: operatorProfile,
      accessToken: "token-1",
      refreshToken: "refresh-1",
      userId: "00000000-0000-0000-0000-000000000123",
    });
    useWorkspaceStore.setState({
      organizationId: "00000000-0000-0000-0000-000000000111",
      workspaceId: "00000000-0000-0000-0000-000000000222",
      networkId: "00000000-0000-0000-0000-000000000333",
    });
    useUiStore.setState({
      commandPaletteOpen: false,
      toasts: [],
    });

    mockUseGenerateReport.mockReturnValue({
      mutateAsync,
      isPending: false,
      isError: false,
      error: null,
    });
    mockUseReportDetail.mockReturnValue(queryResult(null));

    mutateAsync.mockResolvedValue({
      report_id: "00000000-0000-0000-0000-000000000951",
      workspace_id: "00000000-0000-0000-0000-000000000222",
      network_id: "00000000-0000-0000-0000-000000000333",
      report_type: "executive_summary",
      format: "pdf",
      status: "requested",
      date_range: {
        start: "2026-08-01T00:00:00Z",
        end: "2026-08-14T00:00:00Z",
      },
      scope: { workspace: "all" },
      filters: { kpi: "latency" },
      artifacts: [],
      error: null,
      queue_status: "queued",
      stream_entry_id: "1000-0",
      warning: null,
      idempotency_key: "rep-1",
      correlation_id: "corr-1",
      requested_by_user_id: "00000000-0000-0000-0000-000000000123",
      requested_at: "2026-08-14T12:00:00Z",
      completed_at: null,
      created_at: "2026-08-14T12:00:00Z",
      updated_at: "2026-08-14T12:00:00Z",
      idempotent_replay: false,
    });
  });

  it("renders report generator and empty status state", () => {
    render(<ReportsPage />);

    expect(screen.getByText("Report Generator")).toBeInTheDocument();
    expect(screen.getByText("Report Status")).toBeInTheDocument();
    expect(screen.getByText("No report selected")).toBeInTheDocument();
  });

  it("submits report request and stores toast feedback", async () => {
    const user = userEvent.setup();
    render(<ReportsPage />);

    await user.click(screen.getByRole("button", { name: "Generate Report" }));

    expect(mutateAsync).toHaveBeenCalledTimes(1);
    expect(useUiStore.getState().toasts.some((toast) => toast.title === "Report request accepted")).toBe(true);
  });

  it("does not call a failed demo report accepted or generated", async () => {
    mutateAsync.mockResolvedValueOnce({ report_id: "demo-report", status: "failed", queue_status: "blocked", idempotent_replay: false });
    render(<ReportsPage />);
    await userEvent.click(screen.getByRole("button", { name: "Generate Report" }));
    expect(useUiStore.getState().toasts.at(-1)).toMatchObject({
      title: "Report failed: no artifacts generated", tone: "danger",
    });
  });

  it("shows failed report diagnostics and retry action", async () => {
    mockUseReportDetail.mockReturnValue(
      queryResult({
        report_id: "00000000-0000-0000-0000-000000000951",
        workspace_id: "00000000-0000-0000-0000-000000000222",
        network_id: "00000000-0000-0000-0000-000000000333",
        report_type: "executive_summary",
        format: "pdf",
        status: "failed",
        date_range: {
          start: "2026-08-01T00:00:00Z",
          end: "2026-08-14T00:00:00Z",
        },
        scope: { workspace: "all" },
        filters: { kpi: "latency" },
        artifacts: [],
        error: {
          code: "REPORT_GENERATION_FAILED",
          message: "Report generation failed during queue processing.",
        },
        queue_status: "queued",
        stream_entry_id: "1000-0",
        warning: null,
        idempotency_key: "rep-1",
        correlation_id: "corr-1",
        requested_by_user_id: "00000000-0000-0000-0000-000000000123",
        requested_at: "2026-08-14T12:00:00Z",
        completed_at: "2026-08-14T12:00:10Z",
        created_at: "2026-08-14T12:00:00Z",
        updated_at: "2026-08-14T12:00:10Z",
      }),
    );

    const user = userEvent.setup();
    render(<ReportsPage />);

    expect(screen.getByText("Report generation failed")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry Failed Report" }));
    expect(mutateAsync).toHaveBeenCalled();
  });

  it("renders generated artifacts metadata", () => {
    mockUseReportDetail.mockReturnValue(
      queryResult({
        report_id: "00000000-0000-0000-0000-000000000951",
        workspace_id: "00000000-0000-0000-0000-000000000222",
        network_id: "00000000-0000-0000-0000-000000000333",
        report_type: "executive_summary",
        format: "pdf",
        status: "generated",
        date_range: {
          start: "2026-08-01T00:00:00Z",
          end: "2026-08-14T00:00:00Z",
        },
        scope: { workspace: "all" },
        filters: { kpi: "latency" },
        artifacts: [
          {
            artifact_id: "artifact-951-pdf",
            uri: "s3://nanfo-reports/ws/report.pdf",
            media_type: "application/pdf",
            checksum_sha256: "abc123",
            size_bytes: 16384,
            generated_at: "2026-08-14T12:00:10Z",
          },
        ],
        error: null,
        queue_status: "queued",
        stream_entry_id: "1000-0",
        warning: null,
        idempotency_key: "rep-1",
        correlation_id: "corr-1",
        requested_by_user_id: "00000000-0000-0000-0000-000000000123",
        requested_at: "2026-08-14T12:00:00Z",
        completed_at: "2026-08-14T12:00:10Z",
        created_at: "2026-08-14T12:00:00Z",
        updated_at: "2026-08-14T12:00:10Z",
      }),
    );

    render(<ReportsPage />);

    expect(screen.getByText("artifact-951-pdf")).toBeInTheDocument();
    expect(screen.getByText("application/pdf")).toBeInTheDocument();
  });
});
