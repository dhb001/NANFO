import { webcrypto } from "node:crypto";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { RFImportPanel } from "./RFImportPanel";
import { rfFixture, rfFixtureScene } from "./rfFixture.test-data";

describe("RF operator import", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("validates real artifact import, shows modeled values/provenance, hides samples when snapshot changes", async () => {
    vi.stubGlobal("crypto", webcrypto);
    const onChange = vi.fn();
    const props = { scene: rfFixtureScene, workspaceId: "workspace-1", networkId: "network-1", value: null, onChange };
    const view = render(<RFImportPanel {...props} />);
    expect(screen.getByLabelText("Backend spatial-rf artifacts")).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Expected RF coordinate frame ID"), { target: { value: "rf-z-up" } });
    const file = new File([""], "rf.json"); Object.defineProperty(file, "text", { value: async () => JSON.stringify(rfFixture) });
    fireEvent.change(screen.getByLabelText("Backend spatial-rf artifacts"), { target: { files: [file] } });
    await screen.findByText("Imported 1 RF samples; alignment verified.");
    const value = onChange.mock.calls[0][0];
    view.rerender(<RFImportPanel {...props} value={value} />);
    expect(screen.getByText(/rx-1: -49.1 dBm/)).toHaveTextContent("uncertainty unknown");
    expect(screen.getByText(/Network XYZ meters/)).toHaveTextContent("9, 4, 8");
    fireEvent.change(screen.getByLabelText("Backend spatial-rf artifacts"), { target: { files: [file] } });
    await screen.findByText("Duplicate receiver or mixed RF configuration.");
    expect(onChange).toHaveBeenCalledTimes(1);
    view.rerender(<RFImportPanel {...props} scene={{ ...rfFixtureScene, revision: 5 }} value={value} />);
    expect(screen.getByRole("alert")).toHaveTextContent("RF hidden");
    expect(screen.queryByText(/rx-1: -49.1 dBm/)).not.toBeInTheDocument();
  });
});
