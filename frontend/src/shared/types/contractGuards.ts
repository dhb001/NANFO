// Compile-time drift guards between hand-written frontend types and the
// generated backend OpenAPI schemas (ADR-028 FE-Platform items 6/7/14).
// `npm run typecheck` fails on an invented field or an incompatible backend
// shape; regenerate with `npm run api:types` after backend contract changes.
import type { AcceptsBackend, AssertContract as Ok, NoInventedFields as Only, Schema } from "@/shared/types/contracts";
import type { AuditLogEntry, AuditLogList } from "@/shared/types/audit";
import type { AlertActionResult, AlertHistoryResult, AlertListResult, AlertRecord } from "@/shared/types/alerts";
import type { TokenPair, UserProfile } from "@/shared/types/auth";
import type {
  ExecuteIntentRequest, ExecuteIntentResult, IntentConfidenceState, IntentDetailResult, IntentExplainability, IntentHistory, IntentSummary,
  IntentValidationState, ValidateIntentRequest, ValidateIntentResult,
} from "@/shared/types/intent";
import type {
  CampusBuildingList, CampusBuildingRecord, CampusModelAssetList, CampusModelAssetRecord, Device, DeviceGroupList, DeviceGroupRecord,
  DeviceList, Network, NetworkList, TopologyEdge, TopologyNode, TopologyReconcileResult,
} from "@/shared/types/network";
import type { Organization, OrganizationList, OrgMember, OrgMemberList, Workspace, WorkspaceList } from "@/shared/types/organization";
import type { PluginActionResult, PluginListResult, PluginRecord } from "@/shared/types/plugins";
import type { ReportArtifactRef, ReportGenerateResult, ReportHistoryResult, ReportRecord } from "@/shared/types/reporting";
import type {
  BranchSimulationResult, PauseSimulationResult, ScenarioValidationState, SimulationCompare, SimulationDetail, SimulationHistory,
  SimulationSummary, SimulationValidationHandoff,
} from "@/shared/types/simulation";
import type { TelemetryAggregate, TelemetryAggregationHistory, TelemetryDeviceHistory, TelemetryHealth, TelemetryHistory, TelemetryRecord } from "@/shared/types/telemetry";
import type { AutonomyConfidence, AutonomyDecision, AutonomyPendingApproval, AutonomyStatus } from "@/features/autonomy/types";
import type { Configuration, OperationalSettings } from "@/features/autonomy/configurationTypes";

