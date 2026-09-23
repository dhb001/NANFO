import { Suspense, type PropsWithChildren } from "react";
import { Navigate, Outlet, Route, Routes } from "react-router-dom";
import { AppProviders } from "./providers";
import { SessionGate } from "@/features/auth/SessionGate";
import { AppShell } from "@/shared/ui/AppShell";
import {
  AuditPage,
  AutonomyPage,
  IntentPage,
  LoginPage,
  OverviewPage,
  PluginsPage,
  ReportsPage,
  ReliabilityPage,
  SimulationPage,
  TenancyPage,
  TelemetryPage,
  TopologyAnalysisPage,
  TwinPage,
} from "./routes";
import { AsyncState } from "@/shared/ui/AsyncState";
import { RouteErrorBoundary } from "@/shared/ui/RouteErrorBoundary";

function AppLoadingFallback() {
  return (
    <div style={{ maxWidth: 680, margin: "15vh auto", padding: "0 1rem" }}>
      <AsyncState title="Loading NANFO workspace" description="Preparing route bundles and realtime channels..." />
    </div>
  );
}

function RouteView({ children }: PropsWithChildren) {
  return (
    <RouteErrorBoundary>
      <Suspense fallback={<AppLoadingFallback />}>{children}</Suspense>
    </RouteErrorBoundary>
  );
}

export function App() {
  return (
    <RouteErrorBoundary>
      <AppProviders>
        <Suspense fallback={<AppLoadingFallback />}>
          <Routes>
            <Route path="/login" element={<RouteView><LoginPage /></RouteView>} />
            <Route
              path="/ops"
              element={
                <SessionGate>
                  <AppShell />
                </SessionGate>
              }
            >
              <Route element={<RouteView><Outlet /></RouteView>}>
                <Route index element={<Navigate to="overview" replace />} />
                <Route path="overview" element={<OverviewPage />} />
                <Route path="tenancy" element={<TenancyPage />} />
                <Route path="topology-analysis" element={<TopologyAnalysisPage />} />
                <Route path="telemetry" element={<TelemetryPage />} />
                <Route path="reliability" element={<ReliabilityPage />} />
                <Route path="plugins" element={<PluginsPage />} />
                <Route path="reports" element={<ReportsPage />} />
                <Route path="digital-twin" element={<TwinPage />} />
                <Route path="simulation" element={<SimulationPage />} />
                <Route path="intent" element={<IntentPage />} />
                <Route path="autonomy" element={<AutonomyPage />} />
                <Route path="audit" element={<AuditPage />} />
              </Route>
            </Route>
            <Route path="*" element={<Navigate to="/ops" replace />} />
          </Routes>
        </Suspense>
      </AppProviders>
    </RouteErrorBoundary>
  );
}
