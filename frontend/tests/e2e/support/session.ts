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

export interface MockPluginRecord {
  plugin_id: string;
  plugin_key: string;
  name: string;
  version: string;
  manifest: Record<string, unknown>;
  signature_status: string;
  dependency_status: string;
  sandbox_status: string;
  status: "installed" | "enabled" | "disabled" | "failed";
  enabled: boolean;
  failure_reason: string | null;
  queue_status: "queued" | "replayed" | "deferred";
  stream_entry_id: string | null;
  warning: string | null;
  installed_at: string;
  updated_at: string;
}

export interface MockReportArtifactRef {
  artifact_id: string;
  uri: string;
  media_type: string;
  checksum_sha256: string;
  size_bytes: number;
  generated_at: string;
}

export interface MockReportRecord {
  report_id: string;
  workspace_id: string;
  network_id: string | null;
  report_type: string;
  format: string;
  status: "requested" | "generated" | "failed";
  date_range: {
    start: string;
    end: string;
  };
  scope: Record<string, unknown>;
  filters: Record<string, unknown>;
  artifacts: MockReportArtifactRef[];
  error: {
    code: string;
    message: string;
    [key: string]: unknown;
  } | null;
  queue_status: "queued" | "deferred" | "replayed";
  stream_entry_id: string | null;
  warning: string | null;
  idempotency_key: string | null;
  correlation_id: string;
  requested_by_user_id: string;
  requested_at: string;
  completed_at: string | null;
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
  plugins: MockPluginRecord[];
  reports: MockReportRecord[];
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
    plugins: [],
    reports: [],
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

const TRUSTED_PLUGIN_SIGNERS = new Set(["nanfo-labs", "partner-signed"]);
const ALLOWED_PLUGIN_ISOLATION = new Set(["process", "container"]);
const ALLOWED_PLUGIN_PERMISSIONS = new Set([
  "read:telemetry",
  "read:topology",
  "read:alerts",
]);

function normalizePluginStatus(value: string): "installed" | "enabled" | "disabled" | "failed" {
  const normalized = String(value).trim().toLowerCase();
  if (normalized === "enabled" || normalized === "disabled" || normalized === "failed") {
    return normalized;
  }
  return "installed";
}

function computePluginStatusCounts(items: MockPluginRecord[]): Record<string, number> {
  const counts = {
    installed: 0,
    enabled: 0,
    disabled: 0,
    failed: 0,
  };
  for (const item of items) {
    const status = normalizePluginStatus(item.status);
    counts[status] += 1;
  }
  return counts;
}

function buildPluginActionPayload(plugin: MockPluginRecord, queueStatus: "queued" | "replayed" | "deferred") {
  return {
    ...plugin,
    queue_status: queueStatus,
    stream_entry_id: queueStatus === "queued" ? `plugin-${Date.now()}` : null,
    warning: queueStatus === "deferred" ? "event_queue_unavailable" : null,
    idempotent_replay: queueStatus === "replayed",
  };
}

function nextPluginId(state: SessionMockState): string {
  const serial = String(state.plugins.length + 901).padStart(12, "0");
  return `00000000-0000-0000-0000-${serial}`;
}

function parsePluginManifest(payload: unknown): {
  pluginKey: string;
  name: string;
  version: string;
  signer: string;
  signature: string;
  dependencies: Record<string, unknown>;
  sandbox: Record<string, unknown>;
  metadata: Record<string, unknown>;
} {
  const body = typeof payload === "object" && payload !== null
    ? payload as Record<string, unknown>
    : {};
  const dependencies = typeof body.dependencies === "object" && body.dependencies !== null
    ? body.dependencies as Record<string, unknown>
    : {};
  const sandbox = typeof body.sandbox === "object" && body.sandbox !== null
    ? body.sandbox as Record<string, unknown>
    : {};
  const metadata = typeof body.metadata === "object" && body.metadata !== null
    ? body.metadata as Record<string, unknown>
    : {};

  return {
    pluginKey: String(body.plugin_key ?? "").trim().toLowerCase(),
    name: String(body.name ?? "").trim(),
    version: String(body.version ?? "").trim(),
    signer: String(body.signer ?? "").trim(),
    signature: String(body.signature ?? "").trim(),
    dependencies,
    sandbox,
    metadata,
  };
}

function validatePluginSignature(signer: string, signature: string): { code: string; message: string; status: number } | null {
  const normalizedSigner = signer.trim().toLowerCase();
  if (!normalizedSigner || !TRUSTED_PLUGIN_SIGNERS.has(normalizedSigner)) {
    return {
      code: "PLUGIN_SIGNATURE_INVALID",
      message: "Plugin signer is not trusted.",
      status: 400,
    };
  }
  if (!signature.startsWith("sig:")) {
    return {
      code: "PLUGIN_SIGNATURE_INVALID",
      message: "Plugin signature format is invalid.",
      status: 400,
    };
  }
  if (signature.length < 16) {
    return {
      code: "PLUGIN_SIGNATURE_INVALID",
      message: "Plugin signature is too short.",
      status: 400,
    };
  }
  return null;
}

function validatePluginDependencies(dependencies: Record<string, unknown>): { code: string; message: string; status: number } | null {
  const platformVersion = String(
    dependencies.platform_version
      ?? dependencies.requires_platform
      ?? "",
  ).trim();
  if (platformVersion && platformVersion !== "0.1.0") {
    return {
      code: "PLUGIN_DEPENDENCY_INCOMPATIBLE",
      message: "Plugin dependency requirements are incompatible with this runtime.",
      status: 409,
    };
  }

  const requires = dependencies.requires;
  if (requires !== undefined && !Array.isArray(requires)) {
    return {
      code: "PLUGIN_DEPENDENCY_INVALID",
      message: "Plugin requires must be a list when provided.",
      status: 400,
    };
  }

  if (Array.isArray(requires) && requires.length > 25) {
    return {
      code: "PLUGIN_DEPENDENCY_INVALID",
      message: "Plugin declares too many dependencies.",
      status: 400,
    };
  }

  return null;
}

function validatePluginSandbox(sandbox: Record<string, unknown>): { code: string; message: string; status: number } | null {
  const isolationMode = String(sandbox.isolation_mode ?? "process").trim().toLowerCase();
  if (!ALLOWED_PLUGIN_ISOLATION.has(isolationMode)) {
    return {
      code: "PLUGIN_SANDBOX_INVALID",
      message: "Plugin isolation mode is not allowed.",
      status: 400,
    };
  }

  const permissions = sandbox.permissions;
  if (permissions !== undefined && !Array.isArray(permissions)) {
    return {
      code: "PLUGIN_SANDBOX_INVALID",
      message: "Plugin sandbox permissions must be a list.",
      status: 400,
    };
  }

  const requestedPermissions = Array.isArray(permissions)
    ? permissions.map((value) => String(value).trim().toLowerCase()).filter(Boolean)
    : [];
  const hasInvalidPermission = requestedPermissions.some((permission) => !ALLOWED_PLUGIN_PERMISSIONS.has(permission));
  if (hasInvalidPermission) {
    return {
      code: "PLUGIN_PERMISSION_SCOPE_INVALID",
      message: "Plugin requests sandbox permissions outside the allowed safety scope.",
      status: 403,
    };
  }

  return null;
}

function nextReportId(state: SessionMockState): string {
  const serial = String(state.reports.length + 951).padStart(12, "0");
  return `00000000-0000-0000-0000-${serial}`;
}

function normalizeReportFormat(value: unknown): "pdf" | "csv" | null {
  const normalized = String(value ?? "").trim().toLowerCase();
  if (normalized === "pdf" || normalized === "csv") {
    return normalized;
  }
  return null;
}

function isValidDateRange(dateRange: { start: string; end: string } | null): boolean {
  if (!dateRange) {
    return false;
  }
  const start = new Date(dateRange.start);
  const end = new Date(dateRange.end);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
    return false;
  }
  return start.getTime() <= end.getTime();
}