export type ContractGuards = [
  // Identity / tenancy (C6: lists are {items,total}; caller_role on organizations)
  Ok<Only<TokenPair, Schema<"TokenPair">>>, Ok<AcceptsBackend<TokenPair, Schema<"TokenPair">>>,
  Ok<Only<UserProfile, Schema<"UserProfile">>>, Ok<AcceptsBackend<UserProfile, Schema<"UserProfile">>>,
  Ok<Only<Organization, Schema<"OrgResponse">>>, Ok<AcceptsBackend<Organization, Schema<"OrgResponse">>>,
  Ok<Only<OrganizationList, Schema<"OrgListResponse">>>,
  Ok<Only<Workspace, Schema<"WorkspaceResponse">>>, Ok<AcceptsBackend<Workspace, Schema<"WorkspaceResponse">>>,
  Ok<Only<WorkspaceList, Schema<"WorkspaceListResponse">>>,
  Ok<Only<OrgMember, Schema<"MemberResponse">>>, Ok<AcceptsBackend<OrgMember, Schema<"MemberResponse">>>,
  Ok<Only<OrgMemberList, Schema<"MemberListResponse">>>,
  Ok<Only<AuditLogEntry, Schema<"AuditLogEntry">>>, Ok<Only<AuditLogList, Schema<"AuditLogPage">>>,
  // Inventory / topology
  Ok<Only<Network, Schema<"NetworkResponse">>>, Ok<Only<NetworkList, Schema<"NetworkListResponse">>>,
  Ok<Only<Device, Schema<"DeviceResponse">>>, Ok<Only<DeviceList, Schema<"DeviceListResponse">>>,
  Ok<Only<TopologyNode, Schema<"TopologyNode">>>, Ok<Only<TopologyEdge, Schema<"TopologyEdge">>>,
  Ok<Only<TopologyReconcileResult, Schema<"TopologyReconcileResult">>>, Ok<AcceptsBackend<TopologyReconcileResult, Schema<"TopologyReconcileResult">>>,
  Ok<Only<CampusBuildingRecord, Schema<"CampusBuildingResponse">>>, Ok<Only<CampusBuildingList, Schema<"CampusBuildingListResponse">>>,
  Ok<Only<CampusModelAssetRecord, Schema<"CampusModelAssetResponse">>>, Ok<AcceptsBackend<CampusModelAssetRecord, Schema<"CampusModelAssetResponse">>>,
  Ok<Only<CampusModelAssetList, Schema<"CampusModelAssetListResponse">>>,
  Ok<Only<DeviceGroupRecord, Schema<"DeviceGroupResponse">>>, Ok<Only<DeviceGroupList, Schema<"DeviceGroupListResponse">>>,
  // Telemetry (C12 health slo/total_records_estimated; history total_capped)
  Ok<Only<TelemetryRecord, Schema<"TelemetryRecordResponse">>>, Ok<Only<TelemetryHistory, Schema<"TelemetryHistoryResponse">>>,
  Ok<Only<TelemetryAggregate, Schema<"TelemetryAggregateResponse">>>, Ok<Only<TelemetryAggregationHistory, Schema<"TelemetryAggregationResponse">>>,
  Ok<Only<TelemetryDeviceHistory, Schema<"TelemetryDeviceHistoryResponse">>>,
  Ok<Only<TelemetryHealth, Schema<"TelemetryHealthResponse">>>, Ok<AcceptsBackend<TelemetryHealth, Schema<"TelemetryHealthResponse">>>,
  // Workflows (C3 intents, C18 simulations)
  Ok<Only<IntentValidationState, Schema<"IntentValidationState">>>, Ok<AcceptsBackend<IntentValidationState, Schema<"IntentValidationState">>>,
  Ok<Only<IntentExplainability, Schema<"IntentExplainability">>>, Ok<AcceptsBackend<IntentExplainability, Schema<"IntentExplainability">>>,
  Ok<Only<IntentConfidenceState, Schema<"IntentConfidenceState">>>,
  Ok<Only<ValidateIntentResult, Schema<"ValidateIntentResponse">>>, Ok<AcceptsBackend<ValidateIntentResult, Schema<"ValidateIntentResponse">>>,
  Ok<Only<ExecuteIntentResult, Schema<"ExecuteIntentResponse">>>, Ok<AcceptsBackend<ExecuteIntentResult, Schema<"ExecuteIntentResponse">>>,
  Ok<Only<IntentDetailResult, Schema<"IntentDetailResponse">>>, Ok<AcceptsBackend<IntentDetailResult, Schema<"IntentDetailResponse">>>,
  Ok<Only<IntentSummary, Schema<"IntentSummary">>>, Ok<Only<IntentHistory, Schema<"IntentHistoryPage">>>,
  // Request bodies: no field the backend would reject as unknown.
  Ok<Only<ExecuteIntentRequest, Schema<"ExecuteIntentRequest">>>, Ok<Only<ValidateIntentRequest, Schema<"ValidateIntentRequest">>>,
  Ok<Only<ScenarioValidationState, Schema<"ScenarioValidationState">>>,
  Ok<Only<SimulationValidationHandoff, Schema<"SimulationValidationHandoffResponse">>>,
  Ok<Only<PauseSimulationResult, Schema<"PauseSimulationResponse">>>, Ok<Only<BranchSimulationResult, Schema<"BranchSimulationResponse">>>,
  Ok<Only<SimulationDetail, Schema<"SimulationDetailResponse">>>,
  Ok<Only<SimulationCompare, Schema<"SimulationCompareResponse">>>,
  Ok<Only<SimulationSummary, Schema<"SimulationSummary">>>, Ok<Only<SimulationHistory, Schema<"SimulationHistoryPage">>>,
  // Plugins, reports, alerts
  Ok<Only<PluginRecord, Schema<"PluginRecordResponse">>>, Ok<Only<PluginListResult, Schema<"PluginListResponse">>>,
  Ok<Only<PluginActionResult, Schema<"PluginActionResponse">>>,
  Ok<Only<ReportArtifactRef, Schema<"ReportArtifactRef">>>, Ok<Only<ReportRecord, Schema<"ReportRecordResponse">>>,
  Ok<Only<ReportGenerateResult, Schema<"ReportGenerateResponse">>>, Ok<Only<ReportHistoryResult, Schema<"ReportHistoryResponse">>>,
  Ok<Only<AlertRecord, Schema<"AlertRecordResponse">>>, Ok<Only<AlertListResult, Schema<"AlertListResponse">>>,
  Ok<Only<AlertActionResult, Schema<"AlertActionResponse">>>, Ok<Only<AlertHistoryResult, Schema<"AlertHistoryResponse">>>,
  // Autonomy (C17 typed confidence, C25 pending approval)
  Ok<Only<AutonomyStatus, Schema<"AutonomyResponse">>>, Ok<Only<AutonomyDecision, Schema<"DecisionResponse">>>,
  Ok<Only<AutonomyConfidence, Schema<"Confidence">>>, Ok<AcceptsBackend<AutonomyConfidence, Schema<"Confidence">>>,
  Ok<Only<AutonomyPendingApproval, Schema<"PendingApproval">>>, Ok<AcceptsBackend<AutonomyPendingApproval, Schema<"PendingApproval">>>,
  Ok<Only<Configuration, Schema<"ConfigurationResponse">>>,
  Ok<Only<OperationalSettings, Schema<"OperationalSettings">>>, Ok<AcceptsBackend<OperationalSettings, Schema<"OperationalSettings">>>,
];
