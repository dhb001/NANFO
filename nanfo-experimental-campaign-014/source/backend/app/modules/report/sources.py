"""Read-only owner-service adapters. No report-side SQL over source tables."""

from datetime import UTC, datetime

from fastapi import HTTPException

from app.modules.alert.service import AlertService
from app.modules.intent.service import IntentExecutionService
from app.modules.simulation.service import SimulationStartService
from app.modules.telemetry.service import TelemetryQueryService


class ReportSources:
    def __init__(self, db, redis):
        self.db, self.redis = db, redis

    async def revalidate(self, request, user_id):
        """Recheck referenced source authority without changing the frozen snapshot."""
        for identity in request.scope.simulation_ids:
            item = await SimulationStartService(
                db=self.db, redis=self.redis
            ).get_simulation_detail(
                simulation_id=identity,
                requested_by_user_id=user_id,
                requested_workspace_id=request.workspace_id,
                claim_org_id=None,
            )
            if request.network_id is not None and item["network_id"] != str(
                request.network_id
            ):
                raise HTTPException(403, "Source scope changed")
        for identity in request.scope.intent_ids:
            item = await IntentExecutionService(
                db=self.db, redis=self.redis
            ).get_intent_detail(
                workspace_id=request.workspace_id, intent_id=identity, user_id=user_id
            )
            if request.network_id is not None and item["network_id"] != str(
                request.network_id
            ):
                raise HTTPException(403, "Source scope changed")

    async def snapshot(self, request, user_id):
        start, end = request.date_range.start, request.date_range.end
        cap = request.filters.max_rows
        summary = request.report_type in {"executive_summary", "operational_summary"}
        sections = {}
        begun = datetime.now(UTC).isoformat()
        selected = (
            {"telemetry", "alerts", "simulation", "intent"}
            if summary
            else {request.report_type}
        )
        if "telemetry" in selected:
            result = await TelemetryQueryService(self.db).get_history(
                network_id=request.network_id,
                workspace_id=request.workspace_id,
                metric=request.filters.metric,
                page=1,
                page_size=cap,
                start_time=start,
                end_time=end,
            )
            rows = []
            for item in result.items:
                row = item.model_dump(mode="json", exclude={"tags"})
                # Only documented provenance keys, never arbitrary collector tags.
                row["provenance"] = {
                    key: item.tags[key]
                    for key in ("port_no", "peer_host", "run_id", "observation_id")
                    if key in item.tags
                    and isinstance(item.tags[key], (str, int, float))
                }
                rows.append(row)
            sections["telemetry"] = {
                "rows": rows,
                "total": result.total,
                "truncated": result.total > len(rows),
                "omissions": ["arbitrary_tags"],
                "time_field": "observed_at",
            }
        if "alerts" in selected:
            result = await AlertService(db=self.db, redis=self.redis).list_alerts(
                status_filter=request.filters.alert_status,
                severity_filter=request.filters.alert_severity,
                source_filter=None,
                correlation_id_filter=None,
                search_filter=None,
                limit=500,
                actor_user_id=user_id,
                requested_workspace_id=request.workspace_id,
                claim_org_id=None,
            )
            rows = []
            for item in result.items:
                payload = item.payload
                scope = (
                    payload.get("scope")
                    if isinstance(payload.get("scope"), dict)
                    else {}
                )
                network = payload.get("network_id", scope.get("network_id"))
                if request.network_id is not None and str(network) != str(
                    request.network_id
                ):
                    continue
                if not start <= item.created_at < end:
                    continue
                # Alert payload/title are free JSON; export lifecycle identity, not secrets.
                row = item.model_dump(mode="json", exclude={"payload", "alert_key"})
                row["measurement"] = {
                    key: payload[key]
                    for key in ("value", "observed_value", "threshold", "sample_count")
                    if key in payload and type(payload[key]) in (int, float)
                }
                row["measurement"].update(
                    {
                        key: payload[key]
                        for key, allowed in {
                            "unit": {"%", "percent", "ms", "bytes"},
                            "quality": {"measured", "synthetic", "unknown"},
                            "execution_mode": {"demo", "emulation", "production"},
                        }.items()
                        if isinstance(payload.get(key), str) and payload[key] in allowed
                    }
                )
                rows.append(row)
            sections["alerts"] = {
                "rows": rows[:cap],
                "total": None,
                "truncated": len(rows) > cap or len(result.items) >= 500,
                "omissions": [
                    "arbitrary_payload",
                    "source_list_is_bounded_no_complete_history_guarantee",
                ],
                "time_field": "created_at",
                "source_limit": 500,
            }
        for section, ids in (
            ("simulation", request.scope.simulation_ids),
            ("intent", request.scope.intent_ids),
        ):
            if section not in selected:
                continue
            rows, omitted = [], []
            for identity in ids:
                if section == "simulation":
                    item = await SimulationStartService(
                        db=self.db, redis=self.redis
                    ).get_simulation_detail(
                        simulation_id=identity,
                        requested_by_user_id=user_id,
                        requested_workspace_id=request.workspace_id,
                        claim_org_id=None,
                    )
                else:
                    item = await IntentExecutionService(
                        db=self.db, redis=self.redis
                    ).get_intent_detail(
                        workspace_id=request.workspace_id,
                        intent_id=identity,
                        user_id=user_id,
                    )
                if request.network_id is not None and str(
                    item.get("network_id")
                ) != str(request.network_id):
                    raise HTTPException(
                        404,
                        detail={
                            "code": "REPORT_SOURCE_NOT_FOUND",
                            "message": "Source outside report scope.",
                        },
                    )
                if not start <= datetime.fromisoformat(item["requested_at"]) < end:
                    omitted.append(f"{identity}:outside_date_range")
                    continue
                keys = (
                    f"{section}_id",
                    "network_id",
                    "workspace_id",
                    "status",
                    "state",
                    "requested_at",
                    "completed_at",
                    "input_sha256",
                    "checkpoint_sha256",
                    "revision",
                    "risk_gate",
                    "intent_kind",
                )
                row = {key: item[key] for key in keys if key in item}
                if section == "simulation":
                    output = item.get("run_output", {})
                    row["modeled_metrics"] = {
                        key: value
                        for key, value in output.items()
                        if key
                        in {
                            "throughput_mbps",
                            "latency_ms",
                            "loss_pct",
                            "elapsed_ms",
                            "tick",
                            "duration_ticks",
                            "delivered_bytes",
                            "dropped_bytes",
                            "offered_bytes",
                        }
                        and (value is None or type(value) in (int, float))
                    }
                    row["provenance"] = (
                        "configured_model"
                        if item.get("input_sha256")
                        else "unavailable"
                    )
                    row["model_evidence"] = {
                        key: output[key]
                        for key in (
                            "model_version",
                            "workload_sha256",
                            "output_sha256",
                            "source",
                            "physical_safety_authorized",
                            "latency_definition",
                        )
                        if key in output
                    }
                    row["model_omissions"] = [
                        "per_flow_metrics",
                        "tick_trace",
                        "scenario_config",
                    ]
                else:
                    evidence = item.get("execution_provenance", {})
                    row["evidence"] = {
                        key: evidence[key]
                        for key in (
                            "executor",
                            "phase",
                            "execution_id",
                            "plan_hash",
                            "binding_digest",
                            "status",
                        )
                        if key in evidence
                    }
                    plan = evidence.get("approved_plan")
                    if plan is not None:
                        from app.modules.intent.lab import LabPlan

                        row["action"] = LabPlan.model_validate(plan).model_dump(
                            mode="json"
                        )
                    row["evidence_omissions"] = [
                        "free_text",
                        "raw_execution_payload",
                        "credentials",
                        "untyped_verification",
                    ]
                rows.append(row)
            sections[section] = {
                "rows": rows[:cap],
                "total": len(rows),
                "truncated": len(rows) > cap,
                "omissions": omitted
                + (["explicit_ids_required_no_discovery"] if not ids else []),
                "time_field": "requested_at",
            }
        return {
            "version": 1,
            "request": request.model_dump(mode="json"),
            "capture_started_at": begun,
            "capture_completed_at": datetime.now(UTC).isoformat(),
            "consistency": "bounded_owner_service_reads_at_request_time; not_a_cross_store_atomic_snapshot",
            "sections": sections,
        }