function parseReportGenerateBody(payload: unknown): {
  workspace_id: string;
  network_id: string | null;
  report_type: string;
  format: "pdf" | "csv";
  date_range: { start: string; end: string };
  scope: Record<string, unknown>;
  filters: Record<string, unknown>;
} | null {
  const body = typeof payload === "object" && payload !== null
    ? payload as Record<string, unknown>
    : null;
  if (!body) {
    return null;
  }

  const workspaceId = String(body.workspace_id ?? "").trim();
  const reportType = String(body.report_type ?? "").trim();
  const format = normalizeReportFormat(body.format);
  const networkIdRaw = body.network_id;
  const networkId = networkIdRaw == null ? null : String(networkIdRaw).trim() || null;

  const dateRangeRaw = typeof body.date_range === "object" && body.date_range !== null
    ? body.date_range as Record<string, unknown>
    : null;
  const dateRange = dateRangeRaw
    ? {
      start: String(dateRangeRaw.start ?? "").trim(),
      end: String(dateRangeRaw.end ?? "").trim(),
    }
    : null;

  const scope = typeof body.scope === "object" && body.scope !== null && !Array.isArray(body.scope)
    ? body.scope as Record<string, unknown>
    : null;
  const filters = typeof body.filters === "object" && body.filters !== null && !Array.isArray(body.filters)
    ? body.filters as Record<string, unknown>
    : null;

  if (!workspaceId || !reportType || !format || !dateRange || !scope || !filters) {
    return null;
  }

  return {
    workspace_id: workspaceId,
    network_id: networkId,
    report_type: reportType,
    format,
    date_range: dateRange,
    scope,
    filters,
  };
}

