import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useExitPresence } from "./useExitPresence";
import { ToastCenter } from "./ToastCenter";
import { useUiStore } from "@/shared/state/ui-store";

describe("CSS animation presence", () => {
  beforeEach(() => { vi.useFakeTimers(); useUiStore.setState({ toasts: [] }); });
  afterEach(() => vi.useRealTimers());

  it("retains exit content for 200ms and cancels removal when reopened", () => {
    const { result, rerender, unmount } = renderHook(({ open }) => useExitPresence(open), { initialProps: { open: true } });
    rerender({ open: false });
    expect(result.current).toBe(true);
    act(() => vi.advanceTimersByTime(100));
    rerender({ open: true });
    act(() => vi.advanceTimersByTime(200));
    expect(result.current).toBe(true);
    rerender({ open: false });
    act(() => vi.advanceTimersByTime(200));
    expect(result.current).toBe(false);
    rerender({ open: true });
    rerender({ open: false });
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("preserves toast entry/exit while making dismissed content noninteractive", () => {
    useUiStore.setState({ toasts: [{ id: "one", title: "Request accepted", tone: "info" }] });
    const { unmount } = render(<ToastCenter />);
    const toast = screen.getByRole("button", { name: "Request accepted" });
    expect(toast).toHaveClass("toast-presence");
    expect(toast).toHaveAttribute("data-open", "true");
    fireEvent.click(toast);
    expect(toast).toHaveAttribute("data-open", "false");
    expect(toast).toHaveAttribute("aria-hidden", "true");
    expect(toast).toBeDisabled();
    act(() => useUiStore.getState().pushToast({ title: "Another request", tone: "info" }));
    expect(screen.getByRole("button", { name: "Another request" })).toBeEnabled();
    act(() => vi.advanceTimersByTime(200));
    expect(screen.queryByText("Request accepted")).not.toBeInTheDocument();
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});
