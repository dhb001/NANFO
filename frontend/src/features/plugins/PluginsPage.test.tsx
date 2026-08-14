import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { PluginsPage } from "@/features/plugins/PluginsPage";
import { useAuthStore } from "@/shared/state/auth-store";
import { useUiStore } from "@/shared/state/ui-store";

const mockUsePluginsQuery = vi.fn();
const mockUseInstallPlugin = vi.fn();
const mockUseEnablePlugin = vi.fn();
const mockUseDisablePlugin = vi.fn();

vi.mock("@/features/plugins/hooks", () => ({
  usePluginsQuery: (...args: unknown[]) => mockUsePluginsQuery(...args),
  useInstallPlugin: (...args: unknown[]) => mockUseInstallPlugin(...args),
  useEnablePlugin: (...args: unknown[]) => mockUseEnablePlugin(...args),
  useDisablePlugin: (...args: unknown[]) => mockUseDisablePlugin(...args),
}));

const mockInstallMutateAsync = vi.fn();
const mockEnableMutateAsync = vi.fn();
const mockDisableMutateAsync = vi.fn();
const mockPluginsRefetch = vi.fn();

function queryResult<T>(data: T, refetch = vi.fn()) {
  return {
    isLoading: false,
    isError: false,
    data,
    refetch,
  };
}

describe("PluginsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();

    useAuthStore.setState({
      accessToken: "token-1",
      refreshToken: "refresh-1",
      userId: "00000000-0000-0000-0000-000000000123",
    });
    useUiStore.setState({
      commandPaletteOpen: false,
      toasts: [],
    });

    mockUsePluginsQuery.mockReturnValue(
      queryResult(
        {
          items: [
            {
              plugin_id: "00000000-0000-0000-0000-000000000701",
              plugin_key: "safe-plugin",
              name: "Safe Plugin",
              version: "1.0.0",
              manifest: {
                plugin_key: "safe-plugin",
                name: "Safe Plugin",
                version: "1.0.0",
                signer: "nanfo-labs",
                signature: "sig:abcdef1234567890",
                dependencies: {
                  platform_version: "0.1.0",
                  requires: ["core:telemetry"],
                },
                sandbox: {
                  isolation_mode: "process",
                  permissions: ["read:telemetry"],
                },
                metadata: {},
              },
              signature_status: "verified",
              dependency_status: "compatible",
              sandbox_status: "isolated",
              status: "installed",
              enabled: false,
              failure_reason: null,
              queue_status: "queued",
              stream_entry_id: "701-0",
              warning: null,
              installed_at: "2026-08-14T12:00:00Z",
              updated_at: "2026-08-14T12:00:00Z",
            },
            {
              plugin_id: "00000000-0000-0000-0000-000000000702",
              plugin_key: "failed-plugin",
              name: "Failed Plugin",
              version: "2.1.0",
              manifest: {
                plugin_key: "failed-plugin",
                name: "Failed Plugin",
                version: "2.1.0",
                signer: "unknown",
                signature: "sig:zzz",
                dependencies: {
                  platform_version: "9.9.9",
                  requires: [],
                },
                sandbox: {
                  isolation_mode: "process",
                  permissions: ["write:config"],
                },
                metadata: {},
              },
              signature_status: "invalid",
              dependency_status: "incompatible",
              sandbox_status: "blocked",
              status: "failed",
              enabled: false,
              failure_reason: "PLUGIN_SIGNATURE_INVALID",
              queue_status: "queued",
              stream_entry_id: "702-0",
              warning: null,
              installed_at: "2026-08-14T12:01:00Z",
              updated_at: "2026-08-14T12:01:00Z",
            },
          ],
          total: 2,
          status_counts: {
            installed: 1,
            enabled: 0,
            disabled: 0,
            failed: 1,
          },
        },
        mockPluginsRefetch,
      ),
    );

    mockUseInstallPlugin.mockReturnValue({
      mutateAsync: mockInstallMutateAsync,
      isPending: false,
      isError: false,
      error: null,
    });
    mockUseEnablePlugin.mockReturnValue({
      mutateAsync: mockEnableMutateAsync,
      isPending: false,
      isError: false,
      error: null,
    });
    mockUseDisablePlugin.mockReturnValue({
      mutateAsync: mockDisableMutateAsync,
      isPending: false,
      isError: false,
      error: null,
    });

    mockInstallMutateAsync.mockResolvedValue({
      queue_status: "queued",
      idempotent_replay: false,
    });
    mockEnableMutateAsync.mockResolvedValue({
      queue_status: "queued",
      idempotent_replay: false,
    });
    mockDisableMutateAsync.mockResolvedValue({
      queue_status: "queued",
      idempotent_replay: false,
    });
  });

  it("renders plugin registry and failed safety state", () => {
    render(<PluginsPage />);

    expect(screen.getByText("Plugin Runtime Safety")).toBeInTheDocument();
    expect(screen.getByText("Plugin Registry")).toBeInTheDocument();
    expect(screen.getByText("Safe Plugin")).toBeInTheDocument();
    expect(screen.getByText("Failed Plugin")).toBeInTheDocument();
    expect(screen.getByText("Failure reason: PLUGIN_SIGNATURE_INVALID")).toBeInTheDocument();
  });

  it("filters plugins by failed status", async () => {
    const user = userEvent.setup();
    render(<PluginsPage />);

    await user.click(screen.getByRole("button", { name: "Failed" }));

    expect(mockUsePluginsQuery).toHaveBeenCalled();
  });

  it("submits install plugin action", async () => {
    const user = userEvent.setup();
    render(<PluginsPage />);

    await user.click(screen.getByRole("button", { name: "Install Plugin" }));

    expect(mockInstallMutateAsync).toHaveBeenCalled();
  });

  it("blocks install when sandbox permission is unsupported", async () => {
    const user = userEvent.setup();
    render(<PluginsPage />);

    await user.clear(screen.getByLabelText("Sandbox permissions"));
    await user.type(screen.getByLabelText("Sandbox permissions"), "write:config");
    await user.click(screen.getByRole("button", { name: "Install Plugin" }));

    expect(mockInstallMutateAsync).not.toHaveBeenCalled();
    expect(useUiStore.getState().toasts.some((toast) => toast.title === "Invalid permission")).toBe(true);
  });

  it("runs enable action for safe plugin", async () => {
    const user = userEvent.setup();
    render(<PluginsPage />);

    await user.click(screen.getAllByRole("button", { name: "Enable" })[0]);

    expect(mockEnableMutateAsync).toHaveBeenCalledWith("00000000-0000-0000-0000-000000000701");
  });

  it("disable button is unavailable for non-enabled plugins", () => {
    render(<PluginsPage />);
    const disableButtons = screen.getAllByRole("button", { name: "Disable" });
    expect(disableButtons[0]).toBeDisabled();
  });
});