function reportRequestFingerprint(input: {
  network_id: string | null;
  report_type: string;
  format: string;
  date_range: { start: string; end: string };
  scope: Record<string, unknown>;
  filters: Record<string, unknown>;
}): string {
  return JSON.stringify({
    network_id: input.network_id,
    report_type: input.report_type,
    format: input.format,
    date_range: input.date_range,
    scope: input.scope,
    filters: input.filters,
  });
}

function buildReportArtifact(record: MockReportRecord, generatedAt: string): MockReportArtifactRef {
  const extension = record.format === "csv" ? "csv" : "pdf";
  const mediaType = extension === "pdf" ? "application/pdf" : "text/csv";
  return {
    artifact_id: `artifact-${record.report_id}-${extension}`,
    uri: `s3://nanfo-reports/${record.workspace_id}/${record.report_id}.${extension}`,
    media_type: mediaType,
    checksum_sha256: `sha256-${record.report_id.replace(/-/g, "").slice(0, 18)}`,
    size_bytes: extension === "pdf" ? 16384 : 8192,
    generated_at: generatedAt,
  };
}

function shouldReportFail(record: MockReportRecord): boolean {
  const filters = record.filters;
  return filters.force_fail === true || filters.fail_generation === true;
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
          permissions: ["read:topology", "read:telemetry", "execute:intent", "write:config"],
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

  await page.route("**/api/v1/plugins**", async (route) => {
    const request = route.request();
    const requestUrl = new URL(request.url());
    const method = request.method();
    const pathname = requestUrl.pathname;

    if (method === "GET" && pathname === "/api/v1/plugins") {
      const statusFilter = requestUrl.searchParams.get("status")?.trim().toLowerCase() ?? "";
      const enabledFilter = requestUrl.searchParams.get("enabled")?.trim().toLowerCase() ?? "";
      const searchFilter = requestUrl.searchParams.get("search")?.trim().toLowerCase() ?? "";
      const limitRaw = Number(requestUrl.searchParams.get("limit") ?? "200");
      const limit = Number.isFinite(limitRaw) ? Math.min(Math.max(limitRaw, 1), 500) : 200;

      if (statusFilter && !["installed", "enabled", "disabled", "failed"].includes(statusFilter)) {
        await route.fulfill({
          status: 400,
          contentType: "application/json",
          body: JSON.stringify({
            success: false,
            data: null,
            meta: { request_id: "req-plugins-list-400", timestamp: "2026-08-14T12:00:00Z" },
            errors: {
              code: "PLUGIN_STATUS_INVALID",
              message: "status must be one of: installed, enabled, disabled, failed.",
            },
          }),
        });
        return;
      }

      let enabledPredicate: boolean | null = null;
      if (enabledFilter) {
        if (["1", "true", "yes", "y"].includes(enabledFilter)) {
          enabledPredicate = true;
        } else if (["0", "false", "no", "n"].includes(enabledFilter)) {
          enabledPredicate = false;
        } else {
          await route.fulfill({
            status: 400,
            contentType: "application/json",
            body: JSON.stringify({
              success: false,
              data: null,
              meta: { request_id: "req-plugins-enabled-400", timestamp: "2026-08-14T12:00:00Z" },
              errors: {
                code: "PLUGIN_ENABLED_FILTER_INVALID",
                message: "enabled must be a boolean value.",
              },
            }),
          });
          return;
        }
      }

      const items = state.plugins
        .filter((plugin) => {
          const normalizedStatus = normalizePluginStatus(plugin.status);
          if (statusFilter && normalizedStatus !== statusFilter) {
            return false;
          }
          if (enabledPredicate !== null && plugin.enabled !== enabledPredicate) {
            return false;
          }
          if (searchFilter) {
            const haystack = JSON.stringify(plugin).toLowerCase();
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
            status_counts: computePluginStatusCounts(items),
          },
          meta: { request_id: "req-plugins-list", timestamp: "2026-08-14T12:00:00Z" },
          errors: null,
        }),
      });
      return;
    }

    if (method === "POST" && pathname === "/api/v1/plugins/install") {
      const manifest = parsePluginManifest(request.postDataJSON());

      const existing = state.plugins.find((plugin) => plugin.plugin_key === manifest.pluginKey);
      if (existing) {
        if (existing.version === manifest.version) {
          await route.fulfill({
            status: 201,
            contentType: "application/json",
            body: JSON.stringify({
              success: true,
              data: buildPluginActionPayload(existing, "replayed"),
              meta: { request_id: "req-plugin-install-replayed", timestamp: "2026-08-14T12:00:00Z" },
              errors: null,
            }),
          });
          return;
        }

        await route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({
            success: false,
            data: null,
            meta: { request_id: "req-plugin-install-409", timestamp: "2026-08-14T12:00:00Z" },
            errors: {
              code: "PLUGIN_VERSION_CONFLICT",
              message: "plugin_key is already registered with a different version.",
            },
          }),
        });
        return;
      }

      const signatureFailure = validatePluginSignature(manifest.signer, manifest.signature);
      if (signatureFailure) {
        await route.fulfill({
          status: signatureFailure.status,
          contentType: "application/json",
          body: JSON.stringify({
            success: false,
            data: null,
            meta: { request_id: "req-plugin-install-signature", timestamp: "2026-08-14T12:00:00Z" },
            errors: {
              code: signatureFailure.code,
              message: signatureFailure.message,
            },
          }),
        });
        return;
      }

      const dependencyFailure = validatePluginDependencies(manifest.dependencies);
      if (dependencyFailure) {
        await route.fulfill({
          status: dependencyFailure.status,
          contentType: "application/json",
          body: JSON.stringify({
            success: false,
            data: null,
            meta: { request_id: "req-plugin-install-dependencies", timestamp: "2026-08-14T12:00:00Z" },
            errors: {
              code: dependencyFailure.code,
              message: dependencyFailure.message,
            },
          }),
        });
        return;
      }

      const sandboxFailure = validatePluginSandbox(manifest.sandbox);
      if (sandboxFailure) {
        await route.fulfill({
          status: sandboxFailure.status,
          contentType: "application/json",
          body: JSON.stringify({
            success: false,
            data: null,
            meta: { request_id: "req-plugin-install-sandbox", timestamp: "2026-08-14T12:00:00Z" },
            errors: {
              code: sandboxFailure.code,
              message: sandboxFailure.message,
            },
          }),
        });
        return;
      }

      const now = "2026-08-14T12:00:00Z";
      const created: MockPluginRecord = {
        plugin_id: nextPluginId(state),
        plugin_key: manifest.pluginKey,
        name: manifest.name,
        version: manifest.version,
        manifest: {
          plugin_key: manifest.pluginKey,
          name: manifest.name,
          version: manifest.version,
          signer: manifest.signer,
          signature: manifest.signature,
          dependencies: manifest.dependencies,
          sandbox: manifest.sandbox,
          metadata: manifest.metadata,
        },
        signature_status: "verified",
        dependency_status: "compatible",
        sandbox_status: "isolated",
        status: "installed",
        enabled: false,
        failure_reason: null,
        queue_status: "queued",
        stream_entry_id: `plugin-${Date.now()}`,
        warning: null,
        installed_at: now,
        updated_at: now,
      };
      state.plugins.unshift(created);

      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: buildPluginActionPayload(created, "queued"),
          meta: { request_id: "req-plugin-install", timestamp: now },
          errors: null,
        }),
      });
      return;
    }

    const enableMatch = pathname.match(/^\/api\/v1\/plugins\/([^/]+)\/enable$/);
    if (method === "POST" && enableMatch) {
      const pluginId = enableMatch[1] ?? "";
      const target = state.plugins.find((plugin) => plugin.plugin_id === pluginId);
      if (!target) {
        await route.fulfill({
          status: 404,
          contentType: "application/json",
          body: JSON.stringify({
            success: false,
            data: null,
            meta: { request_id: "req-plugin-enable-404", timestamp: "2026-08-14T12:00:00Z" },
            errors: { code: "PLUGIN_NOT_FOUND", message: "Plugin not found." },
          }),
        });
        return;
      }

      if (target.enabled && normalizePluginStatus(target.status) === "enabled") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            success: true,
            data: buildPluginActionPayload(target, "replayed"),
            meta: { request_id: "req-plugin-enable-replayed", timestamp: "2026-08-14T12:00:00Z" },
            errors: null,
          }),
        });
        return;
      }

      const manifest = typeof target.manifest === "object" && target.manifest !== null
        ? target.manifest as Record<string, unknown>
        : {};

      const signatureFailure = validatePluginSignature(
        String(manifest.signer ?? ""),
        String(manifest.signature ?? ""),
      );
      const dependencyFailure = validatePluginDependencies(
        typeof manifest.dependencies === "object" && manifest.dependencies !== null
          ? manifest.dependencies as Record<string, unknown>
          : {},
      );
      const sandboxFailure = validatePluginSandbox(
        typeof manifest.sandbox === "object" && manifest.sandbox !== null
          ? manifest.sandbox as Record<string, unknown>
          : {},
      );

      const failure = signatureFailure ?? dependencyFailure ?? sandboxFailure;
      if (failure) {
        const now = "2026-08-14T12:02:00Z";
        target.status = "failed";
        target.enabled = false;
        target.failure_reason = failure.code;
        target.queue_status = "queued";
        target.stream_entry_id = `plugin-${Date.now()}`;
        target.warning = null;
        target.updated_at = now;
        if (signatureFailure) {
          target.signature_status = "invalid";
        }
        if (dependencyFailure) {
          target.dependency_status = "incompatible";
        }
        if (sandboxFailure) {
          target.sandbox_status = "blocked";
        }

        await route.fulfill({
          status: failure.status,
          contentType: "application/json",
          body: JSON.stringify({
            success: false,
            data: null,
            meta: { request_id: "req-plugin-enable-failure", timestamp: now },
            errors: {
              code: failure.code,
              message: failure.message,
            },
          }),
        });
        return;
      }

      const now = "2026-08-14T12:01:00Z";
      target.status = "enabled";
      target.enabled = true;
      target.failure_reason = null;
      target.signature_status = "verified";
      target.dependency_status = "compatible";
      target.sandbox_status = "isolated";
      target.queue_status = "queued";
      target.stream_entry_id = `plugin-${Date.now()}`;
      target.warning = null;
      target.updated_at = now;

      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: buildPluginActionPayload(target, "queued"),
          meta: { request_id: "req-plugin-enable", timestamp: now },
          errors: null,
        }),
      });
      return;
    }

    const disableMatch = pathname.match(/^\/api\/v1\/plugins\/([^/]+)\/disable$/);
    if (method === "POST" && disableMatch) {
      const pluginId = disableMatch[1] ?? "";
      const target = state.plugins.find((plugin) => plugin.plugin_id === pluginId);
      if (!target) {
        await route.fulfill({
          status: 404,
          contentType: "application/json",
          body: JSON.stringify({
            success: false,
            data: null,
            meta: { request_id: "req-plugin-disable-404", timestamp: "2026-08-14T12:00:00Z" },
            errors: { code: "PLUGIN_NOT_FOUND", message: "Plugin not found." },
          }),
        });
        return;
      }

      if (!target.enabled && ["disabled", "installed", "failed"].includes(normalizePluginStatus(target.status))) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            success: true,
            data: buildPluginActionPayload(target, "replayed"),
            meta: { request_id: "req-plugin-disable-replayed", timestamp: "2026-08-14T12:00:00Z" },
            errors: null,
          }),
        });
        return;
      }

      const now = "2026-08-14T12:03:00Z";
      target.status = "disabled";
      target.enabled = false;
      target.failure_reason = null;
      target.queue_status = "queued";
      target.stream_entry_id = `plugin-${Date.now()}`;
      target.warning = null;
      target.updated_at = now;

      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: buildPluginActionPayload(target, "queued"),
          meta: { request_id: "req-plugin-disable", timestamp: now },
          errors: null,
        }),
      });
      return;
    }

    await route.continue();
  });

  await page.route("**/api/v1/reports/**", async (route) => {
    const request = route.request();
    const requestUrl = new URL(request.url());
    const method = request.method();
    const pathname = requestUrl.pathname;

    if (method === "POST" && pathname === "/api/v1/reports/generate") {
      const payload = parseReportGenerateBody(request.postDataJSON());
      if (!payload) {
        await route.fulfill({
          status: 400,
          contentType: "application/json",
          body: JSON.stringify({
            success: false,
            data: null,
            meta: { request_id: "req-report-generate-400", timestamp: "2026-08-14T12:00:00Z" },
            errors: {
              code: "REPORT_REQUEST_INVALID",
              message: "Report request payload is invalid.",
            },
          }),
        });
        return;
      }

      if (payload.workspace_id !== state.workspaceId) {
        await route.fulfill({
          status: 404,
          contentType: "application/json",
          body: JSON.stringify({
            success: false,
            data: null,
            meta: { request_id: "req-report-workspace-404", timestamp: "2026-08-14T12:00:00Z" },
            errors: {
              code: "WORKSPACE_NOT_FOUND",
              message: "Workspace not found.",
            },
          }),
        });
        return;
      }

      if (payload.network_id && !state.networks.some((network) => network.network_id === payload.network_id)) {
        await route.fulfill({
          status: 404,
          contentType: "application/json",
          body: JSON.stringify({
            success: false,
            data: null,
            meta: { request_id: "req-report-network-404", timestamp: "2026-08-14T12:00:00Z" },
            errors: {
              code: "REPORT_NETWORK_NOT_FOUND",
              message: "network_id does not reference an active network.",
            },
          }),
        });
        return;
      }

      if (!isValidDateRange(payload.date_range)) {
        await route.fulfill({
          status: 400,
          contentType: "application/json",
          body: JSON.stringify({
            success: false,
            data: null,
            meta: { request_id: "req-report-date-400", timestamp: "2026-08-14T12:00:00Z" },
            errors: {
              code: "REPORT_DATE_RANGE_INVALID",
              message: "date_range.start and date_range.end must be valid timestamps with start <= end.",
            },
          }),
        });
        return;
      }

      const idempotencyKey = request.headers()["idempotency-key"]?.trim() ?? "";
      const fingerprint = reportRequestFingerprint(payload);
      const existing = idempotencyKey
        ? state.reports.find((report) => report.workspace_id === payload.workspace_id && report.idempotency_key === idempotencyKey)
        : null;

      if (existing) {
        const existingFingerprint = reportRequestFingerprint(existing);
        if (existingFingerprint !== fingerprint) {
          await route.fulfill({
            status: 409,
            contentType: "application/json",
            body: JSON.stringify({
              success: false,
              data: null,
              meta: { request_id: "req-report-idempotency-409", timestamp: "2026-08-14T12:00:00Z" },
              errors: {
                code: "REPORT_IDEMPOTENCY_CONFLICT",
                message: "idempotency_key is already bound to a different report request.",
              },
            }),
          });
          return;
        }

        await route.fulfill({
          status: 202,
          contentType: "application/json",
          body: JSON.stringify({
            success: true,
            data: {
              ...existing,
              idempotent_replay: true,
              queue_status: existing.queue_status,
            },
            meta: { request_id: "req-report-generate-replayed", timestamp: "2026-08-14T12:00:00Z" },
            errors: null,
          }),
        });
        return;
      }

      const now = "2026-08-14T12:00:00Z";
      const reportId = nextReportId(state);
      const shouldFail = shouldReportFail({
        report_id: reportId,
        workspace_id: payload.workspace_id,
        network_id: payload.network_id,
        report_type: payload.report_type,
        format: payload.format,
        status: "requested",
        date_range: payload.date_range,
        scope: payload.scope,
        filters: payload.filters,
        artifacts: [],
        error: null,
        queue_status: "queued",
        stream_entry_id: null,
        warning: null,
        idempotency_key: idempotencyKey || null,
        correlation_id: `corr-${Date.now()}`,
        requested_by_user_id: state.userId,
        requested_at: now,
        completed_at: null,
        created_at: now,
        updated_at: now,
      });

      const queuedStatus: MockReportRecord["status"] = shouldFail ? "failed" : "generated";
      const terminalTime = "2026-08-14T12:00:05Z";
      const seedRecord: MockReportRecord = {
        report_id: reportId,
        workspace_id: payload.workspace_id,
        network_id: payload.network_id,
        report_type: payload.report_type,
        format: payload.format,
        status: queuedStatus,
        date_range: payload.date_range,
        scope: payload.scope,
        filters: payload.filters,
        artifacts: shouldFail ? [] : [buildReportArtifact({
          report_id: reportId,
          workspace_id: payload.workspace_id,
          network_id: payload.network_id,
          report_type: payload.report_type,
          format: payload.format,
          status: queuedStatus,
          date_range: payload.date_range,
          scope: payload.scope,
          filters: payload.filters,
          artifacts: [],
          error: null,
          queue_status: "queued",
          stream_entry_id: null,
          warning: null,
          idempotency_key: idempotencyKey || null,
          correlation_id: `corr-${Date.now()}`,
          requested_by_user_id: state.userId,
          requested_at: now,
          completed_at: null,
          created_at: now,
          updated_at: now,
        }, terminalTime)],
        error: shouldFail
          ? {
            code: "REPORT_GENERATION_FAILED",
            message: "Report generation failed during queue processing.",
          }
          : null,
        queue_status: "queued",
        stream_entry_id: "report-1000-0",
        warning: null,
        idempotency_key: idempotencyKey || null,
        correlation_id: `corr-${Date.now()}`,
        requested_by_user_id: state.userId,
        requested_at: now,
        completed_at: terminalTime,
        created_at: now,
        updated_at: terminalTime,
      };

      state.reports.unshift(seedRecord);

      const requestedView = {
        ...seedRecord,
        status: "requested",
        artifacts: [],
        error: null,
        completed_at: null,
        updated_at: now,
      };

      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: {
            ...requestedView,
            idempotent_replay: false,
          },
          meta: { request_id: "req-report-generate", timestamp: now },
          errors: null,
        }),
      });
      return;
    }

    if (method === "GET" && pathname.startsWith("/api/v1/reports/")) {
      const reportId = pathname.replace("/api/v1/reports/", "").trim();
      const workspaceId = requestUrl.searchParams.get("workspace_id")?.trim() ?? "";
      const report = state.reports.find((item) => item.report_id === reportId && item.workspace_id === workspaceId);

      if (!report) {
        await route.fulfill({
          status: 404,
          contentType: "application/json",
          body: JSON.stringify({
            success: false,
            data: null,
            meta: { request_id: "req-report-detail-404", timestamp: "2026-08-14T12:00:00Z" },
            errors: {
              code: "REPORT_NOT_FOUND",
              message: "Report not found.",
            },
          }),
        });
        return;
      }

      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: report,
          meta: { request_id: "req-report-detail", timestamp: "2026-08-14T12:00:06Z" },
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
  await page.getByLabel("Email").fill("test@example.com");
  await page.getByLabel("Password").fill("change-me");
  await page.getByRole("button", { name: "Sign In" }).click();
  await expect(page).toHaveURL(/\/ops\/overview$/);
}
