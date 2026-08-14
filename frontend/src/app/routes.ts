import { lazy } from "react";

export const LoginPage = lazy(() => import("@/features/auth/LoginPage").then((module) => ({ default: module.LoginPage })));
export const OverviewPage = lazy(() => import("@/features/overview/OverviewPage").then((module) => ({ default: module.OverviewPage })));
export const TenancyPage = lazy(() => import("@/features/organizations/TenancyPage").then((module) => ({ default: module.TenancyPage })));
export const TopologyAnalysisPage = lazy(() => import("@/features/topology/TopologyAnalysisPage").then((module) => ({ default: module.TopologyAnalysisPage })));
export const TelemetryPage = lazy(() => import("@/features/telemetry/TelemetryPage").then((module) => ({ default: module.TelemetryPage })));
export const ReliabilityPage = lazy(() => import("@/features/reliability/ReliabilityPage").then((module) => ({ default: module.ReliabilityPage })));
export const PluginsPage = lazy(() => import("@/features/plugins/PluginsPage").then((module) => ({ default: module.PluginsPage })));
export const ReportsPage = lazy(() => import("@/features/reporting/ReportsPage").then((module) => ({ default: module.ReportsPage })));
export const TwinPage = lazy(() => import("@/features/digitalTwin/TwinPage").then((module) => ({ default: module.TwinPage })));
export const SimulationPage = lazy(() => import("@/features/simulation/SimulationPage").then((module) => ({ default: module.SimulationPage })));
export const IntentPage = lazy(() => import("@/features/intent/IntentPage").then((module) => ({ default: module.IntentPage })));
export const AuditPage = lazy(() => import("@/features/audit/AuditPage").then((module) => ({ default: module.AuditPage })));
