import { Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppProviders } from "./providers";
import { useAuthStore } from "@/shared/state/auth-store";
import { AppShell } from "@/shared/ui/AppShell";
import {
  AuditPage,
  IntentPage,
  LoginPage,
  OverviewPage,
  ReliabilityPage,
  SimulationPage,
  TenancyPage,
  TelemetryPage,
  TwinPage,
} from "./routes";
import { AsyncState } from "@/shared/ui/AsyncState";

function RequireAuth({ children }: { children: JSX.Element }) {
  const token = useAuthStore((state) => state.accessToken);
  if (!token) {
    return <Navigate to="/login" replace />;
  }
  return children;
}

function AppLoadingFallback() {
  return (
    <div style={{ maxWidth: 680, margin: "15vh auto", padding: "0 1rem" }}>
      <AsyncState title="Loading NANFO workspace" description="Preparing route bundles and realtime channels..." />
    </div>
  );
}

export function App() {
  return (
    <AppProviders>
      <Suspense fallback={<AppLoadingFallback />}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/ops"
            element={
              <RequireAuth>
                <AppShell />
              </RequireAuth>
            }
          >
            <Route index element={<Navigate to="overview" replace />} />
            <Route path="overview" element={<OverviewPage />} />
            <Route path="tenancy" element={<TenancyPage />} />
            <Route path="telemetry" element={<TelemetryPage />} />
            <Route path="reliability" element={<ReliabilityPage />} />
            <Route path="digital-twin" element={<TwinPage />} />
            <Route path="simulation" element={<SimulationPage />} />
            <Route path="intent" element={<IntentPage />} />
            <Route path="audit" element={<AuditPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/ops" replace />} />
        </Routes>
      </Suspense>
    </AppProviders>
  );
}
