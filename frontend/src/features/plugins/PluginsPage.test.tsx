import { beforeEach, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PluginsPage } from "./PluginsPage";
import { useAuthStore } from "@/shared/state/auth-store";
import { operatorProfile } from "@/test/profile";
import { useUiStore } from "@/shared/state/ui-store";

const mocks = vi.hoisted(() => ({ query: vi.fn(), install: vi.fn(), enable: vi.fn(), disable: vi.fn(), uninstall: vi.fn() }));
vi.mock("./hooks", () => ({
  usePluginsQuery: mocks.query,
  useInstallPlugin: () => ({ mutateAsync: mocks.install }),
  useEnablePlugin: () => ({ mutateAsync: mocks.enable }),
  useDisablePlugin: () => ({ mutateAsync: mocks.disable }),
  useUninstallPlugin: () => ({ mutateAsync: mocks.uninstall }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ accessToken: "token", profile: { ...operatorProfile, roles: ["Admin"] } });
  useUiStore.setState({ toasts: [] });
  mocks.query.mockReturnValue({ data: { items: [{ plugin_id: "p1", name: "Declared Plugin", plugin_key: "declared", version: "1", status: "installed", enabled: false,
    signature_status: "verified", dependency_status: "compatible", sandbox_status: "isolated", queue_status: "queued" }] }, refetch: vi.fn() });
  mocks.enable.mockResolvedValue({ status: "enabled" });
});

it("masks historical safety overclaims and enables registry flags only", async () => {
  render(<PluginsPage />);
  expect(screen.getByText("signature declared_unverified")).toBeInTheDocument();
  expect(screen.getByText("sandbox not_executed")).toBeInTheDocument();
  expect(screen.queryByText("signature verified")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Enable" }));
  expect(mocks.enable).toHaveBeenCalledWith("p1");
  expect(screen.getByRole("status")).toHaveTextContent("No package executed");
});

it("requires permission and never treats denied or failed updates as success", async () => {
  mocks.enable.mockRejectedValue(new Error("Permission revoked"));
  render(<PluginsPage />);
  await userEvent.click(screen.getByRole("button", { name: "Enable" }));
  expect(screen.getByText("Permission revoked")).toBeInTheDocument();
  expect(useUiStore.getState().toasts).toHaveLength(0);
});

it("disables writes without Admin and write capability", () => {
  useAuthStore.setState({ profile: operatorProfile });
  render(<PluginsPage />);
  expect(screen.getByRole("button", { name: "Register Metadata" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Enable" })).toBeDisabled();
});

it("requires uninstall confirmation and keeps denial visible without success", async () => {
  mocks.uninstall.mockRejectedValueOnce(new Error("Membership revoked"));
  render(<PluginsPage />);
  await userEvent.click(screen.getByRole("button", { name: "Uninstall" }));
  expect(mocks.uninstall).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("button", { name: "Confirm Uninstall" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Uninstall" }));
  await userEvent.click(screen.getByRole("button", { name: "Confirm Uninstall" }));
  expect(screen.getByText("Membership revoked")).toBeInTheDocument();
  expect(useUiStore.getState().toasts).toHaveLength(0);
  mocks.uninstall.mockResolvedValueOnce(undefined);
  await userEvent.click(screen.getByRole("button", { name: "Confirm Uninstall" }));
  expect(screen.getByRole("status")).toHaveTextContent("Registry entry uninstalled");
});

it("uses backend-owned declaration validation without fake prefilled signatures", async () => {
  render(<PluginsPage />);
  expect(screen.getByLabelText("Signature")).toHaveValue("");
  await userEvent.click(screen.getByRole("button", { name: "Register Metadata" }));
  expect(mocks.install).not.toHaveBeenCalled();
});
