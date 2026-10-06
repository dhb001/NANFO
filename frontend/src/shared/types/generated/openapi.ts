/**
 * GENERATED FILE - do not edit.
 * Source: backend FastAPI schema (app.main:app.openapi(), APP_ENV=test) via openapi-typescript.
 * Regenerate with `npm run api:types`; `npm run api:check` fails when it drifts from the backend.
 */
export interface paths {
    "/ready": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Ready */
        get: operations["ready_ready_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/login": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Login */
        post: operations["login_api_v1_auth_login_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/logout": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Logout */
        post: operations["logout_api_v1_auth_logout_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/refresh": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Refresh */
        post: operations["refresh_api_v1_auth_refresh_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/me": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Me */
        get: operations["me_api_v1_auth_me_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/autonomy": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Autonomy */
        get: operations["get_autonomy_api_v1_autonomy_get"];
        /** Set Autonomy */
        put: operations["set_autonomy_api_v1_autonomy_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/autonomy/stop": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Stop Autonomy */
        post: operations["stop_autonomy_api_v1_autonomy_stop_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/autonomy/configuration": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Configuration */
        get: operations["get_configuration_api_v1_autonomy_configuration_get"];
        /** Put Configuration */
        put: operations["put_configuration_api_v1_autonomy_configuration_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/autonomy/overrides": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Overrides */
        get: operations["get_overrides_api_v1_autonomy_overrides_get"];
        put?: never;
        /** Create Override */
        post: operations["create_override_api_v1_autonomy_overrides_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/autonomy/overrides/{override_id}/cancel": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Cancel Override */
        post: operations["cancel_override_api_v1_autonomy_overrides__override_id__cancel_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/autonomy/overrides/{override_id}/return": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Return Override */
        post: operations["return_override_api_v1_autonomy_overrides__override_id__return_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/organizations": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Orgs */
        get: operations["list_orgs_api_v1_organizations_get"];
        put?: never;
        /** Create Org */
        post: operations["create_org_api_v1_organizations_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/organizations/{org_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Org */
        get: operations["get_org_api_v1_organizations__org_id__get"];
        put?: never;
        post?: never;
        /** Delete Org */
        delete: operations["delete_org_api_v1_organizations__org_id__delete"];
        options?: never;
        head?: never;
        /** Update Org */
        patch: operations["update_org_api_v1_organizations__org_id__patch"];
        trace?: never;
    };
    "/api/v1/organizations/{org_id}/workspaces": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Workspaces */
        get: operations["list_workspaces_api_v1_organizations__org_id__workspaces_get"];
        put?: never;
        /** Create Workspace */
        post: operations["create_workspace_api_v1_organizations__org_id__workspaces_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/organizations/{org_id}/workspaces/{workspace_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Workspace */
        get: operations["get_workspace_api_v1_organizations__org_id__workspaces__workspace_id__get"];
        put?: never;
        post?: never;
        /** Delete Workspace */
        delete: operations["delete_workspace_api_v1_organizations__org_id__workspaces__workspace_id__delete"];
        options?: never;
        head?: never;
        /** Update Workspace */
        patch: operations["update_workspace_api_v1_organizations__org_id__workspaces__workspace_id__patch"];
        trace?: never;
    };
    "/api/v1/organizations/{org_id}/members": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Members */
        get: operations["list_members_api_v1_organizations__org_id__members_get"];
        put?: never;
        /** Add Member */
        post: operations["add_member_api_v1_organizations__org_id__members_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/organizations/{org_id}/members/{user_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Remove Member */
        delete: operations["remove_member_api_v1_organizations__org_id__members__user_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/networks": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Networks */
        get: operations["list_networks_api_v1_networks_get"];
        put?: never;
        /** Create Network */
        post: operations["create_network_api_v1_networks_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/networks/{network_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Delete Network */
        delete: operations["delete_network_api_v1_networks__network_id__delete"];
        options?: never;
        head?: never;
        /** Update Network */
        patch: operations["update_network_api_v1_networks__network_id__patch"];
        trace?: never;
    };
    "/api/v1/networks/{network_id}/devices": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Devices */
        get: operations["list_devices_api_v1_networks__network_id__devices_get"];
        put?: never;
        /** Add Device */
        post: operations["add_device_api_v1_networks__network_id__devices_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/networks/{network_id}/devices/{device_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Delete Device */
        delete: operations["delete_device_api_v1_networks__network_id__devices__device_id__delete"];
        options?: never;
        head?: never;
        /** Update Device */
        patch: operations["update_device_api_v1_networks__network_id__devices__device_id__patch"];
        trace?: never;
    };
    "/api/v1/networks/{network_id}/campus/buildings": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Campus Buildings */
        get: operations["list_campus_buildings_api_v1_networks__network_id__campus_buildings_get"];
        put?: never;
        /** Upsert Campus Buildings */
        post: operations["upsert_campus_buildings_api_v1_networks__network_id__campus_buildings_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/networks/{network_id}/campus/model-assets": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Campus Model Assets */
        get: operations["list_campus_model_assets_api_v1_networks__network_id__campus_model_assets_get"];
        put?: never;
        /** Upsert Campus Model Assets */
        post: operations["upsert_campus_model_assets_api_v1_networks__network_id__campus_model_assets_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/networks/{network_id}/campus/model-assets/{asset_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Retire Campus Model Asset */
        delete: operations["retire_campus_model_asset_api_v1_networks__network_id__campus_model_assets__asset_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/networks/{network_id}/campus-model-assets/{asset_id}/download": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Download Campus Model Asset
         * @description Verified download (C4): digest ETag, ``If-None-Match`` -> 304, streamed body.
         */
        get: operations["download_campus_model_asset_api_v1_networks__network_id__campus_model_assets__asset_id__download_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/networks/{network_id}/device-groups": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Device Groups */
        get: operations["list_device_groups_api_v1_networks__network_id__device_groups_get"];
        put?: never;
        /** Upsert Device Groups */
        post: operations["upsert_device_groups_api_v1_networks__network_id__device_groups_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/networks/{network_id}/spatial-scene": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Spatial Scene */
        get: operations["get_spatial_scene_api_v1_networks__network_id__spatial_scene_get"];
        /** Replace Spatial Scene */
        put: operations["replace_spatial_scene_api_v1_networks__network_id__spatial_scene_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/networks/{network_id}/spatial-scene/history": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Spatial History */
        get: operations["list_spatial_history_api_v1_networks__network_id__spatial_scene_history_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/networks/{network_id}/spatial-scene/history/{revision}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Spatial Revision */
        get: operations["get_spatial_revision_api_v1_networks__network_id__spatial_scene_history__revision__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/topology/graph": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Topology Graph
         * @description Return device nodes and edges for the given network from Neo4j.
         *
         *     Eventual consistency note: Neo4j state is updated asynchronously after
         *     POST /api/v1/networks/{id}/devices via the topology consumer.
         *     A brief lag is expected and is documented behaviour (design_package risk R5).
         */
        get: operations["get_topology_graph_api_v1_topology_graph_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/topology/nodes/{device_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Topology Node With Neighbours */
        get: operations["get_topology_node_with_neighbours_api_v1_topology_nodes__device_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/topology/device/{device_id}/neighbors": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Topology Device Neighbours */
        get: operations["get_topology_device_neighbours_api_v1_topology_device__device_id__neighbors_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/topology/impact/{device_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Topology Impact */
        get: operations["get_topology_impact_api_v1_topology_impact__device_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/topology/reconcile": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Reconcile Topology */
        post: operations["reconcile_topology_api_v1_topology_reconcile_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/telemetry/history": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Telemetry History
         * @description Raw/aggregated history. Page mode totals are capped (``total_capped``); cursor mode has none.
         */
        get: operations["get_telemetry_history_api_v1_telemetry_history_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/telemetry/device/{device_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Device Telemetry */
        get: operations["get_device_telemetry_api_v1_telemetry_device__device_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/telemetry/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Telemetry Health */
        get: operations["get_telemetry_health_api_v1_telemetry_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/telemetry/paths": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Paths */
        get: operations["get_paths_api_v1_telemetry_paths_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/simulations/start": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Start Simulation */
        post: operations["start_simulation_api_v1_simulations_start_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/simulations/pause": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Pause Simulation */
        post: operations["pause_simulation_api_v1_simulations_pause_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/simulations/branch": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Branch Simulation */
        post: operations["branch_simulation_api_v1_simulations_branch_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/simulations": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Simulations */
        get: operations["list_simulations_api_v1_simulations_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/simulations/{simulation_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Simulation Detail */
        get: operations["get_simulation_detail_api_v1_simulations__simulation_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/simulations/{simulation_id}/compare/{baseline_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Compare Simulations */
        get: operations["compare_simulations_api_v1_simulations__simulation_id__compare__baseline_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/intents/validate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Validate Intent */
        post: operations["validate_intent_api_v1_intents_validate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/intents/execute": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Execute Intent */
        post: operations["execute_intent_api_v1_intents_execute_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/intents": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Intents */
        get: operations["list_intents_api_v1_intents_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/intents/{intent_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Intent */
        get: operations["get_intent_api_v1_intents__intent_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/autonomy/model": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Model */
        get: operations["get_model_api_v1_autonomy_model_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/autonomy/model/diagnose": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Diagnose Model */
        post: operations["diagnose_model_api_v1_autonomy_model_diagnose_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/plugins/{plugin_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Uninstall Plugin */
        delete: operations["uninstall_plugin_api_v1_plugins__plugin_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/plugins": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Plugins */
        get: operations["list_plugins_api_v1_plugins_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/plugins/install": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Install Plugin */
        post: operations["install_plugin_api_v1_plugins_install_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/plugins/{plugin_id}/enable": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Enable Plugin */
        post: operations["enable_plugin_api_v1_plugins__plugin_id__enable_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/plugins/{plugin_id}/disable": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Disable Plugin */
        post: operations["disable_plugin_api_v1_plugins__plugin_id__disable_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/reports/generate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Generate Report */
        post: operations["generate_report_api_v1_reports_generate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/reports": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Report History */
        get: operations["report_history_api_v1_reports_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/reports/{report_id}/download": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Download Report */
        get: operations["download_report_api_v1_reports__report_id__download_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/reports/{report_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Report */
        get: operations["get_report_api_v1_reports__report_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/alerts/{alert_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Alert */
        get: operations["get_alert_api_v1_alerts__alert_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/alerts/{alert_id}/history": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Alert History */
        get: operations["get_alert_history_api_v1_alerts__alert_id__history_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/alerts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Alerts */
        get: operations["list_alerts_api_v1_alerts_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/alerts/{alert_id}/ack": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Acknowledge Alert */
        post: operations["acknowledge_alert_api_v1_alerts__alert_id__ack_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/alerts/{alert_id}/resolve": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Resolve Alert */
        post: operations["resolve_alert_api_v1_alerts__alert_id__resolve_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/audit/logs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Audit Logs */
        get: operations["list_audit_logs_api_v1_audit_logs_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Health */
        get: operations["health_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** APIResponse[AlertActionResponse] */
        APIResponse_AlertActionResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["AlertActionResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[AlertHistoryResponse] */
        APIResponse_AlertHistoryResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["AlertHistoryResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[AlertListResponse] */
        APIResponse_AlertListResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["AlertListResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[AlertRecordResponse] */
        APIResponse_AlertRecordResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["AlertRecordResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[AuditLogPage] */
        APIResponse_AuditLogPage_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["AuditLogPage"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[AutonomyResponse] */
        APIResponse_AutonomyResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["AutonomyResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[BranchSimulationResponse] */
        APIResponse_BranchSimulationResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["BranchSimulationResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[CampusBuildingListResponse] */
        APIResponse_CampusBuildingListResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["CampusBuildingListResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[CampusModelAssetListResponse] */
        APIResponse_CampusModelAssetListResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["CampusModelAssetListResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[ConfigurationResponse] */
        APIResponse_ConfigurationResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["ConfigurationResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[DeviceGroupListResponse] */
        APIResponse_DeviceGroupListResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["DeviceGroupListResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[DeviceListResponse] */
        APIResponse_DeviceListResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["DeviceListResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[DeviceResponse] */
        APIResponse_DeviceResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["DeviceResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[IntentDetailResponse] */
        APIResponse_IntentDetailResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["IntentDetailResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[IntentHistoryPage] */
        APIResponse_IntentHistoryPage_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["IntentHistoryPage"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[MemberListResponse] */
        APIResponse_MemberListResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["MemberListResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[MemberResponse] */
        APIResponse_MemberResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["MemberResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[ModelDiagnosticRecord] */
        APIResponse_ModelDiagnosticRecord_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["ModelDiagnosticRecord"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[ModelDiagnosticsResponse] */
        APIResponse_ModelDiagnosticsResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["ModelDiagnosticsResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[NetworkListResponse] */
        APIResponse_NetworkListResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["NetworkListResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[NetworkResponse] */
        APIResponse_NetworkResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["NetworkResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[OrgListResponse] */
        APIResponse_OrgListResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["OrgListResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[OrgResponse] */
        APIResponse_OrgResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["OrgResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[OverrideListResponse] */
        APIResponse_OverrideListResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["OverrideListResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[OverrideResponse] */
        APIResponse_OverrideResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["OverrideResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[PauseSimulationResponse] */
        APIResponse_PauseSimulationResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["PauseSimulationResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[PluginActionResponse] */
        APIResponse_PluginActionResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["PluginActionResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[PluginListResponse] */
        APIResponse_PluginListResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["PluginListResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[ProbePathsResponse] */
        APIResponse_ProbePathsResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["ProbePathsResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[ReportGenerateResponse] */
        APIResponse_ReportGenerateResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["ReportGenerateResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[ReportHistoryResponse] */
        APIResponse_ReportHistoryResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["ReportHistoryResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[ReportRecordResponse] */
        APIResponse_ReportRecordResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["ReportRecordResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[SimulationCompareResponse] */
        APIResponse_SimulationCompareResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["SimulationCompareResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[SimulationDetailResponse] */
        APIResponse_SimulationDetailResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["SimulationDetailResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[SimulationHistoryPage] */
        APIResponse_SimulationHistoryPage_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["SimulationHistoryPage"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[SimulationValidationHandoffResponse] */
        APIResponse_SimulationValidationHandoffResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["SimulationValidationHandoffResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[SpatialHistoryList] */
        APIResponse_SpatialHistoryList_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["SpatialHistoryList"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[SpatialSceneDocument] */
        APIResponse_SpatialSceneDocument_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["SpatialSceneDocument"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[TelemetryDeviceHistoryResponse] */
        APIResponse_TelemetryDeviceHistoryResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["TelemetryDeviceHistoryResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[TelemetryHealthResponse] */
        APIResponse_TelemetryHealthResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["TelemetryHealthResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[TokenPair] */
        APIResponse_TokenPair_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["TokenPair"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[Union[TelemetryHistoryResponse, TelemetryAggregationResponse, TelemetryCursorResponse]] */
        APIResponse_Union_TelemetryHistoryResponse__TelemetryAggregationResponse__TelemetryCursorResponse__: {
            /** Success */
            success: boolean;
            /** Data */
            data: components["schemas"]["TelemetryHistoryResponse"] | components["schemas"]["TelemetryAggregationResponse"] | components["schemas"]["TelemetryCursorResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[UserProfile] */
        APIResponse_UserProfile_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["UserProfile"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[WorkspaceListResponse] */
        APIResponse_WorkspaceListResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["WorkspaceListResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[WorkspaceResponse] */
        APIResponse_WorkspaceResponse_: {
            /** Success */
            success: boolean;
            data: components["schemas"]["WorkspaceResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** APIResponse[dict] */
        APIResponse_dict_: {
            /** Success */
            success: boolean;
            /** Data */
            data: {
                [key: string]: unknown;
            } | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** ActionBinding */
        ActionBinding: {
            /**
             * Intent Id
             * Format: uuid
             */
            intent_id: string;
            /** Plan Sha256 */
            plan_sha256: string;
            /** Network State Sha256 */
            network_state_sha256: string;
        };
        /** AddMemberRequest */
        AddMemberRequest: {
            /**
             * User Id
             * Format: uuid
             */
            user_id: string;
            /**
             * Org Role
             * @enum {string}
             */
            org_role: "Admin" | "Operator" | "Read-Only";
        };
        /** AlertActionResponse */
        AlertActionResponse: {
            /**
             * Alert Id
             * Format: uuid
             */
            alert_id: string;
            /** Alert Key */
            alert_key: string;
            /** Source */
            source: string;
            /** Status */
            status: string;
            /** Severity */
            severity: string | null;
            /**
             * Correlation Id
             * Format: uuid
             */
            correlation_id: string;
            /** Payload */
            payload: {
                [key: string]: unknown;
            };
            /** Acknowledged By User Id */
            acknowledged_by_user_id: string | null;
            /** Resolved By User Id */
            resolved_by_user_id: string | null;
            /** Acknowledged At */
            acknowledged_at: string | null;
            /** Resolved At */
            resolved_at: string | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
            /** Queue Status */
            queue_status: string;
            /** Stream Entry Id */
            stream_entry_id?: string | null;
            /** Warning */
            warning?: string | null;
            /** Idempotent Replay */
            idempotent_replay: boolean;
        };
        /** AlertHistoryEntry */
        AlertHistoryEntry: {
            /**
             * Event Id
             * Format: uuid
             */
            event_id: string;
            /**
             * Alert Id
             * Format: uuid
             */
            alert_id: string;
            /** Event Type */
            event_type: string;
            /**
             * Correlation Id
             * Format: uuid
             */
            correlation_id: string;
            /**
             * Occurred At
             * Format: date-time
             */
            occurred_at: string;
            /** Payload */
            payload: {
                [key: string]: unknown;
            };
        };
        /** AlertHistoryResponse */
        AlertHistoryResponse: {
            /**
             * Alert Id
             * Format: uuid
             */
            alert_id: string;
            /** Items */
            items: components["schemas"]["AlertHistoryEntry"][];
            /** Total */
            total: number;
        };
        /** AlertListResponse */
        AlertListResponse: {
            /** Items */
            items?: components["schemas"]["AlertRecordResponse"][];
            /** Total */
            total: number;
            /** Status Counts */
            status_counts?: {
                [key: string]: number;
            };
        };
        /** AlertRecordResponse */
        AlertRecordResponse: {
            /**
             * Alert Id
             * Format: uuid
             */
            alert_id: string;
            /** Alert Key */
            alert_key: string;
            /** Source */
            source: string;
            /** Status */
            status: string;
            /** Severity */
            severity: string | null;
            /**
             * Correlation Id
             * Format: uuid
             */
            correlation_id: string;
            /** Payload */
            payload: {
                [key: string]: unknown;
            };
            /** Acknowledged By User Id */
            acknowledged_by_user_id: string | null;
            /** Resolved By User Id */
            resolved_by_user_id: string | null;
            /** Acknowledged At */
            acknowledged_at: string | null;
            /** Resolved At */
            resolved_at: string | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
        };
        /** AllowedPath */
        AllowedPath: {
            /** Route Id */
            route_id: string;
            /** Source */
            source: string;
            /** Destination */
            destination: string;
            /** Egress Ids */
            egress_ids: string[];
        };
        /**
         * ApprovalBinding
         * @description The exact lab identity an operator approves (ADR-028 contract 3).
         *
         *     ``plan_hash`` is the canonical SHA-256 of the normalized lab plan,
         *     ``binding_digest`` that of the trusted operator binding and ``run_id`` the
         *     observed lab run. Manual-approval lab execution must echo the server's
         *     current values or is rejected with 409 ``APPROVAL_BINDING_MISMATCH``.
         */
        ApprovalBinding: {
            /** Plan Hash */
            plan_hash: string;
            /** Binding Digest */
            binding_digest: string;
            /**
             * Run Id
             * Format: uuid
             */
            run_id: string;
        };
        /** AssetRegistration */
        AssetRegistration: {
            /**
             * Version
             * @constant
             */
            version: 1;
            translation: components["schemas"]["Position"];
            rotation: components["schemas"]["Rotation"];
            scale: components["schemas"]["RegistrationScale"];
            /**
             * Target Units
             * @constant
             */
            target_units: "m";
            /**
             * Target Up Axis
             * @constant
             */
            target_up_axis: "y";
            /** Source */
            source: string;
        };
        /** AuditLogEntry */
        AuditLogEntry: {
            /**
             * Log Id
             * Format: uuid
             */
            log_id: string;
            /** Event Type */
            event_type: string;
            /** Actor Id */
            actor_id: string | null;
            /** Resource Type */
            resource_type: string | null;
            /** Resource Id */
            resource_id: string | null;
            /** Org Id */
            org_id: string | null;
            /**
             * Correlation Id
             * Format: uuid
             */
            correlation_id: string;
            /**
             * Timestamp
             * Format: date-time
             */
            timestamp: string;
            /** Metadata */
            metadata?: {
                [key: string]: unknown;
            } | null;
        };
        /** AuditLogPage */
        AuditLogPage: {
            /** Items */
            items: components["schemas"]["AuditLogEntry"][];
            /** Total */
            total: number;
            /** Page */
            page: number;
            /** Page Size */
            page_size: number;
            /**
             * Scope
             * @default org
             * @enum {string}
             */
            scope: "org" | "platform";
        };
        /**
         * AutonomyModeMeta
         * @description Additive C25 meta: true when the PUT was recorded for a second approver, not applied.
         */
        AutonomyModeMeta: {
            /** Request Id */
            request_id: string;
            /** Timestamp */
            timestamp: string;
            /** Execution Time Ms */
            execution_time_ms?: number | null;
            /**
             * Execution Mode
             * @enum {string}
             */
            execution_mode?: "demo" | "emulation" | "production";
            /**
             * Pending Approval
             * @default false
             */
            pending_approval: boolean;
            /** Pending Approval Expires At */
            pending_approval_expires_at?: string | null;
            /** Pending Requested By User Id */
            pending_requested_by_user_id?: string | null;
        };
        /** AutonomyModeResponse */
        AutonomyModeResponse: {
            /** Success */
            success: boolean;
            data: components["schemas"]["AutonomyResponse"] | null;
            meta: components["schemas"]["AutonomyModeMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** AutonomyResponse */
        AutonomyResponse: {
            /**
             * Network Id
             * Format: uuid
             */
            network_id: string;
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
            /**
             * Mode
             * @enum {string}
             */
            mode: "monitor" | "recommend" | "autonomous";
            /**
             * Status
             * @enum {string}
             */
            status: "monitoring" | "ready" | "blocked" | "stopped" | "executing" | "uncertain";
            /** Ready */
            ready: boolean;
            /** Blocked Reasons */
            blocked_reasons: string[];
            /**
             * Online Learning
             * @default false
             * @constant
             */
            online_learning: false;
            /**
             * Production Dispatch
             * @default false
             * @constant
             */
            production_dispatch: false;
            /** Checkpoint Sha256 */
            checkpoint_sha256: string | null;
            /** Approval Expires At */
            approval_expires_at: string | null;
            /** Approved By User Id */
            approved_by_user_id: string | null;
            /** Emergency Stopped */
            emergency_stopped: boolean;
            /** Stopped At */
            stopped_at: string | null;
            /** Stopped By User Id */
            stopped_by_user_id: string | null;
            /** Active Execution Id */
            active_execution_id: string | null;
            /**
             * Cancellation Status
             * @enum {string}
             */
            cancellation_status: "none" | "requested" | "verified" | "uncertain";
            /** Revision */
            revision: number;
            providers: components["schemas"]["ProviderStatuses"];
            last_observation: components["schemas"]["Observation"] | null;
            last_decision: components["schemas"]["DecisionResponse"] | null;
            /** Decisions */
            decisions: components["schemas"]["DecisionSummary"][];
            /** History Limit */
            history_limit: number;
            /** Updated At */
            updated_at: string | null;
            pending_approval?: components["schemas"]["PendingApproval"] | null;
        };
        /** BoundHop */
        BoundHop: {
            /** Dpid */
            dpid: string;
            /** Ingress Port */
            ingress_port: number | null;
            /** Egress Port */
            egress_port: number | null;
            /** Received At */
            received_at: string | null;
            /** Sent At */
            sent_at: string | null;
            /**
             * Device Id
             * Format: uuid
             */
            device_id: string;
        };
        /** BoundPath */
        BoundPath: {
            /** Packet Id */
            packet_id: string;
            /** Icmp Id */
            icmp_id: number;
            /** Icmp Seq */
            icmp_seq: number;
            /**
             * Src Host
             * @constant
             */
            src_host: "h1";
            /**
             * Dst Host
             * @constant
             */
            dst_host: "h3";
            /**
             * Src Ip
             * @constant
             */
            src_ip: "10.77.0.1";
            /**
             * Dst Ip
             * @constant
             */
            dst_ip: "10.77.0.3";
            /** Source Timestamp */
            source_timestamp: string | null;
            /** Destination Timestamp */
            destination_timestamp: string | null;
            /**
             * Status
             * @enum {string}
             */
            status: "measured" | "partial" | "ambiguous";
            /** Observed Hops */
            observed_hops: components["schemas"]["BoundHop"][];
            /** Captured Packet Count */
            captured_packet_count: number;
            /**
             * Source Device Id
             * Format: uuid
             */
            source_device_id: string;
            /**
             * Destination Device Id
             * Format: uuid
             */
            destination_device_id: string;
        };
        /** BoxGeometry */
        BoxGeometry: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "box";
            /** Width */
            width: number;
            /** Depth */
            depth: number;
            /** Height */
            height: number;
        };
        /** BranchSimulationRequest */
        BranchSimulationRequest: {
            /**
             * Parent Simulation Id
             * Format: uuid
             */
            parent_simulation_id: string;
            /** Scenario Name */
            scenario_name: string;
            scenario_config?: components["schemas"]["ScenarioConfig"] | null;
        };
        /** BranchSimulationResponse */
        BranchSimulationResponse: {
            /** Simulation Id */
            simulation_id: string;
            /** Parent Simulation Id */
            parent_simulation_id: string;
            /** Scenario Id */
            scenario_id: string;
            /** Network Id */
            network_id: string;
            /** Scene Object Id */
            scene_object_id: string;
            /** State */
            state: string;
            /** Status */
            status: string;
            /** Risk Gate */
            risk_gate: string;
            /** Scenario Name */
            scenario_name: string;
            validation: components["schemas"]["ScenarioValidationState"];
            /** Requested At */
            requested_at: string;
            /** Correlation Id */
            correlation_id: string;
        };
        /** CampusBuildingListResponse */
        CampusBuildingListResponse: {
            /** Items */
            items: components["schemas"]["CampusBuildingResponse"][];
            /** Total */
            total: number;
        };
        /** CampusBuildingResponse */
        CampusBuildingResponse: {
            /**
             * Campus Building Id
             * Format: uuid
             */
            campus_building_id: string;
            /**
             * Network Id
             * Format: uuid
             */
            network_id: string;
            /** Building Id */
            building_id: string;
            /** Campus Key */
            campus_key: string;
            /** Building Key */
            building_key: string;
            /** Label */
            label: string;
            /** Geometry */
            geometry: string;
            /** X */
            x: number;
            /** Z */
            z: number;
            /** Base Y */
            base_y: number;
            /** Width */
            width: number;
            /** Depth */
            depth: number;
            /** Height */
            height: number;
            /** Floors */
            floors: number;
            /** Footprint */
            footprint: number[][];
            /** Wall Material */
            wall_material: string | null;
            /** Attenuation Db */
            attenuation_db: number | null;
            /** Source */
            source: string | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
        };
        /** CampusModelAssetListResponse */
        CampusModelAssetListResponse: {
            /** Items */
            items: components["schemas"]["CampusModelAssetResponse"][];
            /** Total */
            total: number;
            /** Page */
            page?: number | null;
            /** Page Size */
            page_size?: number | null;
        };
        /** CampusModelAssetResponse */
        CampusModelAssetResponse: {
            registration?: components["schemas"]["AssetRegistration"] | null;
            /**
             * Storage Backend
             * @default inline
             */
            storage_backend: string;
            /** Download Path */
            download_path?: string | null;
            /**
             * Campus Model Asset Id
             * Format: uuid
             */
            campus_model_asset_id: string;
            /**
             * Network Id
             * Format: uuid
             */
            network_id: string;
            /** Model File Name */
            model_file_name: string;
            /** Model Mime Type */
            model_mime_type: string;
            /** Model Data Base64 */
            model_data_base64?: string | null;
            /** Model Sha256 */
            model_sha256: string;
            /** Model Size Bytes */
            model_size_bytes: number;
            /** Mapping By Device Id */
            mapping_by_device_id: {
                [key: string]: string;
            };
            /** Source */
            source: string | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
        };
        /** CandidateBounds */
        CandidateBounds: {
            /** Network Id */
            network_id: string;
            /** Run Id */
            run_id: string;
            /** Snapshot Id */
            snapshot_id: string;
            /** Action Id */
            action_id: string;
            /** Calibration Id */
            calibration_id: string;
            /** Provider Id */
            provider_id: string;
            /**
             * Model Version
             * @constant
             */
            model_version: "bounded-fluid-v1";
            /** Policy Version */
            policy_version: string;
            /** Input Sha256 */
            input_sha256: string;
            /** Observed At Unix Seconds */
            observed_at_unix_seconds: number;
            /** Valid Until Unix Seconds */
            valid_until_unix_seconds: number;
            /** Dt Seconds */
            dt_seconds: number;
            /** Actuation Delay Upper Seconds */
            actuation_delay_upper_seconds: number;
            /** Queues */
            queues: components["schemas"]["QueueBounds"][];
        };
        /** Capture */
        Capture: {
            /** Capture Id */
            capture_id: string;
            /** Interface */
            interface: string;
            /**
             * Direction
             * @enum {string}
             */
            direction: "in" | "out";
            /** Dpid */
            dpid: string | null;
            /** Port No */
            port_no: number;
            /** Host */
            host: string | null;
            /** File */
            file: string;
            /** Sha256 */
            sha256: string;
            /** Size Bytes */
            size_bytes: number;
        };
        /** CapturedPacket */
        CapturedPacket: {
            /** Capture Id */
            capture_id: string;
            /** Record Index */
            record_index: number;
            /**
             * Timestamp
             * Format: date-time
             */
            timestamp: string;
            /** Icmp Id */
            icmp_id: number;
            /** Icmp Seq */
            icmp_seq: number;
            /**
             * Src Ip
             * @constant
             */
            src_ip: "10.77.0.1";
            /**
             * Dst Ip
             * @constant
             */
            dst_ip: "10.77.0.3";
            /** Payload Sha256 */
            payload_sha256: string;
            /** Packet Sha256 */
            packet_sha256: string;
        };
        /**
         * Confidence
         * @description Typed confidence carried by every AI proposal (constitution §2, ADR-028 C17).
         */
        Confidence: {
            /** Value */
            value: number;
            /** Method */
            method: string;
            /** Calibrated */
            calibrated: boolean;
            /** Calibration Id */
            calibration_id?: string | null;
        };
        /** ConfigurationResponse */
        ConfigurationResponse: {
            /**
             * Network Id
             * Format: uuid
             */
            network_id: string;
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
            /** Revision */
            revision: number;
            /** Control Revision */
            control_revision: number;
            operational: components["schemas"]["OperationalSettings"];
            requested_training: components["schemas"]["TrainingSettings"];
            effective_training?: components["schemas"]["TrainingSettings"] | null;
            /**
             * Training Status
             * @enum {string}
             */
            training_status: "not_requested" | "retraining_required";
            /**
             * Effective Training Status
             * @default model_owned_unavailable
             * @constant
             */
            effective_training_status: "model_owned_unavailable";
            /**
             * Safety Merge
             * @default stricter_than_calibrated_policy
             * @constant
             */
            safety_merge: "stricter_than_calibrated_policy";
            /**
             * Allow Uncalibrated Confidence Honoured
             * @default false
             */
            allow_uncalibrated_confidence_honoured: boolean;
            /** History */
            history: components["schemas"]["ConfigurationRevisionResponse"][];
            /**
             * History Limit
             * @default 100
             */
            history_limit: number;
        };
        /** ConfigurationRevisionResponse */
        ConfigurationRevisionResponse: {
            /** Revision */
            revision: number;
            /** Actor Id */
            actor_id: string;
            /** Reason */
            reason: string;
            operational: components["schemas"]["OperationalSettings"];
            training: components["schemas"]["TrainingSettings"];
            /** Content Sha256 */
            content_sha256: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
        };
        /** CoordinateSystem */
        CoordinateSystem: {
            /**
             * Units
             * @constant
             */
            units: "m";
            /**
             * Up Axis
             * @constant
             */
            up_axis: "y";
        };
        /** CreateDeviceRequest */
        CreateDeviceRequest: {
            /** Hostname */
            hostname: string;
            /** Ip Address */
            ip_address?: string | null;
            /** Device Type */
            device_type: string;
            /** Vendor */
            vendor?: string | null;
            /** Model */
            model?: string | null;
            /** Location Hint */
            location_hint?: string | null;
            /** Spatial Ref Id */
            spatial_ref_id?: string | null;
        };
        /** CreateNetworkRequest */
        CreateNetworkRequest: {
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
            /** Name */
            name: string;
            /** Description */
            description?: string | null;
            /** Cidr */
            cidr?: string | null;
        };
        /** CreateOrgRequest */
        CreateOrgRequest: {
            /** Name */
            name: string;
            /** Slug */
            slug: string;
        };
        /** CreateOverrideRequest */
        CreateOverrideRequest: {
            /**
             * Network Id
             * Format: uuid
             */
            network_id: string;
            /**
             * Intent Id
             * Format: uuid
             */
            intent_id: string;
            /**
             * Execution Id
             * Format: uuid
             */
            execution_id: string;
            /** Expected Revision */
            expected_revision: number;
            /** Reason */
            reason: string;
            /** Duration Seconds */
            duration_seconds: number;
            /**
             * Return Mode
             * @enum {string}
             */
            return_mode: "monitor" | "recommend" | "autonomous";
        };
        /** CreateWorkspaceRequest */
        CreateWorkspaceRequest: {
            /** Name */
            name: string;
            /** Description */
            description?: string | null;
        };
        /** DecisionResponse */
        DecisionResponse: {
            confidence?: components["schemas"]["Confidence"] | null;
            /**
             * Repeat Count
             * @default 1
             */
            repeat_count: number;
            /** Last Seen At */
            last_seen_at?: string | null;
            /**
             * Decision Id
             * Format: uuid
             */
            decision_id: string;
            /**
             * Network Id
             * Format: uuid
             */
            network_id: string;
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
            /** Actor Id */
            actor_id: string;
            /**
             * Mode
             * @enum {string}
             */
            mode: "monitor" | "recommend" | "autonomous";
            /** Control Revision */
            control_revision: number;
            /**
             * Status
             * @enum {string}
             */
            status: "observing" | "observed" | "blocked" | "recommended" | "accepted" | "verified" | "uncertain" | "cancelled" | "failed" | "control_changed" | "stopped";
            /** Reasons */
            reasons: string[];
            /** Checkpoint Sha256 */
            checkpoint_sha256: string | null;
            observation: components["schemas"]["Observation"] | null;
            proposal: components["schemas"]["Proposal"] | null;
            safety: components["schemas"]["SafetyAssessment"] | null;
            /** Evidence */
            evidence: string[];
            /** Execution Id */
            execution_id: string | null;
            verification: components["schemas"]["Verification"] | null;
            authorization?: components["schemas"]["ExecutionAuthorization"] | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
            /**
             * Projection
             * @default full
             * @constant
             */
            projection: "full";
        };
        /**
         * DecisionSummary
         * @description Bounded list projection of a decision (ADR-028 fix 6); `last_decision` stays full.
         */
        DecisionSummary: {
            confidence?: components["schemas"]["Confidence"] | null;
            /**
             * Repeat Count
             * @default 1
             */
            repeat_count: number;
            /** Last Seen At */
            last_seen_at?: string | null;
            /**
             * Decision Id
             * Format: uuid
             */
            decision_id: string;
            /**
             * Network Id
             * Format: uuid
             */
            network_id: string;
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
            /** Actor Id */
            actor_id: string;
            /**
             * Mode
             * @enum {string}
             */
            mode: "monitor" | "recommend" | "autonomous";
            /** Control Revision */
            control_revision: number;
            /**
             * Status
             * @enum {string}
             */
            status: "observing" | "observed" | "blocked" | "recommended" | "accepted" | "verified" | "uncertain" | "cancelled" | "failed" | "control_changed" | "stopped";
            /** Reasons */
            reasons: string[];
            /** Checkpoint Sha256 */
            checkpoint_sha256: string | null;
            observation: components["schemas"]["ObservationSummary"] | null;
            proposal: components["schemas"]["Proposal"] | null;
            safety: components["schemas"]["SafetySummary"] | null;
            /** Evidence */
            evidence: string[];
            /** Execution Id */
            execution_id: string | null;
            verification: components["schemas"]["Verification"] | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
            /**
             * Projection
             * @default summary
             * @constant
             */
            projection: "summary";
        };
        /** DemandObservation */
        DemandObservation: {
            /** Demand Id */
            demand_id: string;
            /** Source */
            source: string;
            /** Destination */
            destination: string;
            /** Arrival Lower Bytes Per Second */
            arrival_lower_bytes_per_second: number;
            /** Arrival Upper Bytes Per Second */
            arrival_upper_bytes_per_second: number;
        };
        /** DemandRoute */
        DemandRoute: {
            /** Demand Id */
            demand_id: string;
            /** Route Id */
            route_id: string;
        };
        /** DeviceGroupListResponse */
        DeviceGroupListResponse: {
            /** Items */
            items: components["schemas"]["DeviceGroupResponse"][];
            /** Total */
            total: number;
        };
        /** DeviceGroupResponse */
        DeviceGroupResponse: {
            /**
             * Device Group Id
             * Format: uuid
             */
            device_group_id: string;
            /**
             * Network Id
             * Format: uuid
             */
            network_id: string;
            /** Group Key */
            group_key: string;
            /** Name */
            name: string;
            /** Group Type */
            group_type: string;
            /** Description */
            description: string | null;
            /** Selector */
            selector: {
                [key: string]: string;
            };
            /** Device Ids */
            device_ids: string[];
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
        };
        /** DeviceListResponse */
        DeviceListResponse: {
            /** Items */
            items: components["schemas"]["DeviceResponse"][];
            /** Total */
            total: number;
            /** Page */
            page: number;
            /** Page Size */
            page_size: number;
        };
        /** DeviceResponse */
        DeviceResponse: {
            /**
             * Device Id
             * Format: uuid
             */
            device_id: string;
            /**
             * Network Id
             * Format: uuid
             */
            network_id: string;
            /** Hostname */
            hostname: string;
            /** Ip Address */
            ip_address: string | null;
            /** Device Type */
            device_type: string;
            /** Vendor */
            vendor: string | null;
            /** Model */
            model: string | null;
            /** Location Hint */
            location_hint: string | null;
            /** Spatial Ref Id */
            spatial_ref_id: string | null;
            /** Status */
            status: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
        };
        /** DiagnoseModelRequest */
        DiagnoseModelRequest: {
            /**
             * Network Id
             * Format: uuid
             */
            network_id: string;
            /** History Reference */
            history_reference: string;
        };
        /** DiagnosticResult */
        DiagnosticResult: {
            /** Model Id */
            model_id: string;
            /** Checkpoint Id */
            checkpoint_id: string;
            /** History Reference */
            history_reference: string;
            /** Registry Sha256 */
            registry_sha256: string;
            /** Policy Sha256 */
            policy_sha256: string;
            /** Checkpoint Weights Sha256 */
            checkpoint_weights_sha256: string;
            /** Source Sha256 */
            source_sha256: string;
            /** History Sha256 */
            history_sha256: string;
            /** Input Sha256 */
            input_sha256: string;
            /** Contract Hash */
            contract_hash: string;
            /** Spec Hash */
            spec_hash: string;
            /**
             * Action
             * @enum {integer}
             */
            action: 0 | 1;
            /** Action Path */
            action_path: string[];
            /** Probabilities */
            probabilities: number[];
            /** Value */
            value: number;
            /** Inference Seconds */
            inference_seconds: number;
            /** Artifact Validation And Inference Seconds */
            artifact_validation_and_inference_seconds: number;
            /** Subprocess Seconds */
            subprocess_seconds: number;
            /** Evidence */
            evidence: {
                [key: string]: number | number[] | null;
            }[];
            /**
             * History Kind
             * @default historical_measured_v4
             * @constant
             */
            history_kind: "historical_measured_v4";
            /**
             * Live
             * @default false
             * @constant
             */
            live: false;
            /**
             * Execution
             * @default not_applied
             * @constant
             */
            execution: "not_applied";
            /**
             * Safety Authorized
             * @default false
             * @constant
             */
            safety_authorized: false;
            /**
             * Probabilities Are Safety Confidence
             * @default false
             * @constant
             */
            probabilities_are_safety_confidence: false;
            /**
             * Benchmark Status
             * @enum {string}
             */
            benchmark_status: "qualified_scoped_benchmark" | "not_qualified";
            /** Benchmark Scope */
            benchmark_scope: string;
            /** Benchmark Limitations */
            benchmark_limitations: string[];
            /** Benchmark Evidence Sha256 */
            benchmark_evidence_sha256: string;
        };
        /** ErrorDetail */
        ErrorDetail: {
            /** Code */
            code: string;
            /** Message */
            message: string;
        };
        /** ExecuteIntentEnvelope */
        ExecuteIntentEnvelope: {
            /** Success */
            success: boolean;
            data: components["schemas"]["ExecuteIntentResponse"] | null;
            meta: components["schemas"]["IntentResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** ExecuteIntentRequest */
        ExecuteIntentRequest: {
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
            /**
             * Intent Id
             * Format: uuid
             */
            intent_id: string;
            /** Idempotency Key */
            idempotency_key?: string | null;
            /**
             * Manual Approval
             * @default false
             */
            manual_approval: boolean;
            /**
             * Cancel
             * @default false
             */
            cancel: boolean;
            /** Simulation Id */
            simulation_id?: string | null;
            approval_binding?: components["schemas"]["ApprovalBinding"] | null;
        };
        /** ExecuteIntentResponse */
        ExecuteIntentResponse: {
            /**
             * Intent Id
             * Format: uuid
             */
            intent_id: string;
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
            /** Network Id */
            network_id: string | null;
            /** Status */
            status: string;
            /** Intent Kind */
            intent_kind: string;
            /** Queue Status */
            queue_status: string;
            /** Stream Entry Id */
            stream_entry_id: string | null;
            /** Warning */
            warning: string | null;
            /** Validation Result */
            validation_result: {
                [key: string]: unknown;
            };
            /** Execution Provenance */
            execution_provenance: {
                [key: string]: unknown;
            };
            /** Explainability */
            explainability: {
                [key: string]: unknown;
            };
            confidence: components["schemas"]["IntentConfidenceState"];
            /** Idempotency Key */
            idempotency_key: string | null;
            /**
             * Correlation Id
             * Format: uuid
             */
            correlation_id: string;
            /** Requested By User Id */
            requested_by_user_id: string;
            /**
             * Requested At
             * Format: date-time
             */
            requested_at: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
            /** Idempotent Replay */
            idempotent_replay: boolean;
            approval_binding?: components["schemas"]["ApprovalBinding"] | null;
        };
        /** ExecutionAuthorization */
        ExecutionAuthorization: {
            /**
             * Decision Id
             * Format: uuid
             */
            decision_id: string;
            /**
             * Execution Id
             * Format: uuid
             */
            execution_id: string;
            /**
             * Intent Id
             * Format: uuid
             */
            intent_id: string;
            /**
             * Network Id
             * Format: uuid
             */
            network_id: string;
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
            /** Actor Id */
            actor_id: string;
            /** Checkpoint Sha256 */
            checkpoint_sha256: string;
            /**
             * Approval Expires At
             * Format: date-time
             */
            approval_expires_at: string;
            /** Control Revision */
            control_revision: number;
            /**
             * Claim Token
             * Format: uuid
             */
            claim_token: string;
            /** Safety Evidence Json */
            safety_evidence_json: string;
            /** Selected Action Json */
            selected_action_json: string;
            /** Safety Sha256 */
            safety_sha256: string;
            /** Selected Action Sha256 */
            selected_action_sha256: string;
            /** Certificate Expires At Unix Seconds */
            certificate_expires_at_unix_seconds: number;
        };
        /** FluidMetrics */
        FluidMetrics: {
            /** Offered Bytes */
            offered_bytes: number;
            /** Delivered Bytes */
            delivered_bytes: number;
            /** Dropped Bytes */
            dropped_bytes: number;
            /** Queued Bytes */
            queued_bytes: number;
            /** Inflight Bytes */
            inflight_bytes: number;
            /** Delivered Residence Byte Ms */
            delivered_residence_byte_ms: number;
            /** Loss Pct */
            loss_pct: number | null;
            /** Delivery Ratio */
            delivery_ratio: number | null;
            /** Throughput Mbps */
            throughput_mbps: number | null;
            /** Latency Ms */
            latency_ms: number | null;
        };
        /** GenerateReportRequest */
        GenerateReportRequest: {
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
            /** Network Id */
            network_id?: string | null;
            /**
             * Report Type
             * @enum {string}
             */
            report_type: "executive_summary" | "operational_summary" | "telemetry" | "alerts" | "simulation" | "intent";
            /**
             * Format
             * @enum {string}
             */
            format: "pdf" | "csv";
            date_range: components["schemas"]["ReportDateRangeRequest"];
            scope?: components["schemas"]["ReportScope"];
            filters?: components["schemas"]["ReportFilters"];
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** InitialBackground */
        InitialBackground: {
            /** Initial Bytes */
            initial_bytes: number;
            /** Queued Bytes */
            queued_bytes: number;
            /** Inflight Bytes */
            inflight_bytes: number;
            /** Delivered Bytes */
            delivered_bytes: number;
        };
        /** IntentConfidenceState */
        IntentConfidenceState: {
            /** Score */
            score: number;
            /** Band */
            band: string;
            /** Approval Required */
            approval_required: boolean;
        };
        /** IntentDetailResponse */
        IntentDetailResponse: {
            /**
             * Intent Id
             * Format: uuid
             */
            intent_id: string;
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
            /** Network Id */
            network_id: string | null;
            /** Status */
            status: string;
            /** Intent Kind */
            intent_kind: string;
            /** Intent Payload */
            intent_payload: {
                [key: string]: unknown;
            };
            /** Validation Result */
            validation_result: {
                [key: string]: unknown;
            };
            /** Execution Provenance */
            execution_provenance: {
                [key: string]: unknown;
            };
            /** Explainability */
            explainability: {
                [key: string]: unknown;
            };
            confidence: components["schemas"]["IntentConfidenceState"];
            /** Idempotency Key */
            idempotency_key: string | null;
            /** Queue Status */
            queue_status: string;
            /** Stream Entry Id */
            stream_entry_id: string | null;
            /** Warning */
            warning: string | null;
            /**
             * Correlation Id
             * Format: uuid
             */
            correlation_id: string;
            /** Requested By User Id */
            requested_by_user_id: string;
            /**
             * Requested At
             * Format: date-time
             */
            requested_at: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
            approval_binding?: components["schemas"]["ApprovalBinding"] | null;
            simulation_action_binding?: components["schemas"]["SimulationActionBinding"] | null;
        };
        /** IntentExplainability */
        IntentExplainability: {
            /** Summary */
            summary: string;
            /** Evidence */
            evidence?: string[];
            /** Alternatives Considered */
            alternatives_considered?: string[];
            /** Policy Reference */
            policy_reference: string;
        };
        /** IntentHistoryPage */
        IntentHistoryPage: {
            /** Items */
            items: components["schemas"]["IntentSummary"][];
            /** Total */
            total: number;
            /** Page */
            page: number;
            /** Page Size */
            page_size: number;
        };
        /**
         * IntentResponseMeta
         * @description Envelope meta plus ``idempotent_replay`` (true when a stored result is returned).
         */
        IntentResponseMeta: {
            /** Request Id */
            request_id: string;
            /** Timestamp */
            timestamp: string;
            /** Execution Time Ms */
            execution_time_ms?: number | null;
            /**
             * Execution Mode
             * @enum {string}
             */
            execution_mode?: "demo" | "emulation" | "production";
            /**
             * Idempotent Replay
             * @default false
             */
            idempotent_replay: boolean;
        };
        /** IntentSummary */
        IntentSummary: {
            /**
             * Intent Id
             * Format: uuid
             */
            intent_id: string;
            /** Network Id */
            network_id: string | null;
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
            /** Action */
            action: string | null;
            /** Status */
            status: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
        };
        /** IntentValidationState */
        IntentValidationState: {
            /** Is Valid */
            is_valid: boolean;
            /** Reasons */
            reasons?: components["schemas"]["ValidationReason"][];
            /** Required Checks */
            required_checks?: string[];
            /** Capability Match */
            capability_match: string;
            /** Dependency Analysis */
            dependency_analysis: string;
            /** Simulation Required */
            simulation_required: boolean;
            /** Policy Reference */
            policy_reference: string;
            /**
             * Validated At
             * Format: date-time
             */
            validated_at: string;
            /**
             * Validation Kind
             * @default baseline_schema_only
             */
            validation_kind: string;
            /**
             * Model Evidence
             * @default unavailable
             */
            model_evidence: string;
        };
        JsonValue: unknown;
        /** LinkFlowTrace */
        LinkFlowTrace: {
            /** Arrived Bytes */
            arrived_bytes: number;
            /** Dropped Bytes */
            dropped_bytes: number;
            /** Served Bytes */
            served_bytes: number;
            /** Queued Bytes */
            queued_bytes: number;
        };
        /** LinkTrace */
        LinkTrace: {
            /** Flows */
            flows: {
                [key: string]: components["schemas"]["LinkFlowTrace"];
            };
            /** Served Bytes */
            served_bytes: number;
            /** Queued Bytes */
            queued_bytes: number;
            /** Utilization */
            utilization: number;
            /** Background Queued Bytes */
            background_queued_bytes: number;
            /** Background Served Bytes */
            background_served_bytes: number;
        };
        /** LoginRequest */
        LoginRequest: {
            /**
             * Email
             * Format: email
             */
            email: string;
            /** Password */
            password: string;
        };
        /** MemberListResponse */
        MemberListResponse: {
            /** Items */
            items: components["schemas"]["MemberResponse"][];
            /** Total */
            total: number;
        };
        /** MemberResponse */
        MemberResponse: {
            /**
             * Org Id
             * Format: uuid
             */
            org_id: string;
            /**
             * User Id
             * Format: uuid
             */
            user_id: string;
            /** Org Role */
            org_role: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
        };
        /** ModelDiagnosticRecord */
        ModelDiagnosticRecord: {
            /**
             * Diagnostic Id
             * Format: uuid
             */
            diagnostic_id: string;
            /**
             * Network Id
             * Format: uuid
             */
            network_id: string;
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
            /** Actor Id */
            actor_id: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            result: components["schemas"]["DiagnosticResult"];
        };
        /** ModelDiagnosticsResponse */
        ModelDiagnosticsResponse: {
            /**
             * Network Id
             * Format: uuid
             */
            network_id: string;
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
            /**
             * Status
             * @enum {string}
             */
            status: "operator_registered" | "unavailable";
            /** Reasons */
            reasons: string[];
            model: components["schemas"]["RegisteredModelStatus"] | null;
            /** Diagnostics */
            diagnostics: components["schemas"]["ModelDiagnosticRecord"][];
            /**
             * Live History Status
             * @default unavailable
             * @constant
             */
            live_history_status: "unavailable";
            /**
             * Safety Authorized
             * @default false
             * @constant
             */
            safety_authorized: false;
            /**
             * Production Dispatch
             * @default false
             * @constant
             */
            production_dispatch: false;
        };
        /** ModeledOutput */
        ModeledOutput: {
            /** Offered Bytes */
            offered_bytes: number;
            /** Delivered Bytes */
            delivered_bytes: number;
            /** Dropped Bytes */
            dropped_bytes: number;
            /** Queued Bytes */
            queued_bytes: number;
            /** Inflight Bytes */
            inflight_bytes: number;
            /** Delivered Residence Byte Ms */
            delivered_residence_byte_ms: number;
            /** Loss Pct */
            loss_pct: number | null;
            /** Delivery Ratio */
            delivery_ratio: number | null;
            /** Throughput Mbps */
            throughput_mbps: number | null;
            /** Latency Ms */
            latency_ms: number | null;
            /**
             * Model Version
             * @constant
             */
            model_version: "finite-buffer-fluid.v1";
            /** Input Sha256 */
            input_sha256: string;
            /** Workload Sha256 */
            workload_sha256: string;
            /** Checkpoint Sha256 */
            checkpoint_sha256: string;
            /** Output Sha256 */
            output_sha256: string;
            /** Elapsed Ms */
            elapsed_ms: number;
            /** Duration Ticks */
            duration_ticks: number;
            /** Tick */
            tick: number;
            /**
             * Source
             * @constant
             */
            source: "operator_configured_model";
            /**
             * Physical Safety Authorized
             * @constant
             */
            physical_safety_authorized: false;
            /** Latency Definition */
            latency_definition: string;
            objective_checks: components["schemas"]["ObjectiveChecks"];
            /**
             * Risk Gate
             * @enum {string}
             */
            risk_gate: "passed" | "blocked";
            /** Flows */
            flows: {
                [key: string]: components["schemas"]["FluidMetrics"];
            };
            /** Initial Background */
            initial_background: {
                [key: string]: components["schemas"]["InitialBackground"];
            };
            /** Trace */
            trace: components["schemas"]["SimulationTrace"][];
        };
        /** NetworkListResponse */
        NetworkListResponse: {
            /** Items */
            items: components["schemas"]["NetworkResponse"][];
            /** Total */
            total: number;
            /** Page */
            page: number;
            /** Page Size */
            page_size: number;
        };
        /** NetworkResponse */
        NetworkResponse: {
            /**
             * Network Id
             * Format: uuid
             */
            network_id: string;
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
            /** Name */
            name: string;
            /** Description */
            description: string | null;
            /** Cidr */
            cidr: string | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
        };
        /** ObjectiveChecks */
        ObjectiveChecks: {
            /** Max Loss Pct */
            max_loss_pct: boolean;
            /** Max Latency Ms */
            max_latency_ms: boolean;
            /** Min Throughput Mbps */
            min_throughput_mbps: boolean;
        };
        /** Observation */
        Observation: {
            /**
             * Network Id
             * Format: uuid
             */
            network_id: string;
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
            /** Provider Id */
            provider_id: string;
            /** Contract */
            contract: string;
            /** Observed At */
            observed_at: string | null;
            /**
             * Collected At
             * Format: date-time
             */
            collected_at: string;
            /** Age Seconds */
            age_seconds: number | null;
            /** Fresh */
            fresh: boolean;
            /** Compatible */
            compatible: boolean;
            /** Reasons */
            reasons?: string[];
            /** Samples */
            samples?: components["schemas"]["ObservationSample"][];
            /** Evidence */
            evidence?: string[];
        };
        /** ObservationSample */
        ObservationSample: {
            /**
             * Record Id
             * Format: uuid
             */
            record_id: string;
            /**
             * Device Id
             * Format: uuid
             */
            device_id: string;
            /** Metric */
            metric: string;
            /** Value */
            value: number;
            /** Unit */
            unit: string | null;
            /**
             * Observed At
             * Format: date-time
             */
            observed_at: string;
            /** Source */
            source: string;
            /** Run Id */
            run_id: string | null;
            /** Port No */
            port_no: string | null;
        };
        /**
         * ObservationSummary
         * @description Observation without its sample payload (history lists never carry blobs).
         */
        ObservationSummary: {
            /**
             * Network Id
             * Format: uuid
             */
            network_id: string;
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
            /** Provider Id */
            provider_id: string;
            /** Contract */
            contract: string;
            /** Observed At */
            observed_at: string | null;
            /**
             * Collected At
             * Format: date-time
             */
            collected_at: string;
            /** Age Seconds */
            age_seconds: number | null;
            /** Fresh */
            fresh: boolean;
            /** Compatible */
            compatible: boolean;
            /** Reasons */
            reasons?: string[];
            /** Evidence */
            evidence?: string[];
            /** Samples */
            samples?: components["schemas"]["ObservationSample"][];
            /**
             * Sample Count
             * @default 0
             */
            sample_count: number;
        };
        /** OperationalSettings */
        OperationalSettings: {
            /**
             * Max Observation Age Seconds
             * @default 30
             */
            max_observation_age_seconds: number;
            /**
             * Decision Interval Seconds
             * @default 10
             */
            decision_interval_seconds: number;
            /**
             * Min Route Hold Seconds
             * @default 3
             */
            min_route_hold_seconds: number;
            /**
             * Max Changes Per Minute
             * @default 10
             */
            max_changes_per_minute: number;
            /**
             * Min Confidence
             * @default 0.95
             */
            min_confidence: number;
            /**
             * Allow Uncalibrated Confidence
             * @default false
             */
            allow_uncalibrated_confidence: boolean;
        };
        /** OrgListResponse */
        OrgListResponse: {
            /** Items */
            items: components["schemas"]["OrgResponse"][];
            /** Total */
            total: number;
        };
        /** OrgResponse */
        OrgResponse: {
            /**
             * Org Id
             * Format: uuid
             */
            org_id: string;
            /** Name */
            name: string;
            /** Slug */
            slug: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Caller Role */
            caller_role?: ("Admin" | "Operator" | "Read-Only") | null;
        };
        /** OverrideListResponse */
        OverrideListResponse: {
            /**
             * Network Id
             * Format: uuid
             */
            network_id: string;
            /** Control Revision */
            control_revision: number;
            /** Overrides */
            overrides: components["schemas"]["OverrideResponse"][];
            /**
             * History Limit
             * @default 100
             */
            history_limit: number;
        };
        /** OverrideResponse */
        OverrideResponse: {
            /**
             * Override Id
             * Format: uuid
             */
            override_id: string;
            /**
             * Network Id
             * Format: uuid
             */
            network_id: string;
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
            /**
             * Intent Id
             * Format: uuid
             */
            intent_id: string;
            /**
             * Execution Id
             * Format: uuid
             */
            execution_id: string;
            /** Actor Id */
            actor_id: string;
            /** Reason */
            reason: string;
            /** Duration Seconds */
            duration_seconds: number;
            /**
             * Return Mode
             * @enum {string}
             */
            return_mode: "monitor" | "recommend" | "autonomous";
            /**
             * Prior Mode
             * @enum {string}
             */
            prior_mode: "monitor" | "recommend" | "autonomous";
            /** Prior Revision */
            prior_revision: number;
            /** Hold Revision */
            hold_revision: number;
            /** Checkpoint Sha256 */
            checkpoint_sha256: string | null;
            /** Prior Approval Expires At */
            prior_approval_expires_at: string | null;
            /** Prior Approved By User Id */
            prior_approved_by_user_id: string | null;
            /** Command Sha256 */
            command_sha256: string;
            /** Plan Hash */
            plan_hash: string;
            /** Binding Digest */
            binding_digest: string;
            /**
             * Run Id
             * Format: uuid
             */
            run_id: string;
            /**
             * Configuration Verified At
             * Format: date-time
             */
            configuration_verified_at: string;
            /**
             * Evidence Scope
             * @default historical_configuration_readback
             * @constant
             */
            evidence_scope: "historical_configuration_readback";
            /**
             * Status
             * @enum {string}
             */
            status: "holding" | "restoring" | "restored" | "return_blocked" | "returned";
            /** Reasons */
            reasons: string[];
            /** Cancellation Id */
            cancellation_id: string | null;
            /** Cancellation Requested At */
            cancellation_requested_at: string | null;
            /** Cancelled By User Id */
            cancelled_by_user_id: string | null;
            /** Restoration Attempts */
            restoration_attempts: number;
            /** Verification */
            verification: {
                [key: string]: unknown;
            } | null;
            /** Restored At */
            restored_at: string | null;
            /** Return Requested At */
            return_requested_at: string | null;
            /** Return Requested By User Id */
            return_requested_by_user_id: string | null;
            /** Return Reason */
            return_reason: string | null;
            /** Returned At */
            returned_at: string | null;
            /**
             * Expires At
             * Format: date-time
             */
            expires_at: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
        };
        /** PauseSimulationRequest */
        PauseSimulationRequest: {
            /**
             * Simulation Id
             * Format: uuid
             */
            simulation_id: string;
        };
        /** PauseSimulationResponse */
        PauseSimulationResponse: {
            /** Simulation Id */
            simulation_id: string;
            /** Network Id */
            network_id: string;
            /** Scene Object Id */
            scene_object_id: string;
            /** State */
            state: string;
            /** Status */
            status: string;
            /** Risk Gate */
            risk_gate: string;
            /** Scenario Id */
            scenario_id: string;
            /** Correlation Id */
            correlation_id: string;
        };
        /**
         * PendingApproval
         * @description C25 two-person switch: request awaiting a different approver's identical PUT.
         */
        PendingApproval: {
            /** Requested By User Id */
            requested_by_user_id: string;
            /**
             * Mode
             * @enum {string}
             */
            mode: "monitor" | "recommend" | "autonomous";
            /** Expected Revision */
            expected_revision: number;
            /** Checkpoint Sha256 */
            checkpoint_sha256: string | null;
            /** Approval Expires At */
            approval_expires_at: string | null;
            /**
             * Requested At
             * Format: date-time
             */
            requested_at: string;
            /**
             * Expires At
             * Format: date-time
             */
            expires_at: string;
        };
        /** PluginActionResponse */
        PluginActionResponse: {
            /**
             * Registry Only
             * @default true
             * @constant
             */
            registry_only: true;
            /**
             * Execution Supported
             * @default false
             * @constant
             */
            execution_supported: false;
            /**
             * Lifecycle Semantics
             * @default registry_flags_only
             * @constant
             */
            lifecycle_semantics: "registry_flags_only";
            /**
             * Plugin Id
             * Format: uuid
             */
            plugin_id: string;
            /** Plugin Key */
            plugin_key: string;
            /** Name */
            name: string;
            /** Version */
            version: string;
            /** Manifest */
            manifest: {
                [key: string]: unknown;
            };
            /**
             * Signature Status
             * @description Signatures are declarations; no cryptographic verification is performed.
             * @default declared_unverified
             * @constant
             */
            signature_status: "declared_unverified";
            /**
             * Dependency Status
             * @default declared_unverified
             * @constant
             */
            dependency_status: "declared_unverified";
            /**
             * Sandbox Status
             * @default not_executed
             * @constant
             */
            sandbox_status: "not_executed";
            /**
             * Permissions Status
             * @default declared_unverified
             * @constant
             */
            permissions_status: "declared_unverified";
            /**
             * Status
             * @enum {string}
             */
            status: "installed" | "enabled" | "disabled" | "failed" | "uninstalled";
            /** Enabled */
            enabled: boolean;
            /** Failure Reason */
            failure_reason: string | null;
            /** Queue Status */
            queue_status: string;
            /** Stream Entry Id */
            stream_entry_id: string | null;
            /** Warning */
            warning: string | null;
            /**
             * Installed At
             * Format: date-time
             */
            installed_at: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
            /** Uninstalled At */
            uninstalled_at?: string | null;
            /** Idempotent Replay */
            idempotent_replay: boolean;
        };
        /**
         * PluginInstallRequest
         * @description Metadata-only registry declaration; nothing is fetched, verified or executed.
         */
        PluginInstallRequest: {
            /** Plugin Key */
            plugin_key: string;
            /** Name */
            name: string;
            /** Version */
            version: string;
            /**
             * Signer
             * @description Declared signer. Admission checks allowlist membership only; the signer identity is never verified (signature_status=declared_unverified).
             */
            signer: string;
            /**
             * Signature
             * @description Declared signature string. Admission checks the configured prefix and minimum length only; it is never cryptographically verified (signature_status=declared_unverified).
             */
            signature: string;
            /** Dependencies */
            dependencies?: {
                [key: string]: components["schemas"]["JsonValue"];
            };
            /** Sandbox */
            sandbox?: {
                [key: string]: components["schemas"]["JsonValue"];
            };
            /** Metadata */
            metadata?: {
                [key: string]: components["schemas"]["JsonValue"];
            };
        };
        /** PluginListResponse */
        PluginListResponse: {
            /**
             * Registry Only
             * @default true
             * @constant
             */
            registry_only: true;
            /**
             * Execution Supported
             * @default false
             * @constant
             */
            execution_supported: false;
            /**
             * Lifecycle Semantics
             * @default registry_flags_only
             * @constant
             */
            lifecycle_semantics: "registry_flags_only";
            /** Items */
            items?: components["schemas"]["PluginRecordResponse"][];
            /** Total */
            total: number;
            /** Status Counts */
            status_counts?: {
                [key: string]: number;
            };
        };
        /** PluginRecordResponse */
        PluginRecordResponse: {
            /**
             * Registry Only
             * @default true
             * @constant
             */
            registry_only: true;
            /**
             * Execution Supported
             * @default false
             * @constant
             */
            execution_supported: false;
            /**
             * Lifecycle Semantics
             * @default registry_flags_only
             * @constant
             */
            lifecycle_semantics: "registry_flags_only";
            /**
             * Plugin Id
             * Format: uuid
             */
            plugin_id: string;
            /** Plugin Key */
            plugin_key: string;
            /** Name */
            name: string;
            /** Version */
            version: string;
            /** Manifest */
            manifest: {
                [key: string]: unknown;
            };
            /**
             * Signature Status
             * @description Signatures are declarations; no cryptographic verification is performed.
             * @default declared_unverified
             * @constant
             */
            signature_status: "declared_unverified";
            /**
             * Dependency Status
             * @default declared_unverified
             * @constant
             */
            dependency_status: "declared_unverified";
            /**
             * Sandbox Status
             * @default not_executed
             * @constant
             */
            sandbox_status: "not_executed";
            /**
             * Permissions Status
             * @default declared_unverified
             * @constant
             */
            permissions_status: "declared_unverified";
            /**
             * Status
             * @enum {string}
             */
            status: "installed" | "enabled" | "disabled" | "failed" | "uninstalled";
            /** Enabled */
            enabled: boolean;
            /** Failure Reason */
            failure_reason: string | null;
            /** Queue Status */
            queue_status: string;
            /** Stream Entry Id */
            stream_entry_id: string | null;
            /** Warning */
            warning: string | null;
            /**
             * Installed At
             * Format: date-time
             */
            installed_at: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
            /** Uninstalled At */
            uninstalled_at?: string | null;
        };
        /** Position */
        Position: {
            /** X */
            x: number;
            /** Y */
            y: number;
            /** Z */
            z: number;
        };
        /** ProbePathsResponse */
        ProbePathsResponse: {
            /**
             * Network Id
             * Format: uuid
             */
            network_id: string;
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
            /**
             * Status
             * @enum {string}
             */
            status: "measured" | "partial" | "ambiguous" | "stale" | "unavailable" | "invalid" | "run_mismatch";
            /** Reason */
            reason?: string | null;
            /**
             * Scope
             * @default selected_probe_only
             * @constant
             */
            scope: "selected_probe_only";
            /**
             * Freshness
             * @default unavailable
             * @enum {string}
             */
            freshness: "fresh" | "stale" | "unavailable";
            /** Run Id */
            run_id?: string | null;
            /** Window Id */
            window_id?: string | null;
            /** Window Start */
            window_start?: string | null;
            /** Window End */
            window_end?: string | null;
            /** Age Seconds */
            age_seconds?: number | null;
            /**
             * Max Age Seconds
             * @default 30
             */
            max_age_seconds: number;
            /** Evidence Sha256 */
            evidence_sha256?: string | null;
            /** Evidence Verification */
            evidence_verification?: "raw_pcap_replayed" | null;
            /**
             * Captured Packet Count
             * @default 0
             */
            captured_packet_count: number;
            /**
             * Measured Path Count
             * @default 0
             */
            measured_path_count: number;
            /** Paths */
            paths?: components["schemas"]["BoundPath"][];
            /** Captures */
            captures?: components["schemas"]["Capture"][];
            /** Packets */
            packets?: components["schemas"]["CapturedPacket"][];
            /**
             * Configuration Comparison
             * @default unavailable
             * @constant
             */
            configuration_comparison: "unavailable";
            /**
             * Path Variation
             * @default unknown
             * @enum {string}
             */
            path_variation: "single_observed_path" | "multiple_observed_paths" | "unknown";
        };
        /** Proposal */
        Proposal: {
            /** Action Id */
            action_id: string;
            /** Checkpoint Sha256 */
            checkpoint_sha256: string;
            /** Observation Contract */
            observation_contract: string;
            /** Evidence */
            evidence: string[];
            confidence?: components["schemas"]["Confidence"] | null;
        };
        /** Provenance */
        Provenance: {
            /** Source */
            source: string;
            /** Accuracy M */
            accuracy_m: number | null;
        };
        /** ProviderStatus */
        ProviderStatus: {
            /** Provider Id */
            provider_id: string;
            /**
             * Status
             * @enum {string}
             */
            status: "ready" | "unavailable" | "incompatible" | "uncalibrated";
            /** Reasons */
            reasons?: string[];
        };
        /** ProviderStatuses */
        ProviderStatuses: {
            observer: components["schemas"]["ProviderStatus"];
            qualification: components["schemas"]["ProviderStatus"];
            inference: components["schemas"]["ProviderStatus"];
            safety: components["schemas"]["ProviderStatus"];
            executor: components["schemas"]["ProviderStatus"];
        };
        /** QueueBounds */
        QueueBounds: {
            /** Egress Id */
            egress_id: string;
            /** Arrival Lower Bytes Per Second */
            arrival_lower_bytes_per_second: number;
            /** Arrival Upper Bytes Per Second */
            arrival_upper_bytes_per_second: number;
            /** Service Lower Bytes Per Second */
            service_lower_bytes_per_second: number;
            /** Service Upper Bytes Per Second */
            service_upper_bytes_per_second: number;
            /** Error Upper Bytes */
            error_upper_bytes: number;
        };
        /** QueueObservation */
        QueueObservation: {
            /** Egress Id */
            egress_id: string;
            /** Source */
            source: string;
            /** Destination */
            destination: string;
            /** Queue Bytes */
            queue_bytes: number;
            /** Capacity Bytes Per Second */
            capacity_bytes_per_second: number;
        };
        /** RefreshRequest */
        RefreshRequest: {
            /** Refresh Token */
            refresh_token: string;
        };
        /** RegisteredModelStatus */
        RegisteredModelStatus: {
            /** Model Id */
            model_id: string;
            /** Checkpoint Id */
            checkpoint_id: string;
            /** Checkpoint Sha256 */
            checkpoint_sha256: string;
            /** History References */
            history_references: string[];
            /**
             * Status
             * @default operator_registered
             * @constant
             */
            status: "operator_registered";
            /**
             * Benchmark Status
             * @enum {string}
             */
            benchmark_status: "qualified_scoped_benchmark" | "not_qualified";
            /** Benchmark Scope */
            benchmark_scope: string;
            /** Benchmark Limitations */
            benchmark_limitations: string[];
        };
        /** RegistrationScale */
        RegistrationScale: {
            /** X */
            x: number;
            /** Y */
            y: number;
            /** Z */
            z: number;
        };
        /** ReplaceSpatialSceneRequest */
        ReplaceSpatialSceneRequest: {
            /** Expected Revision */
            expected_revision: number;
            scene: components["schemas"]["SpatialSceneInput"];
        };
        /** ReportArtifactRef */
        ReportArtifactRef: {
            /** Artifact Id */
            artifact_id: string;
            /** Uri */
            uri: string;
            /** Media Type */
            media_type: string;
            /** Checksum Sha256 */
            checksum_sha256: string;
            /** Size Bytes */
            size_bytes: number;
            /**
             * Generated At
             * Format: date-time
             */
            generated_at: string;
            /** Filename */
            filename?: string | null;
        };
        /** ReportDateRangeRequest */
        ReportDateRangeRequest: {
            /**
             * Start
             * Format: date-time
             */
            start: string;
            /**
             * End
             * Format: date-time
             */
            end: string;
        };
        /** ReportFilters */
        ReportFilters: {
            /** Metric */
            metric?: string | null;
            /** Alert Status */
            alert_status?: ("active" | "acknowledged" | "resolved") | null;
            /** Alert Severity */
            alert_severity?: ("info" | "warning" | "critical" | "low" | "medium" | "high") | null;
            /**
             * Max Rows
             * @default 100
             */
            max_rows: number;
        };
        /** ReportGenerateResponse */
        ReportGenerateResponse: {
            /**
             * Report Id
             * Format: uuid
             */
            report_id: string;
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
            /** Network Id */
            network_id: string | null;
            /** Report Type */
            report_type: string;
            /** Format */
            format: string;
            /** Status */
            status: string;
            /** Date Range */
            date_range: {
                [key: string]: unknown;
            };
            /** Scope */
            scope: {
                [key: string]: unknown;
            };
            /** Filters */
            filters: {
                [key: string]: unknown;
            };
            /** Artifacts */
            artifacts?: components["schemas"]["ReportArtifactRef"][];
            /** Error */
            error?: {
                [key: string]: unknown;
            } | null;
            /** Queue Status */
            queue_status: string;
            /** Stream Entry Id */
            stream_entry_id: string | null;
            /** Warning */
            warning: string | null;
            /** Idempotency Key */
            idempotency_key: string | null;
            /**
             * Correlation Id
             * Format: uuid
             */
            correlation_id: string;
            /** Requested By User Id */
            requested_by_user_id: string;
            /**
             * Requested At
             * Format: date-time
             */
            requested_at: string;
            /** Completed At */
            completed_at: string | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
            /**
             * Artifact Version
             * @default 0
             */
            artifact_version: number;
            /**
             * Status Version
             * @default 0
             */
            status_version: number;
            /** Snapshot Sha256 */
            snapshot_sha256?: string | null;
            /** Snapshot Summary */
            snapshot_summary?: {
                [key: string]: unknown;
            };
            /** Idempotent Replay */
            idempotent_replay: boolean;
        };
        /** ReportHistoryResponse */
        ReportHistoryResponse: {
            /** Items */
            items: components["schemas"]["ReportRecordResponse"][];
            /** Total */
            total: number;
            /** Page */
            page: number;
            /** Page Size */
            page_size: number;
        };
        /** ReportRecordResponse */
        ReportRecordResponse: {
            /**
             * Report Id
             * Format: uuid
             */
            report_id: string;
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
            /** Network Id */
            network_id: string | null;
            /** Report Type */
            report_type: string;
            /** Format */
            format: string;
            /** Status */
            status: string;
            /** Date Range */
            date_range: {
                [key: string]: unknown;
            };
            /** Scope */
            scope: {
                [key: string]: unknown;
            };
            /** Filters */
            filters: {
                [key: string]: unknown;
            };
            /** Artifacts */
            artifacts?: components["schemas"]["ReportArtifactRef"][];
            /** Error */
            error?: {
                [key: string]: unknown;
            } | null;
            /** Queue Status */
            queue_status: string;
            /** Stream Entry Id */
            stream_entry_id: string | null;
            /** Warning */
            warning: string | null;
            /** Idempotency Key */
            idempotency_key: string | null;
            /**
             * Correlation Id
             * Format: uuid
             */
            correlation_id: string;
            /** Requested By User Id */
            requested_by_user_id: string;
            /**
             * Requested At
             * Format: date-time
             */
            requested_at: string;
            /** Completed At */
            completed_at: string | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
            /**
             * Artifact Version
             * @default 0
             */
            artifact_version: number;
            /**
             * Status Version
             * @default 0
             */
            status_version: number;
            /** Snapshot Sha256 */
            snapshot_sha256?: string | null;
            /** Snapshot Summary */
            snapshot_summary?: {
                [key: string]: unknown;
            };
        };
        /** ReportScope */
        ReportScope: {
            /**
             * Workspace
             * @default all
             * @constant
             */
            workspace: "all";
            /** Simulation Ids */
            simulation_ids?: string[];
            /** Intent Ids */
            intent_ids?: string[];
        };
        /** ResponseMeta */
        ResponseMeta: {
            /** Request Id */
            request_id: string;
            /** Timestamp */
            timestamp: string;
            /** Execution Time Ms */
            execution_time_ms?: number | null;
            /**
             * Execution Mode
             * @enum {string}
             */
            execution_mode?: "demo" | "emulation" | "production";
        };
        /** ReturnOverrideRequest */
        ReturnOverrideRequest: {
            /** Expected Revision */
            expected_revision: number;
            /** Reason */
            reason: string;
        };
        /**
         * Rotation
         * @description Radians; column-vector local matrix is T @ Rz @ Ry @ Rx.
         */
        Rotation: {
            /** X */
            x: number;
            /** Y */
            y: number;
            /** Z */
            z: number;
        };
        /** SafetyAction */
        SafetyAction: {
            /** Action Id */
            action_id: string;
            /** Network Id */
            network_id: string;
            /** Run Id */
            run_id: string;
            /** Snapshot Id */
            snapshot_id: string;
            /** Routes */
            routes: components["schemas"]["DemandRoute"][];
            bounds: components["schemas"]["CandidateBounds"];
        };
        /** SafetyAssessment */
        SafetyAssessment: {
            /** Admissible */
            admissible: boolean;
            /** Action Id */
            action_id?: string | null;
            /** Model Version */
            model_version: string;
            /** Reasons */
            reasons?: string[];
            /** Evidence */
            evidence?: string[];
            selected_action?: components["schemas"]["SafetyAction"] | null;
            certificate?: components["schemas"]["SafetyCertificate"] | null;
            binding?: components["schemas"]["SafetyBinding"] | null;
        };
        /** SafetyBinding */
        SafetyBinding: {
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
            /** Observation Sha256 */
            observation_sha256: string;
            /** Proposal Sha256 */
            proposal_sha256: string;
            /** Calibration Sha256 */
            calibration_sha256: string;
            /** Selected Action Sha256 */
            selected_action_sha256: string;
            /** Evaluated At Unix Seconds */
            evaluated_at_unix_seconds: number;
            observation: components["schemas"]["SafetyObservation"];
            policy: components["schemas"]["SafetyPolicy"];
            calibration: components["schemas"]["TrustedCalibration"];
            state: components["schemas"]["SafetyState"];
        };
        /**
         * SafetyBindingSummary
         * @description Binding digests only; the bound provider inputs stay in the full decision.
         */
        SafetyBindingSummary: {
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
            /** Observation Sha256 */
            observation_sha256: string;
            /** Proposal Sha256 */
            proposal_sha256: string;
            /** Calibration Sha256 */
            calibration_sha256: string;
            /** Selected Action Sha256 */
            selected_action_sha256: string;
            /** Evaluated At Unix Seconds */
            evaluated_at_unix_seconds: number;
        };
        /** SafetyCertificate */
        SafetyCertificate: {
            /**
             * Model
             * @constant
             */
            model: "bounded-fluid-v1";
            /** Calibration Id */
            calibration_id: string;
            /** Provider Id */
            provider_id: string;
            /** Policy Version */
            policy_version: string;
            /** Input Sha256 */
            input_sha256: string;
            /** Network Id */
            network_id: string;
            /** Run Id */
            run_id: string;
            /** Snapshot Id */
            snapshot_id: string;
            /** Action Id */
            action_id: string;
            /** Routes */
            routes: components["schemas"]["DemandRoute"][];
            /**
             * Conditional
             * @constant
             */
            conditional: true;
            /** Observed At Unix Seconds */
            observed_at_unix_seconds: number;
            /** Horizon End Unix Seconds */
            horizon_end_unix_seconds: number;
            /** Dt Seconds */
            dt_seconds: number;
            /** Actuation Delay Upper Seconds */
            actuation_delay_upper_seconds: number;
            /** Expires At Unix Seconds */
            expires_at_unix_seconds: number;
            drift: components["schemas"]["SafetyDrift"];
            envelope: components["schemas"]["SafetyEnvelope"];
            /** Model Checks Passed */
            model_checks_passed: boolean;
        };
        /** SafetyDrift */
        SafetyDrift: {
            /** V Before Bytes Squared */
            v_before_bytes_squared: number;
            /** V Next Upper Bytes Squared */
            v_next_upper_bytes_squared: number;
            /** Upper Bytes Squared */
            upper_bytes_squared: number;
            /** Budget Bytes Squared */
            budget_bytes_squared: number;
        };
        /** SafetyEnvelope */
        SafetyEnvelope: {
            /** Threshold Bytes */
            threshold_bytes: number;
            /** Q Next Upper Bytes */
            q_next_upper_bytes: {
                [key: string]: number;
            };
        };
        /** SafetyObservation */
        SafetyObservation: {
            /** Network Id */
            network_id: string;
            /** Run Id */
            run_id: string;
            /** Snapshot Id */
            snapshot_id: string;
            /** Sequence */
            sequence: number;
            /** Observed At Unix Seconds */
            observed_at_unix_seconds: number;
            /** Counter Reset */
            counter_reset: boolean;
            /** Attribution Complete */
            attribution_complete: boolean;
            /** Unknown Demand Ids */
            unknown_demand_ids: string[];
            /** Queues */
            queues: components["schemas"]["QueueObservation"][];
            /** Demands */
            demands: components["schemas"]["DemandObservation"][];
        };
        /** SafetyPolicy */
        SafetyPolicy: {
            /** Network Id */
            network_id: string;
            /** Policy Version */
            policy_version: string;
            /** Queue Threshold Bytes */
            queue_threshold_bytes: number;
            /** Max Dt Seconds */
            max_dt_seconds: number;
            /** Max Observation Age Seconds */
            max_observation_age_seconds: number;
            /** Max Delay Seconds */
            max_delay_seconds: number;
            /** Min Dwell Seconds */
            min_dwell_seconds: number;
            /** Rate Window Seconds */
            rate_window_seconds: number;
            /** Max Actions Per Window */
            max_actions_per_window: number;
            /**
             * Hysteresis Bytes Squared
             * @default 0
             */
            hysteresis_bytes_squared: number;
            /**
             * Drift Budget Bytes Squared
             * @default 0
             */
            drift_budget_bytes_squared: number;
            /** Allowed Paths */
            allowed_paths: components["schemas"]["AllowedPath"][];
        };
        /**
         * SafetyState
         * @description Fresh, durable executor history, independent of candidate/model evidence.
         */
        SafetyState: {
            /** Network Id */
            network_id: string;
            /** Run Id */
            run_id: string;
            /** Snapshot Id */
            snapshot_id: string;
            /** Observed At Unix Seconds */
            observed_at_unix_seconds: number;
            /** Last Evaluated Sequence */
            last_evaluated_sequence: number;
            /** Active Routes */
            active_routes: components["schemas"]["DemandRoute"][];
            /** Route Since Unix Seconds */
            route_since_unix_seconds: number;
            /** History Complete Since Unix Seconds */
            history_complete_since_unix_seconds: number;
            /** Last Applied At Unix Seconds */
            last_applied_at_unix_seconds: number | null;
            /** Recent Dispatch At Unix Seconds */
            recent_dispatch_at_unix_seconds: number[];
        };
        /** SafetySummary */
        SafetySummary: {
            /** Admissible */
            admissible: boolean;
            /** Action Id */
            action_id?: string | null;
            /** Model Version */
            model_version: string;
            /** Reasons */
            reasons?: string[];
            /** Evidence */
            evidence?: string[];
            certificate?: components["schemas"]["SafetyCertificate"] | null;
            binding?: components["schemas"]["SafetyBindingSummary"] | null;
        };
        /** ScenarioConfig */
        ScenarioConfig: {
            /**
             * Version
             * @constant
             */
            version: 1;
            /** Seed */
            seed: number;
            /** Tick Ms */
            tick_ms: number;
            /** Duration Ticks */
            duration_ticks: number;
            /** Links */
            links: components["schemas"]["ScenarioLink"][];
            /** Flows */
            flows: components["schemas"]["ScenarioFlow"][];
            action_binding: components["schemas"]["ActionBinding"] | null;
            limits: components["schemas"]["ScenarioLimits"];
        };
        /** ScenarioFlow */
        ScenarioFlow: {
            /** Flow Id */
            flow_id: string;
            /** Source */
            source: string;
            /** Target */
            target: string;
            /** Path */
            path: string[];
            /** Demand Mbps */
            demand_mbps: number[];
        };
        /** ScenarioLimits */
        ScenarioLimits: {
            /** Max Loss Pct */
            max_loss_pct: number;
            /** Max Latency Ms */
            max_latency_ms: number;
            /** Min Throughput Mbps */
            min_throughput_mbps: number;
        };
        /** ScenarioLink */
        ScenarioLink: {
            /** Link Id */
            link_id: string;
            /** Source */
            source: string;
            /** Target */
            target: string;
            /** Capacity Mbps */
            capacity_mbps: number;
            /** Buffer Bytes */
            buffer_bytes: number;
            /** Delay Ms */
            delay_ms: number;
            /** Initial Queue Bytes */
            initial_queue_bytes: number;
        };
        /** ScenarioValidationState */
        ScenarioValidationState: {
            /** Pipeline Stage */
            pipeline_stage: string;
            /** Required Checks */
            required_checks: string[];
            /** Policy Reference */
            policy_reference: string;
            /** Status */
            status: string;
            /** Queued At */
            queued_at: string;
            /** Requested By User Id */
            requested_by_user_id: string;
            /**
             * Evaluator Status
             * @default unavailable
             */
            evaluator_status: string;
            /** Failure Reason */
            failure_reason?: string | null;
            /**
             * Source
             * @default unavailable
             * @enum {string}
             */
            source: "operator_configured_model" | "unavailable";
            /**
             * Physical Safety Authorized
             * @default false
             * @constant
             */
            physical_safety_authorized: false;
        };
        /** SetAutonomyRequest */
        SetAutonomyRequest: {
            /**
             * Network Id
             * Format: uuid
             */
            network_id: string;
            /** Expected Revision */
            expected_revision: number;
            /**
             * Mode
             * @enum {string}
             */
            mode: "monitor" | "recommend" | "autonomous";
            /** Checkpoint Sha256 */
            checkpoint_sha256?: string | null;
            /** Approval Expires At */
            approval_expires_at?: string | null;
        };
        /** SetConfigurationRequest */
        SetConfigurationRequest: {
            /**
             * Network Id
             * Format: uuid
             */
            network_id: string;
            /** Expected Revision */
            expected_revision: number;
            /** Reason */
            reason: string;
            operational: components["schemas"]["OperationalSettings"];
            training: components["schemas"]["TrainingSettings"];
        };
        /**
         * SimulationActionBinding
         * @description Copy verbatim into ``scenario_config.action_binding`` (ADR-028 C18).
         *
         *     ``network_state_sha256`` is the stable topology/configuration digest
         *     (``simulation.modeled.current_network_state_hash`` v2), not a sample hash.
         */
        SimulationActionBinding: {
            /**
             * Intent Id
             * Format: uuid
             */
            intent_id: string;
            /** Plan Sha256 */
            plan_sha256: string;
            /** Network State Sha256 */
            network_state_sha256: string;
        };
        /** SimulationCompareResponse */
        SimulationCompareResponse: {
            /** Simulation Id */
            simulation_id: string;
            /** Baseline Simulation Id */
            baseline_simulation_id: string;
            /** Scenario Id */
            scenario_id: string;
            /** Baseline Scenario Id */
            baseline_scenario_id: string;
            /** Network Id */
            network_id: string;
            simulation_metrics: components["schemas"]["SimulationMetricsSnapshot"];
            baseline_metrics: components["schemas"]["SimulationMetricsSnapshot"];
            deltas: components["schemas"]["SimulationMetricsSnapshot"];
            /**
             * Compatible
             * @default false
             */
            compatible: boolean;
            /** Comparison Reason */
            comparison_reason?: string | null;
            /** Simulation Trace */
            simulation_trace?: components["schemas"]["SimulationTrace"][] | null;
            /** Baseline Trace */
            baseline_trace?: components["schemas"]["SimulationTrace"][] | null;
        };
        /** SimulationDetailResponse */
        SimulationDetailResponse: {
            /** Simulation Id */
            simulation_id: string;
            /** Parent Simulation Id */
            parent_simulation_id: string | null;
            /** Scenario Id */
            scenario_id: string;
            /** Network Id */
            network_id: string;
            /** Workspace Id */
            workspace_id: string;
            /** Scene Object Id */
            scene_object_id: string;
            /** State */
            state: string;
            /** Status */
            status: string;
            /** Risk Gate */
            risk_gate: string;
            /** Scenario Name */
            scenario_name: string;
            /** Validation */
            validation: {
                [key: string]: unknown;
            };
            /** Run Output */
            run_output: components["schemas"]["ModeledOutput"] | components["schemas"]["UnavailableOutput"];
            /** Model Versions */
            model_versions: {
                [key: string]: unknown;
            };
            /** Audit Provenance */
            audit_provenance: {
                [key: string]: unknown;
            };
            /** Queue Status */
            queue_status: string;
            /** Stream Entry Id */
            stream_entry_id: string | null;
            /** Warning */
            warning: string | null;
            /** Requested By User Id */
            requested_by_user_id: string;
            /** Requested At */
            requested_at: string;
            /** Created At */
            created_at: string;
            /** Updated At */
            updated_at: string;
            scenario_config?: components["schemas"]["ScenarioConfig"] | null;
            /** Input Sha256 */
            input_sha256?: string | null;
            /** Checkpoint Sha256 */
            checkpoint_sha256?: string | null;
            /**
             * Revision
             * @default 0
             */
            revision: number;
            /** Progress */
            progress?: {
                [key: string]: number;
            } | null;
            /** Completed At */
            completed_at?: string | null;
            /** Evidence Expires At */
            evidence_expires_at?: string | null;
            /** Execution Policy */
            execution_policy?: {
                [key: string]: unknown;
            } | null;
        };
        /** SimulationHistoryPage */
        SimulationHistoryPage: {
            /** Items */
            items: components["schemas"]["SimulationSummary"][];
            /** Total */
            total: number;
            /** Page */
            page: number;
            /** Page Size */
            page_size: number;
        };
        /** SimulationMetricsSnapshot */
        SimulationMetricsSnapshot: {
            /** Latency Ms */
            latency_ms: number | null;
            /** Loss Pct */
            loss_pct: number | null;
            /** Throughput Mbps */
            throughput_mbps: number | null;
        };
        /** SimulationSummary */
        SimulationSummary: {
            /**
             * Simulation Id
             * Format: uuid
             */
            simulation_id: string;
            /**
             * Network Id
             * Format: uuid
             */
            network_id: string;
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
            /** Scenario Name */
            scenario_name: string;
            /** Status */
            status: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
        };
        /** SimulationTrace */
        SimulationTrace: {
            /** Tick */
            tick: number;
            /** Elapsed Ms */
            elapsed_ms: number;
            /** Links */
            links: {
                [key: string]: components["schemas"]["LinkTrace"];
            };
            /** Flows */
            flows: {
                [key: string]: components["schemas"]["FluidMetrics"];
            };
        };
        /** SimulationValidationHandoffResponse */
        SimulationValidationHandoffResponse: {
            /** Simulation Id */
            simulation_id: string;
            /** Resumed From Simulation Id */
            resumed_from_simulation_id?: string | null;
            /** Scenario Id */
            scenario_id: string;
            /** Network Id */
            network_id: string;
            /** Scene Object Id */
            scene_object_id: string;
            /** State */
            state: string;
            /** Status */
            status: string;
            /** Risk Gate */
            risk_gate: string;
            /** Scenario Name */
            scenario_name: string;
            validation: components["schemas"]["ScenarioValidationState"];
            /** Requested At */
            requested_at: string;
            /** Correlation Id */
            correlation_id: string;
            /** Queue Status */
            queue_status: string;
            /** Stream Entry Id */
            stream_entry_id: string | null;
            /** Warning */
            warning: string | null;
        };
        /** SlabGeometry */
        SlabGeometry: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "slab";
            /** Width */
            width: number;
            /** Depth */
            depth: number;
            /** Thickness */
            thickness: number;
        };
        /** SpatialHistoryEntry */
        SpatialHistoryEntry: {
            /** Revision */
            revision: number;
            /**
             * Recorded At
             * Format: date-time
             */
            recorded_at: string;
            /** Actor Id */
            actor_id: string | null;
            /**
             * Origin
             * @enum {string}
             */
            origin: "baseline" | "replacement";
            /** Object Count */
            object_count: number;
        };
        /** SpatialHistoryList */
        SpatialHistoryList: {
            /** Items */
            items: components["schemas"]["SpatialHistoryEntry"][];
            /** Total */
            total: number;
            /** Page */
            page: number;
            /** Page Size */
            page_size: number;
        };
        /** SpatialObject */
        SpatialObject: {
            /** Object Id */
            object_id: string;
            /** Parent Id */
            parent_id: string | null;
            /**
             * Object Type
             * @enum {string}
             */
            object_type: "campus" | "building" | "floor" | "room" | "rack" | "device" | "interface" | "wall";
            /** Name */
            name: string;
            position: components["schemas"]["Position"];
            rotation: components["schemas"]["Rotation"];
            /** Device Id */
            device_id: string | null;
            provenance: components["schemas"]["Provenance"];
            /** Geometry */
            geometry?: (components["schemas"]["BoxGeometry"] | components["schemas"]["SlabGeometry"] | components["schemas"]["WallGeometry"]) | null;
        };
        /** SpatialSceneDocument */
        SpatialSceneDocument: {
            /**
             * Version
             * @constant
             */
            version: 1;
            coordinate_system: components["schemas"]["CoordinateSystem"];
            /** Objects */
            objects: components["schemas"]["SpatialObject"][];
            /** Revision */
            revision: number;
        };
        /** SpatialSceneInput */
        SpatialSceneInput: {
            /**
             * Version
             * @constant
             */
            version: 1;
            coordinate_system: components["schemas"]["CoordinateSystem"];
            /** Objects */
            objects: components["schemas"]["SpatialObject"][];
        };
        /** StartSimulationRequest */
        StartSimulationRequest: {
            /**
             * Network Id
             * Format: uuid
             */
            network_id: string;
            /** Scenario Name */
            scenario_name: string;
            /** Simulation Id */
            simulation_id?: string | null;
            scenario_config?: components["schemas"]["ScenarioConfig"] | null;
            /** Validation Checks */
            validation_checks?: string[];
        };
        /** StopAutonomyRequest */
        StopAutonomyRequest: {
            /**
             * Network Id
             * Format: uuid
             */
            network_id: string;
        };
        /** TelemetryAggregateResponse */
        TelemetryAggregateResponse: {
            /**
             * Device Id
             * Format: uuid
             */
            device_id: string;
            /** Metric */
            metric: string;
            /** Unit */
            unit: string | null;
            /** Source */
            source: string;
            /** Port No */
            port_no: string | null;
            /** Peer Host */
            peer_host: string | null;
            /** Run Id */
            run_id: string | null;
            /**
             * Bucket Start
             * Format: date-time
             */
            bucket_start: string;
            /** Value */
            value: number;
            /** Sample Count */
            sample_count: number;
        };
        /** TelemetryAggregationResponse */
        TelemetryAggregationResponse: {
            /** Items */
            items: components["schemas"]["TelemetryAggregateResponse"][];
            /** Total */
            total: number;
            /** Page */
            page: number;
            /** Page Size */
            page_size: number;
            /**
             * Total Capped
             * @default false
             */
            total_capped: boolean;
        };
        /** TelemetryCursorResponse */
        TelemetryCursorResponse: {
            /** Items */
            items: components["schemas"]["TelemetryRecordResponse"][];
            /** Page Size */
            page_size: number;
            /** Next Cursor */
            next_cursor: string | null;
            /** Upper Observed At */
            upper_observed_at: string | null;
            /** Upper Record Id */
            upper_record_id: string | null;
        };
        /** TelemetryDeviceHistoryResponse */
        TelemetryDeviceHistoryResponse: {
            /**
             * Device Id
             * Format: uuid
             */
            device_id: string;
            /** Items */
            items: components["schemas"]["TelemetryRecordResponse"][];
            /** Total */
            total: number;
            /** Page */
            page: number;
            /** Page Size */
            page_size: number;
            /**
             * Total Capped
             * @default false
             */
            total_capped: boolean;
        };
        /** TelemetryHealthResponse */
        TelemetryHealthResponse: {
            /** Status */
            status: string;
            /** Ingest Lag Ms */
            ingest_lag_ms: number | null;
            /** Dropped Events */
            dropped_events: number;
            /** Latest Observed At */
            latest_observed_at: string | null;
            /** Total Records */
            total_records: number;
            /**
             * Total Records Estimated
             * @default false
             */
            total_records_estimated: boolean;
            slo?: components["schemas"]["TelemetrySLOHealth"] | null;
        };
        /** TelemetryHistoryResponse */
        TelemetryHistoryResponse: {
            /** Items */
            items: components["schemas"]["TelemetryRecordResponse"][];
            /** Total */
            total: number;
            /** Page */
            page: number;
            /** Page Size */
            page_size: number;
            /**
             * Total Capped
             * @default false
             */
            total_capped: boolean;
        };
        /** TelemetryRecordResponse */
        TelemetryRecordResponse: {
            /**
             * Record Id
             * Format: uuid
             */
            record_id: string;
            /**
             * Event Id
             * Format: uuid
             */
            event_id: string;
            /**
             * Correlation Id
             * Format: uuid
             */
            correlation_id: string;
            /**
             * Device Id
             * Format: uuid
             */
            device_id: string;
            /**
             * Network Id
             * Format: uuid
             */
            network_id: string;
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
            /** Metric */
            metric: string;
            /** Value */
            value: number;
            /** Unit */
            unit: string | null;
            /**
             * Observed At
             * Format: date-time
             */
            observed_at: string;
            /** Source */
            source: string;
            /** Tags */
            tags: {
                [key: string]: unknown;
            };
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
        };
        /**
         * TelemetrySLOHealth
         * @description Additive read-only view of the collector-evaluated SLO state (ADR-028 C12).
         */
        TelemetrySLOHealth: {
            /**
             * Status
             * @enum {string}
             */
            status: "ok" | "degraded" | "critical" | "unavailable";
            /** Severity Reason */
            severity_reason?: string | null;
            /**
             * Alert Active
             * @default false
             */
            alert_active: boolean;
            /** Anomaly Reason Flags */
            anomaly_reason_flags?: string[];
            /**
             * Anomaly Streak
             * @default 0
             */
            anomaly_streak: number;
            /** Evaluated At */
            evaluated_at?: string | null;
            /** Evaluation Interval Seconds */
            evaluation_interval_seconds: number;
            /** Stale */
            stale: boolean;
            window?: components["schemas"]["TelemetrySLOWindowHealth"] | null;
            trend?: components["schemas"]["TelemetrySLOTrendHealth"] | null;
            /** Thresholds */
            thresholds?: {
                [key: string]: number;
            };
        };
        /** TelemetrySLOTrendHealth */
        TelemetrySLOTrendHealth: {
            /** Window Size */
            window_size: number;
            /** Max Window Size */
            max_window_size: number;
            /** Severity Transition Counts */
            severity_transition_counts: {
                [key: string]: number;
            };
            /** Anomaly Reason Frequency */
            anomaly_reason_frequency: {
                [key: string]: number;
            };
        };
        /**
         * TelemetrySLOWindowHealth
         * @description Counter deltas observed in the last closed evaluation window.
         */
        TelemetrySLOWindowHealth: {
            /** Start */
            start: string | null;
            /**
             * End
             * Format: date-time
             */
            end: string;
            /** Seconds */
            seconds: number;
            /** Ingest Attempts */
            ingest_attempts: number;
            /** Ingest Failures */
            ingest_failures: number;
            /** Invalid Samples */
            invalid_samples: number;
            /** Dropped Samples */
            dropped_samples: number;
            /** Invalid Sample Ratio */
            invalid_sample_ratio: number;
            /** Counter Reset */
            counter_reset: boolean;
        };
        /** TokenPair */
        TokenPair: {
            /** Access Token */
            access_token: string;
            /** Refresh Token */
            refresh_token: string;
            /**
             * Token Type
             * @default bearer
             */
            token_type: string;
            /** Expires In */
            expires_in: number;
        };
        /** TopologyDeviceNeighboursResponse */
        TopologyDeviceNeighboursResponse: {
            device: components["schemas"]["TopologyNode"];
            /** Neighbours */
            neighbours: components["schemas"]["TopologyNeighbourEdge"][];
            /** Depth */
            depth: number;
            /** Total */
            total: number;
        };
        /** TopologyEdge */
        TopologyEdge: {
            /** Source Id */
            source_id: string;
            /** Target Id */
            target_id: string;
            /** Edge Type */
            edge_type: string;
            /** Metadata */
            metadata: {
                [key: string]: unknown;
            };
        };
        /** TopologyGraphAPIResponse */
        TopologyGraphAPIResponse: {
            /** Success */
            success: boolean;
            data: components["schemas"]["TopologyGraphResponse"] | null;
            meta: components["schemas"]["TopologyGraphMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** TopologyGraphMeta */
        TopologyGraphMeta: {
            /** Request Id */
            request_id: string;
            /** Timestamp */
            timestamp: string;
            /** Execution Time Ms */
            execution_time_ms?: number | null;
            /**
             * Execution Mode
             * @enum {string}
             */
            execution_mode?: "demo" | "emulation" | "production";
            /** Next Cursor */
            next_cursor?: string | null;
        };
        /** TopologyGraphResponse */
        TopologyGraphResponse: {
            /** Nodes */
            nodes: components["schemas"]["TopologyNode"][];
            /** Edges */
            edges: components["schemas"]["TopologyEdge"][];
        };
        /** TopologyImpactAPIResponse */
        TopologyImpactAPIResponse: {
            /** Success */
            success: boolean;
            data: components["schemas"]["TopologyImpactResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** TopologyImpactNode */
        TopologyImpactNode: {
            /** Device Id */
            device_id: string;
            /** Hostname */
            hostname: string;
            /** Device Type */
            device_type: string;
            /** Status */
            status: string;
            /** Spatial Ref Id */
            spatial_ref_id?: string | null;
            /** Hop Depth */
            hop_depth: number;
        };
        /** TopologyImpactResponse */
        TopologyImpactResponse: {
            device: components["schemas"]["TopologyNode"];
            /** Impacts */
            impacts: components["schemas"]["TopologyImpactNode"][];
            /** Max Hops */
            max_hops: number;
            /** Total */
            total: number;
        };
        /** TopologyNeighbourEdge */
        TopologyNeighbourEdge: {
            /** Device Id */
            device_id: string;
            /** Hostname */
            hostname: string;
            /** Device Type */
            device_type: string;
            /** Status */
            status: string;
            /** Spatial Ref Id */
            spatial_ref_id?: string | null;
            /** Edge Type */
            edge_type: string;
            /** Edge Metadata */
            edge_metadata: {
                [key: string]: unknown;
            };
            /** Direction */
            direction: string;
            /** Hop Depth */
            hop_depth: number;
        };
        /** TopologyNeighbourNode */
        TopologyNeighbourNode: {
            /** Device Id */
            device_id: string;
            /** Hostname */
            hostname: string;
            /** Device Type */
            device_type: string;
            /** Status */
            status: string;
            /** Spatial Ref Id */
            spatial_ref_id?: string | null;
            /** Edge Type */
            edge_type: string;
            /** Direction */
            direction: string;
        };
        /** TopologyNeighboursAPIResponse */
        TopologyNeighboursAPIResponse: {
            /** Success */
            success: boolean;
            data: components["schemas"]["TopologyDeviceNeighboursResponse"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** TopologyNode */
        TopologyNode: {
            /** Device Id */
            device_id: string;
            /** Hostname */
            hostname: string;
            /** Device Type */
            device_type: string;
            /** Status */
            status: string;
            /** Spatial Ref Id */
            spatial_ref_id?: string | null;
        };
        /** TopologyNodeAPIResponse */
        TopologyNodeAPIResponse: {
            /** Success */
            success: boolean;
            data: components["schemas"]["TopologyNodeWithNeighbours"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** TopologyNodeWithNeighbours */
        TopologyNodeWithNeighbours: {
            node: components["schemas"]["TopologyPrimaryNode"];
            /** Neighbours */
            neighbours: components["schemas"]["TopologyNeighbourNode"][];
        };
        /** TopologyPrimaryNode */
        TopologyPrimaryNode: {
            /** Device Id */
            device_id: string;
            /** Hostname */
            hostname: string;
            /** Device Type */
            device_type: string;
            /** Status */
            status: string;
            /** Spatial Ref Id */
            spatial_ref_id?: string | null;
        };
        /** TopologyReconcileAPIResponse */
        TopologyReconcileAPIResponse: {
            /** Success */
            success: boolean;
            data: components["schemas"]["TopologyReconcileResult"] | null;
            meta: components["schemas"]["ResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** TopologyReconcileRequest */
        TopologyReconcileRequest: {
            /**
             * Network Id
             * Format: uuid
             */
            network_id: string;
        };
        /** TopologyReconcileResult */
        TopologyReconcileResult: {
            /** Reconcile Id */
            reconcile_id: string;
            /** Network Id */
            network_id: string;
            /** Status */
            status: string;
            /** Checked Nodes */
            checked_nodes: number;
            /** Checked Edges */
            checked_edges: number;
            /** Missing Workspace Nodes */
            missing_workspace_nodes: number;
            /** Workspace Backfilled Nodes */
            workspace_backfilled_nodes: number;
            /** Warning */
            warning?: string | null;
            /**
             * Active Devices
             * @default 0
             */
            active_devices: number;
            /**
             * Upserted Nodes
             * @default 0
             */
            upserted_nodes: number;
            /**
             * Tombstoned Nodes
             * @default 0
             */
            tombstoned_nodes: number;
            /**
             * Skipped Newer Nodes
             * @default 0
             */
            skipped_newer_nodes: number;
            /**
             * Watermark Sequence
             * @default 0
             */
            watermark_sequence: number;
        };
        /** TrainingSettings */
        TrainingSettings: {
            /** Reward Weights */
            reward_weights?: {
                [key: string]: number;
            };
        };
        /**
         * TrustedCalibration
         * @description Server-owned installation record, NOT a payload self-attestation flag.
         */
        TrustedCalibration: {
            /** Calibration Id */
            calibration_id: string;
            /** Provider Id */
            provider_id: string;
            /**
             * Model Version
             * @constant
             */
            model_version: "bounded-fluid-v1";
            /** Network Id */
            network_id: string;
            /** Run Id */
            run_id: string;
            /** Valid From Unix Seconds */
            valid_from_unix_seconds: number;
            /** Valid Until Unix Seconds */
            valid_until_unix_seconds: number;
            /** Egress Ids */
            egress_ids: string[];
            /** Demand Ids */
            demand_ids: string[];
            /** Min Error Upper Bytes */
            min_error_upper_bytes: number;
            /** Min Service Uncertainty Bytes Per Second */
            min_service_uncertainty_bytes_per_second: number;
        };
        /** UnavailableOutput */
        UnavailableOutput: {
            /** Latency Ms */
            latency_ms?: null;
            /** Loss Pct */
            loss_pct?: null;
            /** Throughput Mbps */
            throughput_mbps?: null;
        };
        /** UpdateDeviceRequest */
        UpdateDeviceRequest: {
            /** Hostname */
            hostname?: string | null;
            /** Ip Address */
            ip_address?: string | null;
            /** Device Type */
            device_type?: string | null;
            /** Vendor */
            vendor?: string | null;
            /** Model */
            model?: string | null;
            /** Location Hint */
            location_hint?: string | null;
            /** Spatial Ref Id */
            spatial_ref_id?: string | null;
        };
        /** UpdateNetworkRequest */
        UpdateNetworkRequest: {
            /** Name */
            name?: string | null;
            /** Description */
            description?: string | null;
            /** Cidr */
            cidr?: string | null;
        };
        /** UpdateOrgRequest */
        UpdateOrgRequest: {
            /** Name */
            name?: string | null;
        };
        /** UpdateWorkspaceRequest */
        UpdateWorkspaceRequest: {
            /** Name */
            name?: string | null;
            /** Description */
            description?: string | null;
        };
        /** UpsertCampusBuildingInput */
        UpsertCampusBuildingInput: {
            /** Building Id */
            building_id: string;
            /** Campus Key */
            campus_key: string;
            /** Building Key */
            building_key: string;
            /** Label */
            label: string;
            /** Geometry */
            geometry: string;
            /** X */
            x: number;
            /** Z */
            z: number;
            /** Base Y */
            base_y: number;
            /** Width */
            width: number;
            /** Depth */
            depth: number;
            /** Height */
            height: number;
            /** Floors */
            floors: number;
            /** Footprint */
            footprint: number[][];
            /** Wall Material */
            wall_material?: string | null;
            /** Attenuation Db */
            attenuation_db?: number | null;
            /** Source */
            source?: string | null;
        };
        /** UpsertCampusBuildingsRequest */
        UpsertCampusBuildingsRequest: {
            /** Buildings */
            buildings?: components["schemas"]["UpsertCampusBuildingInput"][];
            /**
             * Replace Existing
             * @default true
             */
            replace_existing: boolean;
        };
        /** UpsertCampusModelAssetRequest */
        UpsertCampusModelAssetRequest: {
            registration?: components["schemas"]["AssetRegistration"] | null;
            /** Model File Name */
            model_file_name: string;
            /** Model Mime Type */
            model_mime_type: string;
            /** Model Data Base64 */
            model_data_base64: string;
            /** Model Sha256 */
            model_sha256: string;
            /** Model Size Bytes */
            model_size_bytes: number;
            /** Mapping By Device Id */
            mapping_by_device_id?: {
                [key: string]: string;
            };
            /** Source */
            source?: string | null;
            /**
             * Replace Existing
             * @default true
             */
            replace_existing: boolean;
        };
        /** UpsertDeviceGroupInput */
        UpsertDeviceGroupInput: {
            /** Group Key */
            group_key: string;
            /** Name */
            name: string;
            /** Group Type */
            group_type: string;
            /** Description */
            description?: string | null;
            /** Selector */
            selector?: {
                [key: string]: string;
            };
            /** Device Ids */
            device_ids?: string[];
            /** Expected Updated At */
            expected_updated_at?: string | null;
        };
        /** UpsertDeviceGroupsRequest */
        UpsertDeviceGroupsRequest: {
            /** Groups */
            groups?: components["schemas"]["UpsertDeviceGroupInput"][];
            /**
             * Replace Existing
             * @default false
             */
            replace_existing: boolean;
        };
        /** UserProfile */
        UserProfile: {
            /**
             * User Id
             * Format: uuid
             */
            user_id: string;
            /** Email */
            email: string;
            /** Display Name */
            display_name: string | null;
            /** Roles */
            roles: string[];
            /** Permissions */
            permissions: string[];
        };
        /** ValidateIntentEnvelope */
        ValidateIntentEnvelope: {
            /** Success */
            success: boolean;
            data: components["schemas"]["ValidateIntentResponse"] | null;
            meta: components["schemas"]["IntentResponseMeta"];
            errors: components["schemas"]["ErrorDetail"] | null;
        };
        /** ValidateIntentRequest */
        ValidateIntentRequest: {
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
            /** Network Id */
            network_id?: string | null;
            /**
             * Intent
             * @description UNIL intent document: JSON-native values only, at most 65536 bytes serialized, nesting depth 10, 128 keys per object and 1024 items per array.
             */
            intent?: {
                [key: string]: unknown;
            };
        };
        /** ValidateIntentResponse */
        ValidateIntentResponse: {
            /**
             * Intent Id
             * Format: uuid
             */
            intent_id: string;
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
            /** Network Id */
            network_id: string | null;
            /** Status */
            status: string;
            /** Intent Kind */
            intent_kind: string;
            validation: components["schemas"]["IntentValidationState"];
            explainability: components["schemas"]["IntentExplainability"];
            confidence: components["schemas"]["IntentConfidenceState"];
            /** Idempotency Key */
            idempotency_key: string | null;
            /**
             * Correlation Id
             * Format: uuid
             */
            correlation_id: string;
            /**
             * Requested At
             * Format: date-time
             */
            requested_at: string;
            /**
             * Queue Status
             * @default validated
             */
            queue_status: string;
            /** Stream Entry Id */
            stream_entry_id?: string | null;
            /** Warning */
            warning?: string | null;
            /**
             * Idempotent Replay
             * @default false
             */
            idempotent_replay: boolean;
            approval_binding?: components["schemas"]["ApprovalBinding"] | null;
            simulation_action_binding?: components["schemas"]["SimulationActionBinding"] | null;
        };
        /** ValidationError */
        ValidationError: {
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
            /** Input */
            input?: unknown;
            /** Context */
            ctx?: Record<string, never>;
        };
        /** ValidationReason */
        ValidationReason: {
            /** Code */
            code: string;
            /** Message */
            message: string;
            /** Path */
            path?: string | null;
        };
        /** Verification */
        Verification: {
            /**
             * Execution Id
             * Format: uuid
             */
            execution_id: string;
            /**
             * Status
             * @enum {string}
             */
            status: "pending" | "verified" | "cancelled" | "failed" | "uncertain";
            /**
             * Safe To Release
             * @default false
             */
            safe_to_release: boolean;
            /** Evidence */
            evidence?: string[];
            /** Reasons */
            reasons?: string[];
        };
        /** WallGeometry */
        WallGeometry: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "wall";
            /** Length */
            length: number;
            /** Height */
            height: number;
            /** Thickness */
            thickness: number;
            material: components["schemas"]["WallMaterial"];
        };
        /** WallMaterial */
        WallMaterial: {
            /** Name */
            name: string;
            /** Attenuation Db */
            attenuation_db: number | null;
            /** Source */
            source: string;
        };
        /** WorkspaceListResponse */
        WorkspaceListResponse: {
            /** Items */
            items: components["schemas"]["WorkspaceResponse"][];
            /** Total */
            total: number;
        };
        /** WorkspaceResponse */
        WorkspaceResponse: {
            /**
             * Workspace Id
             * Format: uuid
             */
            workspace_id: string;
            /**
             * Org Id
             * Format: uuid
             */
            org_id: string;
            /** Name */
            name: string;
            /** Description */
            description: string | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    ready_ready_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    login_api_v1_auth_login_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LoginRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_TokenPair_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    logout_api_v1_auth_logout_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_dict_"];
                };
            };
        };
    };
    refresh_api_v1_auth_refresh_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RefreshRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_TokenPair_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    me_api_v1_auth_me_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_UserProfile_"];
                };
            };
        };
    };
    get_autonomy_api_v1_autonomy_get: {
        parameters: {
            query: {
                network_id: string;
                history_limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_AutonomyResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    set_autonomy_api_v1_autonomy_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SetAutonomyRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AutonomyModeResponse"];
                };
            };
            /** @description Accepted */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AutonomyModeResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    stop_autonomy_api_v1_autonomy_stop_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["StopAutonomyRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_AutonomyResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_configuration_api_v1_autonomy_configuration_get: {
        parameters: {
            query: {
                network_id: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_ConfigurationResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    put_configuration_api_v1_autonomy_configuration_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SetConfigurationRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_ConfigurationResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_overrides_api_v1_autonomy_overrides_get: {
        parameters: {
            query: {
                network_id: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_OverrideListResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_override_api_v1_autonomy_overrides_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateOverrideRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_OverrideResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    cancel_override_api_v1_autonomy_overrides__override_id__cancel_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                override_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_OverrideResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    return_override_api_v1_autonomy_overrides__override_id__return_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                override_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReturnOverrideRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_OverrideResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_orgs_api_v1_organizations_get: {
        parameters: {
            query?: {
                /** @description 1-based page number */
                page?: number;
                page_size?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_OrgListResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_org_api_v1_organizations_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateOrgRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_OrgResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_org_api_v1_organizations__org_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                org_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_OrgResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_org_api_v1_organizations__org_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                org_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_org_api_v1_organizations__org_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                org_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdateOrgRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_OrgResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_workspaces_api_v1_organizations__org_id__workspaces_get: {
        parameters: {
            query?: {
                /** @description 1-based page number */
                page?: number;
                page_size?: number;
            };
            header?: never;
            path: {
                org_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_WorkspaceListResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_workspace_api_v1_organizations__org_id__workspaces_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                org_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateWorkspaceRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_WorkspaceResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_workspace_api_v1_organizations__org_id__workspaces__workspace_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                org_id: string;
                workspace_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_WorkspaceResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_workspace_api_v1_organizations__org_id__workspaces__workspace_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                org_id: string;
                workspace_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_workspace_api_v1_organizations__org_id__workspaces__workspace_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                org_id: string;
                workspace_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdateWorkspaceRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_WorkspaceResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_members_api_v1_organizations__org_id__members_get: {
        parameters: {
            query?: {
                /** @description 1-based page number */
                page?: number;
                page_size?: number;
            };
            header?: never;
            path: {
                org_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_MemberListResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    add_member_api_v1_organizations__org_id__members_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                org_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AddMemberRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_MemberResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    remove_member_api_v1_organizations__org_id__members__user_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                org_id: string;
                user_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_networks_api_v1_networks_get: {
        parameters: {
            query: {
                workspace_id: string;
                /** @description 1-based page number */
                page?: number;
                page_size?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_NetworkListResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_network_api_v1_networks_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateNetworkRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_NetworkResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_network_api_v1_networks__network_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                network_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_network_api_v1_networks__network_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                network_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdateNetworkRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_NetworkResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_devices_api_v1_networks__network_id__devices_get: {
        parameters: {
            query?: {
                /** @description 1-based page number */
                page?: number;
                page_size?: number;
            };
            header?: never;
            path: {
                network_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_DeviceListResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    add_device_api_v1_networks__network_id__devices_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                network_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateDeviceRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_DeviceResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_device_api_v1_networks__network_id__devices__device_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                network_id: string;
                device_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_device_api_v1_networks__network_id__devices__device_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                network_id: string;
                device_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdateDeviceRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_DeviceResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_campus_buildings_api_v1_networks__network_id__campus_buildings_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                network_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_CampusBuildingListResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    upsert_campus_buildings_api_v1_networks__network_id__campus_buildings_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                network_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpsertCampusBuildingsRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_CampusBuildingListResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_campus_model_assets_api_v1_networks__network_id__campus_model_assets_get: {
        parameters: {
            query?: {
                include_data?: boolean;
                /** @description 1-based page number */
                page?: number;
                page_size?: number;
            };
            header?: never;
            path: {
                network_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_CampusModelAssetListResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    upsert_campus_model_assets_api_v1_networks__network_id__campus_model_assets_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                network_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpsertCampusModelAssetRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_CampusModelAssetListResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    retire_campus_model_asset_api_v1_networks__network_id__campus_model_assets__asset_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                network_id: string;
                asset_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    download_campus_model_asset_api_v1_networks__network_id__campus_model_assets__asset_id__download_get: {
        parameters: {
            query?: never;
            header?: {
                "if-none-match"?: string | null;
            };
            path: {
                network_id: string;
                asset_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_device_groups_api_v1_networks__network_id__device_groups_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                network_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_DeviceGroupListResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    upsert_device_groups_api_v1_networks__network_id__device_groups_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                network_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpsertDeviceGroupsRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_DeviceGroupListResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_spatial_scene_api_v1_networks__network_id__spatial_scene_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                network_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_SpatialSceneDocument_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    replace_spatial_scene_api_v1_networks__network_id__spatial_scene_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                network_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReplaceSpatialSceneRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_SpatialSceneDocument_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_spatial_history_api_v1_networks__network_id__spatial_scene_history_get: {
        parameters: {
            query?: {
                /** @description 1-based page number */
                page?: number;
                page_size?: number;
            };
            header?: never;
            path: {
                network_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_SpatialHistoryList_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_spatial_revision_api_v1_networks__network_id__spatial_scene_history__revision__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                network_id: string;
                revision: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_SpatialSceneDocument_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_topology_graph_api_v1_topology_graph_get: {
        parameters: {
            query: {
                network_id: string;
                depth?: number;
                limit?: number;
                cursor?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TopologyGraphAPIResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_topology_node_with_neighbours_api_v1_topology_nodes__device_id__get: {
        parameters: {
            query?: {
                depth?: number;
            };
            header?: never;
            path: {
                device_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TopologyNodeAPIResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_topology_device_neighbours_api_v1_topology_device__device_id__neighbors_get: {
        parameters: {
            query?: {
                depth?: number;
                limit?: number;
            };
            header?: never;
            path: {
                device_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TopologyNeighboursAPIResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_topology_impact_api_v1_topology_impact__device_id__get: {
        parameters: {
            query?: {
                max_hops?: number;
                limit?: number;
            };
            header?: never;
            path: {
                device_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TopologyImpactAPIResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reconcile_topology_api_v1_topology_reconcile_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TopologyReconcileRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TopologyReconcileAPIResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_telemetry_history_api_v1_telemetry_history_get: {
        parameters: {
            query?: {
                network_id?: string | null;
                workspace_id?: string | null;
                metric?: string | null;
                /** @description 1-based page number */
                page?: number;
                page_size?: number;
                start_time?: string | null;
                end_time?: string | null;
                aggregation?: ("avg" | "min" | "max" | "sum") | null;
                bucket_seconds?: number | null;
                pagination?: "page" | "cursor";
                cursor?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_Union_TelemetryHistoryResponse__TelemetryAggregationResponse__TelemetryCursorResponse__"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_device_telemetry_api_v1_telemetry_device__device_id__get: {
        parameters: {
            query?: {
                metric?: string | null;
                /** @description 1-based page number */
                page?: number;
                page_size?: number;
                start_time?: string | null;
                end_time?: string | null;
            };
            header?: never;
            path: {
                device_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_TelemetryDeviceHistoryResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_telemetry_health_api_v1_telemetry_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_TelemetryHealthResponse_"];
                };
            };
        };
    };
    get_paths_api_v1_telemetry_paths_get: {
        parameters: {
            query: {
                network_id: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_ProbePathsResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    start_simulation_api_v1_simulations_start_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["StartSimulationRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_SimulationValidationHandoffResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    pause_simulation_api_v1_simulations_pause_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PauseSimulationRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_PauseSimulationResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    branch_simulation_api_v1_simulations_branch_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BranchSimulationRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_BranchSimulationResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_simulations_api_v1_simulations_get: {
        parameters: {
            query: {
                workspace_id: string;
                network_id?: string | null;
                /** @description 1-based page number */
                page?: number;
                page_size?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_SimulationHistoryPage_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_simulation_detail_api_v1_simulations__simulation_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                simulation_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_SimulationDetailResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    compare_simulations_api_v1_simulations__simulation_id__compare__baseline_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                simulation_id: string;
                baseline_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_SimulationCompareResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    validate_intent_api_v1_intents_validate_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ValidateIntentRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ValidateIntentEnvelope"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    execute_intent_api_v1_intents_execute_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ExecuteIntentRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExecuteIntentEnvelope"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_intents_api_v1_intents_get: {
        parameters: {
            query: {
                workspace_id: string;
                network_id?: string | null;
                /** @description 1-based page number */
                page?: number;
                page_size?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_IntentHistoryPage_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_intent_api_v1_intents__intent_id__get: {
        parameters: {
            query: {
                workspace_id: string;
            };
            header?: never;
            path: {
                intent_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_IntentDetailResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_model_api_v1_autonomy_model_get: {
        parameters: {
            query: {
                network_id: string;
                history_limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_ModelDiagnosticsResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    diagnose_model_api_v1_autonomy_model_diagnose_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DiagnoseModelRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_ModelDiagnosticRecord_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    uninstall_plugin_api_v1_plugins__plugin_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                plugin_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_plugins_api_v1_plugins_get: {
        parameters: {
            query?: {
                status?: string | null;
                enabled?: string | null;
                search?: string | null;
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_PluginListResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    install_plugin_api_v1_plugins_install_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PluginInstallRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_PluginActionResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    enable_plugin_api_v1_plugins__plugin_id__enable_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                plugin_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_PluginActionResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    disable_plugin_api_v1_plugins__plugin_id__disable_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                plugin_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_PluginActionResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    generate_report_api_v1_reports_generate_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["GenerateReportRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_ReportGenerateResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    report_history_api_v1_reports_get: {
        parameters: {
            query: {
                workspace_id: string;
                /** @description 1-based page number */
                page?: number;
                page_size?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_ReportHistoryResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    download_report_api_v1_reports__report_id__download_get: {
        parameters: {
            query: {
                workspace_id: string;
            };
            header?: never;
            path: {
                report_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_report_api_v1_reports__report_id__get: {
        parameters: {
            query: {
                workspace_id: string;
            };
            header?: never;
            path: {
                report_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_ReportRecordResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_alert_api_v1_alerts__alert_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                alert_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_AlertRecordResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_alert_history_api_v1_alerts__alert_id__history_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                alert_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_AlertHistoryResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_alerts_api_v1_alerts_get: {
        parameters: {
            query?: {
                status?: string | null;
                severity?: string | null;
                source?: string | null;
                correlation_id?: string | null;
                search?: string | null;
                limit?: number;
                workspace_id?: string | null;
                network_id?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_AlertListResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    acknowledge_alert_api_v1_alerts__alert_id__ack_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                alert_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_AlertActionResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    resolve_alert_api_v1_alerts__alert_id__resolve_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                alert_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_AlertActionResponse_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_audit_logs_api_v1_audit_logs_get: {
        parameters: {
            query?: {
                actor_id?: string | null;
                org_id?: string | null;
                resource_type?: string | null;
                /** @description 1-based page number */
                page?: number;
                page_size?: number;
                search?: string | null;
                scope?: "org" | "platform";
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["APIResponse_AuditLogPage_"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    health_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
}
