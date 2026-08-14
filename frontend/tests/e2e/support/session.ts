import { expect, Page } from "@playwright/test";

export interface MockNetwork {
  network_id: string;
  workspace_id: string;
  name: string;
  description: string | null;
  cidr: string | null;
  created_at: string;
}

export interface MockDevice {
  device_id: string;
  network_id: string;
  hostname: string;
  ip_address: string | null;
  device_type: string;
  vendor: string | null;
  model: string | null;
  location_hint: string | null;
  spatial_ref_id: string | null;
  status: string;
  created_at: string;
}

export interface MockAlertRecord {
  alert_id: string;
  alert_key: string;
  source: string;
  status: "active" | "acknowledged" | "resolved";
  severity: string | null;
  correlation_id: string;
  payload: Record<string, unknown>;
  acknowledged_by_user_id: string | null;
  resolved_by_user_id: string | null;
  acknowledged_at: string | null;
  resolved_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface SessionMockState {
  userId: string;
  email: string;
  orgId: string;
  workspaceId: string;
  networks: MockNetwork[];
  devicesByNetwork: Record<string, MockDevice[]>;
  alerts: MockAlertRecord[];
}

export function createDefaultSessionState(): SessionMockState {
  const orgId = "00000000-0000-0000-0000-000000000111";
  const workspaceId = "00000000-0000-0000-0000-000000000222";
  const networkId = "00000000-0000-0000-0000-000000000333";

  return {
    userId: "00000000-0000-0000-0000-000000000123",
    email: "test@example.com",
    orgId,
    workspaceId,
    networks: [
      {
        network_id: networkId,
        workspace_id: workspaceId,
        name: "Network A",
        description: null,
        cidr: null,
        created_at: "2026-08-13T09:20:00Z",
      },
    ],
    devicesByNetwork: {
      [networkId]: [
        {
          device_id: "00000000-0000-0000-0000-000000000444",
          network_id: networkId,
          hostname: "edge-1",
          ip_address: null,
          device_type: "switch",
          vendor: null,
          model: null,
          location_hint: null,
          spatial_ref_id: "campus-a/building-1/floor-1/rack-2",
          status: "active",
          created_at: "2026-08-13T09:25:00Z",
        },
      ],
    },
    alerts: [],
  };
}

function normalizeAlertStatus(value: string): "active" | "acknowledged" | "resolved" {
  if (value === "ack") {
    return "acknowledged";
  }
  if (value === "acknowledged" || value === "resolved") {
    return value;
  }
  return "active";
}

function computeStatusCounts(items: MockAlertRecord[]): Record<string, number> {
  const counts = {
    active: 0,
    acknowledged: 0,
    resolved: 0,
  };
  for (const item of items) {
    const status = normalizeAlertStatus(item.status);
    counts[status] += 1;
  }
  return counts;
}

function buildAlertActionPayload(alert: MockAlertRecord, queueStatus: "queued" | "replayed") {
  return {
    ...alert,
    queue_status: queueStatus,
    stream_entry_id: queueStatus === "queued" ? `event-${Date.now()}` : null,
    warning: null,
    idempotent_replay: queueStatus === "replayed",
  };
}

export async function installSessionMocks(page: Page, state: SessionMockState): Promise<void> {
  await page.route("**/api/v1/auth/login", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          access_token: "token-1",
          refresh_token: "refresh-1",
          token_type: "bearer",
          expires_in: 900,
        },
        meta: { request_id: "req-login", timestamp: "2026-08-13T10:00:00Z" },
        errors: null,
      }),
    });
  });

  await page.route("**/api/v1/auth/me", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          user_id: state.userId,
          email: state.email,
          display_name: "Operator",
          roles: ["Admin"],
          permissions: ["execute:intent", "write:config"],
        },
        meta: { request_id: "req-profile", timestamp: "2026-08-13T10:00:01Z" },
        errors: null,
      }),
    });
  });

  await page.route("**/api/v1/organizations?page=1&page_size=20", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          items: [
            {
              org_id: state.orgId,
              name: "Org A",
              slug: "org-a",
              created_at: "2026-08-13T09:00:00Z",
            },
          ],
          total: 1,
        },
        meta: { request_id: "req-orgs", timestamp: "2026-08-13T10:00:02Z" },
        errors: null,
      }),
    });
  });

  await page.route(`**/api/v1/organizations/${state.orgId}/workspaces?page=1&page_size=20`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          items: [
            {
              workspace_id: state.workspaceId,
              org_id: state.orgId,
              name: "Workspace A",
              description: null,
              created_at: "2026-08-13T09:10:00Z",
            },
          ],
          total: 1,
        },
        meta: { request_id: "req-workspaces", timestamp: "2026-08-13T10:00:03Z" },
        errors: null,
      }),
    });
  });

  await page.route(`**/api/v1/organizations/${state.orgId}/members?page=1&page_size=20`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          items: [
            {
              org_id: state.orgId,
              user_id: state.userId,
              org_role: "Admin",
              created_at: "2026-08-13T09:00:00Z",
            },
          ],
          total: 1,
        },
        meta: { request_id: "req-members", timestamp: "2026-08-13T10:00:03Z" },
        errors: null,
      }),
    });
  });

  await page.route("**/api/v1/networks?**", async (route) => {
    const requestUrl = new URL(route.request().url());
    const workspaceId = requestUrl.searchParams.get("workspace_id");
    if (workspaceId !== state.workspaceId) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: {
            items: [],
            total: 0,
            page: Number(requestUrl.searchParams.get("page") ?? 1),
            page_size: Number(requestUrl.searchParams.get("page_size") ?? 20),
          },
          meta: { request_id: "req-networks-empty", timestamp: "2026-08-13T10:00:04Z" },
          errors: null,
        }),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          items: state.networks,
          total: state.networks.length,
          page: Number(requestUrl.searchParams.get("page") ?? 1),
          page_size: Number(requestUrl.searchParams.get("page_size") ?? 20),
        },
        meta: { request_id: "req-networks", timestamp: "2026-08-13T10:00:04Z" },
        errors: null,
      }),
    });
  });

  await page.route("**/api/v1/networks/*/devices?page=1&page_size=20", async (route) => {
    const requestUrl = new URL(route.request().url());
    const pathParts = requestUrl.pathname.split("/");
    const networkId = pathParts[4] ?? "";
    const devices = state.devicesByNetwork[networkId] ?? [];

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          items: devices,
          total: devices.length,
          page: 1,
          page_size: 20,
        },
        meta: { request_id: "req-devices", timestamp: "2026-08-13T10:00:05Z" },
        errors: null,
      }),
    });
  });

  await page.route("**/api/v1/alerts**", async (route) => {
    const request = route.request();
    const requestUrl = new URL(request.url());
    const method = request.method();
    const pathname = requestUrl.pathname;

    if (method === "GET" && pathname === "/api/v1/alerts") {
      const statusFilter = requestUrl.searchParams.get("status")?.trim().toLowerCase() ?? "";
      const severityFilter = requestUrl.searchParams.get("severity")?.trim().toLowerCase() ?? "";
      const sourceFilter = requestUrl.searchParams.get("source")?.trim().toLowerCase() ?? "";
      const correlationFilter = requestUrl.searchParams.get("correlation_id")?.trim().toLowerCase() ?? "";
      const searchFilter = requestUrl.searchParams.get("search")?.trim().toLowerCase() ?? "";
      const limitRaw = Number(requestUrl.searchParams.get("limit") ?? "200");
      const limit = Number.isFinite(limitRaw) ? Math.min(Math.max(limitRaw, 1), 500) : 200;

      const items = state.alerts
        .filter((alert) => {
          if (statusFilter && normalizeAlertStatus(alert.status) !== statusFilter) {
            return false;
          }
          if (severityFilter && String(alert.severity ?? "").toLowerCase() !== severityFilter) {
            return false;
          }
          if (sourceFilter && String(alert.source).toLowerCase() !== sourceFilter) {
            return false;
          }
          if (correlationFilter && String(alert.correlation_id).toLowerCase() !== correlationFilter) {
            return false;
          }
          if (searchFilter) {
            const haystack = JSON.stringify(alert).toLowerCase();
            return haystack.includes(searchFilter);
          }
          return true;
        })
        .sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)))
        .slice(0, limit);

      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: {
            items,
            total: items.length,
            status_counts: computeStatusCounts(items),
          },
          meta: { request_id: "req-alerts-list", timestamp: "2026-08-14T12:00:00Z" },
          errors: null,
        }),
      });
      return;
    }

    const ackMatch = pathname.match(/^\/api\/v1\/alerts\/([^/]+)\/ack$/);
    if (method === "POST" && ackMatch) {
      const alertId = ackMatch[1] ?? "";
      const target = state.alerts.find((alert) => alert.alert_id === alertId);
      if (!target) {
        await route.fulfill({
          status: 404,
          contentType: "application/json",
          body: JSON.stringify({
            success: false,
            data: null,
            meta: { request_id: "req-alert-ack-404", timestamp: "2026-08-14T12:00:00Z" },
            errors: { code: "ALERT_NOT_FOUND", message: "Alert not found." },
          }),
        });
        return;
      }

      if (target.status === "resolved") {
        await route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({
            success: false,
            data: null,
            meta: { request_id: "req-alert-ack-409", timestamp: "2026-08-14T12:00:00Z" },
            errors: {
              code: "ALERT_ALREADY_RESOLVED",
              message: "Resolved alerts cannot be acknowledged.",
            },
          }),
        });
        return;
      }

      if (target.status === "acknowledged") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            success: true,
            data: buildAlertActionPayload(target, "replayed"),
            meta: { request_id: "req-alert-ack-replayed", timestamp: "2026-08-14T12:00:00Z" },
            errors: null,
          }),
        });
        return;
      }

      const now = "2026-08-14T12:00:00Z";
      target.status = "acknowledged";
      target.acknowledged_by_user_id = state.userId;
      target.acknowledged_at = now;
      target.updated_at = now;
      target.payload = {
        ...target.payload,
        alert_id: target.alert_id,
        alert_key: target.alert_key,
        status: "acknowledged",
        severity: target.severity,
        acknowledged_by_user_id: state.userId,
        acknowledged_at: now,
      };

      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: buildAlertActionPayload(target, "queued"),
          meta: { request_id: "req-alert-ack", timestamp: now },
          errors: null,
        }),
      });
      return;
    }

    const resolveMatch = pathname.match(/^\/api\/v1\/alerts\/([^/]+)\/resolve$/);
    if (method === "POST" && resolveMatch) {
      const alertId = resolveMatch[1] ?? "";
      const target = state.alerts.find((alert) => alert.alert_id === alertId);
      if (!target) {
        await route.fulfill({
          status: 404,
          contentType: "application/json",
          body: JSON.stringify({
            success: false,
            data: null,
            meta: { request_id: "req-alert-resolve-404", timestamp: "2026-08-14T12:00:00Z" },
            errors: { code: "ALERT_NOT_FOUND", message: "Alert not found." },
          }),
        });
        return;
      }

      if (target.status === "resolved") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            success: true,
            data: buildAlertActionPayload(target, "replayed"),
            meta: { request_id: "req-alert-resolve-replayed", timestamp: "2026-08-14T12:00:00Z" },
            errors: null,
          }),
        });
        return;
      }

      const now = "2026-08-14T12:01:00Z";
      target.status = "resolved";
      target.resolved_by_user_id = state.userId;
      target.resolved_at = now;
      target.updated_at = now;
      target.payload = {
        ...target.payload,
        alert_id: target.alert_id,
        alert_key: target.alert_key,
        status: "resolved",
        severity: target.severity,
        resolved_by_user_id: state.userId,
        resolved_at: now,
      };

      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: buildAlertActionPayload(target, "queued"),
          meta: { request_id: "req-alert-resolve", timestamp: now },
          errors: null,
        }),
      });
      return;
    }

    await route.continue();
  });

  await page.route("**/ws/*", async (route) => {
    await route.abort();
  });
}

export async function loginFromUi(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByRole("button", { name: "Sign In" }).click();
  await expect(page).toHaveURL(/\/ops\/overview$/);
}
