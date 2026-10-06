import { lazyWithRetry } from "./lazyWithRetry";

// Route chunks load through lazyWithRetry: React.lazy alone caches a failed import forever.
export const LoginPage = lazyWithRetry(() => import("@/features/auth/LoginPage").then((module) => ({ default: module.LoginPage })));
export const OverviewPage = lazyWithRetry(() => import("@/features/overview/OverviewPage").then((module) => ({ default: module.OverviewPage })));
export const TenancyPage = lazyWithRetry(() => import("@/features/organizations/TenancyPage").then((module) => ({ default: module.TenancyPage })));
export const TopologyAnalysisPage = lazyWithRetry(() => import("@/features/topology/TopologyAnalysisPage").then((module) => ({ default: module.TopologyAnalysisPage })));
export const TelemetryPage = lazyWithRetry(() => import("@/features/telemetry/TelemetryPage").then((module) => ({ default: module.TelemetryPage })));
export const ReliabilityPage = lazyWithRetry(() => import("@/features/reliability/ReliabilityPage").then((module) => ({ default: module.ReliabilityPage })));
export const PluginsPage = lazyWithRetry(() => import("@/features/plugins/PluginsPage").then((module) => ({ default: module.PluginsPage })));
export const ReportsPage = lazyWithRetry(() => import("@/features/reporting/ReportsPage").then((module) => ({ default: module.ReportsPage })));
export const TwinPage = lazyWithRetry(() => import("@/features/digitalTwin/TwinPage").then((module) => ({ default: module.TwinPage })));
export const SimulationPage = lazyWithRetry(() => import("@/features/simulation/SimulationPage").then((module) => ({ default: module.SimulationPage })));
export const IntentPage = lazyWithRetry(() => import("@/features/intent/IntentPage").then((module) => ({ default: module.IntentPage })));
export const AutonomyPage = lazyWithRetry(() => import("@/features/autonomy/AutonomyPage").then((module) => ({ default: module.AutonomyPage })));
export const AuditPage = lazyWithRetry(() => import("@/features/audit/AuditPage").then((module) => ({ default: module.AuditPage })));
