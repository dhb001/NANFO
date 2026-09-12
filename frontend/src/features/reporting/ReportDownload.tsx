import { useEffect, useRef, useState } from "react";
import { downloadReport } from "./download";
import { ReportRecord } from "@/shared/types/reporting";
import { toErrorMessage } from "@/shared/lib/errors";
import { Button } from "@/shared/ui/Button";

export function ReportDownload({ report }: { report: ReportRecord }) {
  const [verify, setVerify] = useState(true);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);

  async function save(index: number) {
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setPending(true); setMessage("");
    try {
      const result = await downloadReport(report, report.artifacts[index], controller.signal, verify);
      if (controller.signal.aborted) return;
      const url = URL.createObjectURL(result.blob);
      const anchor = document.createElement("a");
      anchor.href = url; anchor.download = result.filename;
      document.body.append(anchor);
      try { anchor.click(); } finally { anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
      setMessage(`${result.size} actual bytes received; ${result.checksumVerified ? "SHA-256 verified" : "checksum not verified in browser"}. Download handed to browser.`);
    } catch (cause) { if (!controller.signal.aborted) setMessage(toErrorMessage(cause)); }
    finally { if (!controller.signal.aborted) setPending(false); }
  }

  return <div>
    <label><input type="checkbox" checked={verify} disabled={pending} onChange={(event) => setVerify(event.target.checked)} /> Verify SHA-256 in browser</label>
    {report.artifacts.map((artifact, index) => <article key={artifact.artifact_id}>
      <strong>{artifact.media_type}</strong><p>{artifact.size_bytes} bytes (server metadata); SHA-256 {artifact.checksum_sha256}</p>
      <Button permission="read:telemetry" disabled={pending} onClick={() => save(index)}>{pending ? "Downloading..." : `Download ${report.format.toUpperCase()}`}</Button>
    </article>)}
    {message ? <p role="status">{message}</p> : null}
  </div>;
}
