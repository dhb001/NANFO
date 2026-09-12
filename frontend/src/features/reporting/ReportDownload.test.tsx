import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { ReportDownload } from "./ReportDownload";
import { ReportRecord } from "@/shared/types/reporting";
import { useAuthStore } from "@/shared/state/auth-store";
import { operatorProfile } from "@/test/profile";

const download = vi.hoisted(() => vi.fn());
vi.mock("./download", () => ({ downloadReport: download }));
const report = { report_id: "r1", format: "csv", artifacts: [{ artifact_id: "a1", media_type: "text/csv", size_bytes: 3, checksum_sha256: "serverhash" }] } as ReportRecord;
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("hands a verified Blob to the browser and revokes its object URL", async () => {
  useAuthStore.setState({ profile: operatorProfile });
  const revoke = vi.fn(), create = vi.fn(() => "blob:fixture");
  vi.stubGlobal("URL", { createObjectURL: create, revokeObjectURL: revoke });
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  download.mockResolvedValue({ blob: new Blob(["abc"]), filename: "report.csv", size: 3, checksumVerified: true });
  render(<ReportDownload report={report} />);
  await userEvent.click(screen.getByRole("button", { name: "Download CSV" }));
  expect(click).toHaveBeenCalledOnce();
  expect(screen.getByRole("status")).toHaveTextContent("3 actual bytes received; SHA-256 verified");
  expect(document.querySelector("a[download]")).toBeNull();
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 1050)); });
  expect(revoke).toHaveBeenCalledWith("blob:fixture");
});

it("aborts on unmount and never creates a URL for a late completion", async () => {
  useAuthStore.setState({ profile: operatorProfile });
  const create = vi.fn(); vi.stubGlobal("URL", { createObjectURL: create });
  let finish!: (value: unknown) => void;
  download.mockReturnValue(new Promise((resolve) => { finish = resolve; }));
  const view = render(<ReportDownload report={report} />);
  await userEvent.click(screen.getByRole("button", { name: "Download CSV" }));
  const signal = download.mock.calls.at(-1)![2] as AbortSignal;
  view.unmount();
  expect(signal.aborted).toBe(true);
  await act(async () => finish({ blob: new Blob(["abc"]), filename: "report.csv", size: 3 }));
  expect(create).not.toHaveBeenCalled();
});
