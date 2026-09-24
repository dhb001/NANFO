import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { AuditPage } from "./AuditPage";
import { useAuthStore } from "@/shared/state/auth-store";
import { useWorkspaceStore } from "@/shared/state/workspace-store";
import { operatorProfile } from "@/test/profile";

const actorId = "00000000-0000-0000-0000-000000000123";
const requests: URLSearchParams[] = [];

beforeEach(() => {
  requests.length = 0;
  useAuthStore.setState({ userId: actorId, accessToken: "token-1", profile: { ...operatorProfile, roles: ["Admin"] } });
  useWorkspaceStore.setState({ organizationId: "org-1", workspaceId: null, networkId: null });
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const params = new URL(url, "http://localhost").searchParams;
    requests.push(params);
    const page = Number(params.get("page"));
    const pageSize = Number(params.get("page_size"));
    const total = params.get("search") === "absent" ? 0 : 125;
    return Response.json({ success: true, data: { total, page, page_size: pageSize,
      items: Array.from({ length: Math.max(0, Math.min(pageSize, total - (page - 1) * pageSize)) }, (_, i) => {
        const index = (page - 1) * pageSize + i + 1;
        return { log_id: `log-${index}`, event_type: `event-${index}`, actor_id: actorId,
          resource_type: "network", resource_id: `resource-${index}`, org_id: "org-1", correlation_id: `corr-${index}`,
          timestamp: "2026-09-20T00:00:00Z", metadata: { before: { name: "old name" }, after: { name: "new name" } } };
      }) }, meta: {}, errors: null });
  }));
});

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><AuditPage /></QueryClientProvider>);
}

it("pages beyond 120 records and exposes actor, resource and before/after evidence", async () => {
  const user = userEvent.setup();
  renderPage();
  await screen.findByText("event-1");
  expect(screen.getAllByRole("listitem")).toHaveLength(50);
  expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Next page" }));
  await screen.findByText("event-51");
  await user.click(screen.getByRole("button", { name: "Next page" }));
  await screen.findByText("event-125");
  expect(screen.getAllByRole("listitem")).toHaveLength(25);
  expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
  await user.click(screen.getByText("Audit details: event-125"));
  expect(screen.getByText("resource-125")).toBeVisible();
  expect(screen.getAllByText(actorId).at(-1)).toBeVisible();
  expect(screen.getAllByText(/old name/).at(-1)).toBeVisible();
  expect(screen.getAllByText(/new name/).at(-1)).toBeVisible();
});

it("submits all server filters, resets the page and tenant state, and preserves drafts over token rotation", async () => {
  const user = userEvent.setup();
  renderPage();
  await screen.findByText("event-1");
  await user.click(screen.getByRole("button", { name: "Next page" }));
  await screen.findByText("event-51");
  await user.type(screen.getByLabelText("Search audit records"), "absent");
  await user.type(screen.getByLabelText("Actor ID"), actorId);
  await user.type(screen.getByLabelText("Resource type"), "network");
  expect(requests.at(-1)?.get("search")).toBeNull();
  await user.click(screen.getByRole("button", { name: "Apply filters" }));
  await screen.findByText("No audit records match these filters");
  expect(Object.fromEntries(requests.at(-1)!)).toMatchObject({ page: "1", page_size: "50", actor_id: actorId, resource_type: "network", search: "absent", org_id: "org-1" });
  act(() => useAuthStore.setState({ accessToken: "rotated" }));
  expect(screen.getByLabelText("Search audit records")).toHaveValue("absent");
  act(() => useWorkspaceStore.setState({ organizationId: "org-2" }));
  await waitFor(() => expect(requests.at(-1)?.get("org_id")).toBe("org-2"));
  expect(screen.getByLabelText("Search audit records")).toHaveValue("");
  expect(requests.at(-1)?.get("search")).toBeNull();
  expect(requests.at(-1)?.get("page")).toBe("1");
});

it("does not query audit without an organization", () => {
  useWorkspaceStore.setState({ organizationId: null });
  renderPage();
  expect(screen.getByText("Select an organization")).toBeInTheDocument();
  expect(requests).toHaveLength(0);
});

it("lists platform-scope events for global admins without an organization (C7)", async () => {
  const user = userEvent.setup();
  useWorkspaceStore.setState({ organizationId: null });
  renderPage();
  expect(screen.getByText("Select an organization")).toBeInTheDocument();
  await user.click(screen.getByRole("radio", { name: /Platform events/ }));
  await screen.findByText("event-1");
  expect(requests.at(-1)?.get("scope")).toBe("platform");
  // Platform scope never sends org_id (the backend rejects the combination).
  expect(requests.at(-1)?.get("org_id")).toBeNull();
  await user.click(screen.getByRole("radio", { name: "This organization" }));
  expect(screen.getByText("Select an organization")).toBeInTheDocument();
});

it("keeps org scope as the default and never sends scope=platform implicitly", async () => {
  renderPage();
  await screen.findByText("event-1");
  expect(requests.every((params) => params.get("scope") === null && params.get("org_id") === "org-1")).toBe(true);
});
