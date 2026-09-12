import type { AutonomyDecision } from "./types";

export function SafetyCertificate({ safety, now }: { safety: AutonomyDecision["safety"]; now: number }) {
  const certificate = safety?.certificate;
  if (!certificate) return null;
  const binding = safety.binding;
  const timestamp = (seconds: number) => new Date(seconds * 1_000).toISOString();
  return <section aria-label="Reported conditional certificate" className="autonomy-stack">
    <h4>Reported conditional certificate</h4>
    <p>Historical backend evidence, not current dispatch authorization. Hashes are reported identifiers, not signatures or independently verified provenance.</p>
    <dl>
      <div><dt>Model / provider</dt><dd>{certificate.model} / {certificate.provider_id}</dd></div>
      <div><dt>Calibration / policy</dt><dd>{certificate.calibration_id} / {certificate.policy_version}</dd></div>
      <div><dt>Network / run / snapshot</dt><dd>{certificate.network_id} / {certificate.run_id} / {certificate.snapshot_id}</dd></div>
      <div><dt>Action</dt><dd>{certificate.action_id}</dd></div>
      <div><dt>Input SHA-256</dt><dd className="mono">{certificate.input_sha256}</dd></div>
      <div><dt>Observed at (UTC)</dt><dd>{timestamp(certificate.observed_at_unix_seconds)}</dd></div>
      <div><dt>Horizon end (UTC)</dt><dd>{timestamp(certificate.horizon_end_unix_seconds)}</dd></div>
      <div><dt>Exclusive expiry (UTC)</dt><dd>{timestamp(certificate.expires_at_unix_seconds)}. {now >= certificate.expires_at_unix_seconds * 1_000 ? "Expired by browser clock" : "Expiry not yet reached by browser clock; server must recheck"}.</dd></div>
      <div><dt>Horizon / actuation delay upper bound (seconds)</dt><dd>{certificate.dt_seconds} / {certificate.actuation_delay_upper_seconds}</dd></div>
      <div><dt>Model checks at evaluation</dt><dd>{certificate.model_checks_passed ? "Passed under supplied bounds" : "Did not pass"}</dd></div>
      <div><dt>V before / V next upper (bytes squared)</dt><dd>{certificate.drift.v_before_bytes_squared} / {certificate.drift.v_next_upper_bytes_squared}</dd></div>
      <div><dt>Drift upper / budget (bytes squared)</dt><dd>{certificate.drift.upper_bytes_squared} / {certificate.drift.budget_bytes_squared}</dd></div>
      <div><dt>Queue threshold (bytes)</dt><dd>{certificate.envelope.threshold_bytes}</dd></div>
      {binding ? <>
        <div><dt>Binding evaluated at (UTC)</dt><dd>{timestamp(binding.evaluated_at_unix_seconds)}</dd></div>
        <div><dt>Observation SHA-256</dt><dd className="mono">{binding.observation_sha256}</dd></div>
        <div><dt>Proposal SHA-256</dt><dd className="mono">{binding.proposal_sha256}</dd></div>
        <div><dt>Calibration SHA-256</dt><dd className="mono">{binding.calibration_sha256}</dd></div>
        <div><dt>Selected action SHA-256</dt><dd className="mono">{binding.selected_action_sha256}</dd></div>
      </> : null}
    </dl>
    <details><summary>Reported routes and queue upper bounds</summary>
      <pre className="autonomy-evidence">{JSON.stringify({ routes: certificate.routes, q_next_upper_bytes: certificate.envelope.q_next_upper_bytes }, null, 2)}</pre>
    </details>
  </section>;
}
