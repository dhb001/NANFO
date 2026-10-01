import { useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Panel } from "@/shared/ui/Panel";
import { Button } from "@/shared/ui/Button";
import { toErrorMessage } from "@/shared/lib/errors";
import { formatTimestamp } from "@/shared/lib/format";
import { useOperatorSession } from "./operatorSession";
import { AUTONOMY_FRESH_MS } from "./hooks";
import { getConfiguration, MIN_CONFIDENCE_BOUNDS, operationalBounds, putConfiguration, validTraining } from "./configurationApi";
import type { Configuration, ConfigurationUpdate, OperationalSettings } from "./configurationTypes";

export function ConfigurationPanel({ now }: { now: number }) {
  const session = useOperatorSession();
  const client = useQueryClient();
  const [draft, setDraft] = useState<{ revision: number; operational: OperationalSettings; rewards: string } | null>(null);
  const [reason, setReason] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const saving = useRef(false);
  const queryKey = ["autonomy-operator", ...session.identity, "configuration"];
  const query = useQuery({ queryKey, queryFn: async ({ signal }) => {
    session.assertCurrent();
    const result = await getConfiguration(session.token, session.networkId!, session.workspaceId!, signal);
    const current = client.getQueryData<Configuration>(queryKey);
    if (current && result.revision < current.revision) throw new Error("Older configuration revision received. Refresh before editing.");
    return result;
  }, enabled: session.enabled, retry: false, gcTime: 0, refetchOnWindowFocus: false });
  const fresh = query.isSuccess && !query.isFetching && now - query.dataUpdatedAt < AUTONOMY_FRESH_MS;
  const mutation = useMutation({ mutationFn: (input: ConfigurationUpdate) => {
    session.assertCurrent(true);
    if (!fresh || input.expected_revision !== query.data?.revision) throw new Error("Configuration revision changed. Reload the draft and explicitly resubmit.");
    return putConfiguration(session.token, session.workspaceId!, input);
  }, retry: false, onSuccess: async (result) => {
    session.assertCurrent(); await client.cancelQueries({ queryKey, exact: true }); session.assertCurrent();
    client.setQueryData<Configuration>(queryKey, (current) => current && current.revision > result.revision ? current : result);
  }, onSettled: session.reconcile });
  async function save(event: FormEvent) {
    event.preventDefault(); if (!draft || saving.current) return;
    setNotice(null); saving.current = true;
    try {
      const training = { reward_weights: JSON.parse(draft.rewards) as Record<string, number> };
      if (!validTraining(training)) throw new Error("Reward weights must be a JSON object of up to 32 named finite weights from -100 to 100.");
      await mutation.mutateAsync({ network_id: session.networkId!, expected_revision: draft.revision, reason: reason.trim(), operational: draft.operational, training });
      session.assertCurrent(); setDraft(null); setReason("");
      setNotice("Configuration revision recorded. Operational settings and requested training are separate; running model weights were not changed.");
    } catch (error) { setNotice(`Configuration not confirmed. ${toErrorMessage(error)} No automatic retry. Refresh and reload the draft before explicitly resubmitting.`); }
    finally { saving.current = false; }
  }
  const data = query.data;
  return <Panel title="Versioned operational configuration" subtitle="Immutable revisions; requested rewards never overwrite frozen training">
    <div className="autonomy-stack">
      <Button tone="ghost" disabled={!session.enabled || query.isFetching || mutation.isPending} onClick={() => void query.refetch()}>Refresh configuration</Button>
      {query.isPending && <p role="status">Loading configuration...</p>}
      {query.isError && <p role="alert">Configuration read unavailable. {toErrorMessage(query.error)} Retry with Refresh configuration.</p>}
      {data && !fresh && <p role="status">Configuration is stale or refreshing. Editing requires a fresh read.</p>}
      {data && <>
        <p>Effective operational revision: <strong>{data.revision}</strong>. Control revision: {data.control_revision}. Safety merge: {data.safety_merge}.</p>
        <dl>{Object.entries(data.operational).filter(([key]) => key in operationalBounds).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>)}</dl>
        <p role="note" aria-label="Confidence gate">Confidence gate (C17): autonomous dispatch requires <strong>calibrated</strong> confidence of at least {data.operational.min_confidence}.
          {" "}Uncalibrated confidence: {data.operational.allow_uncalibrated_confidence
            ? data.allow_uncalibrated_confidence_honoured
              ? "allowed by this policy and honoured here (experimental lab only; results are not calibrated evidence)."
              : "allowed by this policy but NOT honoured in this deployment; uncalibrated proposals are still refused."
            : "refused."}</p>
        <p>Requested training: <strong>{data.training_status}</strong>. Effective training: <strong>{data.effective_training_status}</strong>.</p>
        <pre className="autonomy-evidence">{JSON.stringify(data.requested_training, null, 2)}</pre>
        <p>Reward changes require separate retraining and qualification. Effective frozen model reward settings are unavailable, not equal to the requested values. No online learning or autonomy activation.</p>
        <Button tone="ghost" disabled={!session.canWrite || !fresh || mutation.isPending} onClick={() => {
          if (draft && !window.confirm("Discard this local configuration draft and reload the current revision?")) return;
          setDraft({ revision: data.revision, operational: { ...data.operational }, rewards: JSON.stringify(data.requested_training.reward_weights, null, 2) }); setNotice(null);
        }}>{draft ? "Reload configuration draft" : "Edit current revision"}</Button>
      </>}
      {!session.canWrite && <p>Read-only: configuration writes require write:config and execute:rollback.</p>}
      {draft && <form className="autonomy-stack" onSubmit={(event) => void save(event)}>
        <p>Draft expected revision: {draft.revision}. {draft.revision !== data?.revision ? "Revision conflict: reload this draft; no silent rebase." : "Every save records a new immutable revision."}</p>
        <fieldset disabled={!session.canWrite || !fresh || mutation.isPending} className="autonomy-stack"><legend>Bounded operational settings</legend>
          {Object.entries(operationalBounds).map(([key, [min, max]]) => <label key={key}>{key}<input type="number" required min={min} max={max} step={1}
            value={Number.isNaN(draft.operational[key as keyof typeof operationalBounds]) ? "" : draft.operational[key as keyof typeof operationalBounds]}
            onChange={(event) => setDraft({ ...draft, operational: { ...draft.operational, [key]: event.target.valueAsNumber } })} /></label>)}
          <label>min_confidence (calibrated, {MIN_CONFIDENCE_BOUNDS[0]} to {MIN_CONFIDENCE_BOUNDS[1]}; may only be tightened)<input type="number" required
            min={MIN_CONFIDENCE_BOUNDS[0]} max={MIN_CONFIDENCE_BOUNDS[1]} step={0.01}
            value={Number.isNaN(draft.operational.min_confidence) ? "" : draft.operational.min_confidence}
            onChange={(event) => setDraft({ ...draft, operational: { ...draft.operational, min_confidence: event.target.valueAsNumber } })} /></label>
          <label><input type="checkbox" checked={draft.operational.allow_uncalibrated_confidence}
            onChange={(event) => setDraft({ ...draft, operational: { ...draft.operational, allow_uncalibrated_confidence: event.target.checked } })} />
            {" "}Allow uncalibrated confidence (experimental lab only; {data?.allow_uncalibrated_confidence_honoured ? "honoured in this deployment" : "ignored in this deployment"})</label>
          <label>Requested reward weights (JSON)<textarea value={draft.rewards} onChange={(event) => setDraft({ ...draft, rewards: event.target.value })} rows={5} spellCheck={false} /></label>
          <label>Configuration change reason<input required maxLength={1000} value={reason} onChange={(event) => setReason(event.target.value)} /></label>
        </fieldset>
        <Button type="submit" disabled={!session.canWrite || !fresh || mutation.isPending || draft.revision !== data?.revision || !reason.trim()}>Save new configuration revision</Button>
      </form>}
      {notice && <p role="alert">{notice}</p>}
      <h3>Immutable configuration history</h3>
      {!data?.history.length && <p>No configuration revisions recorded. Server defaults remain operational.</p>}
      {data?.history.map((item) => <details key={item.revision}><summary>Revision {item.revision}: {item.reason}</summary>
        <p>{formatTimestamp(item.created_at)} / {item.actor_id}</p><p className="mono">Content SHA-256: {item.content_sha256}</p>
        <pre className="autonomy-evidence">{JSON.stringify({ operational: item.operational, requested_training: item.training }, null, 2)}</pre></details>)}
    </div>
  </Panel>;
}
