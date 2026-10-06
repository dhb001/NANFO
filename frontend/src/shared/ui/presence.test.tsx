import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useExitPresence } from "./useExitPresence";
import { ToastCenter, TOAST_AUTO_DISMISS_MS } from "./ToastCenter";
import { useUiStore } from "@/shared/state/ui-store";

describe("CSS animation presence", () => {
  beforeEach(() => { vi.useFakeTimers(); useUiStore.setState({ toasts: [] }); });
  afterEach(() => vi.useRealTimers());

  it("retains exit content for 200ms and cancels removal when reopened", () => {
    const { result, rerender, unmount } = renderHook(({ open }) => useExitPresence(open), { initialProps: { open: true } });
    rerender({ open: false });
    expect(result.current).toBe(true);
    act(() => { vi.advanceTimersByTime(100); });
    rerender({ open: true });
    act(() => { vi.advanceTimersByTime(200); });
    expect(result.current).toBe(true);
    rerender({ open: false });
    act(() => { vi.advanceTimersByTime(200); });
    expect(result.current).toBe(false);
    rerender({ open: true });
    rerender({ open: false });
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("preserves toast entry/exit while making dismissed content noninteractive", () => {
    useUiStore.setState({ toasts: [{ id: "one", title: "Request accepted", tone: "info" }] });
    const { unmount } = render(<ToastCenter />);
    const dismiss = screen.getByRole("button", { name: "Dismiss Request accepted" });
    const toast = dismiss.parentElement!;
    expect(toast).toHaveClass("toast-presence");
    expect(toast).toHaveAttribute("data-open", "true");
    fireEvent.click(dismiss);
    expect(toast).toHaveAttribute("data-open", "false");
    expect(toast).toHaveAttribute("aria-hidden", "true");
    expect(dismiss).toBeDisabled();
    act(() => useUiStore.getState().pushToast({ title: "Another request", tone: "info" }));
    expect(screen.getByRole("button", { name: "Dismiss Another request" })).toBeEnabled();
    act(() => { vi.advanceTimersByTime(200); });
    expect(screen.queryByText("Request accepted")).not.toBeInTheDocument();
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("caps toasts, keeps errors longest, and announces tone in text and role (ADR-028)", () => {
    const push = useUiStore.getState().pushToast;
    push({ title: "Failure 1", tone: "danger" });
    for (let index = 1; index <= 6; index++) push({ title: `Notice ${index}`, tone: "info" });
    const titles = useUiStore.getState().toasts.map((toast) => toast.title);
    expect(titles).toEqual(["Failure 1", "Notice 3", "Notice 4", "Notice 5", "Notice 6"]);
    const { unmount } = render(<ToastCenter />);
    expect(screen.getByRole("alert")).toHaveTextContent("Error: Failure 1");
    expect(screen.getByRole("alert")).toHaveClass("toast--danger");
    expect(screen.getAllByRole("status")).toHaveLength(4);
    expect(screen.getByText("Notice 6").parentElement).toHaveTextContent("Notice: Notice 6");
    unmount();
  });

  it("auto-dismisses non-danger toasts, pauses while hovered, and keeps errors until dismissed", () => {
    useUiStore.setState({ toasts: [
      { id: "e", title: "Execution failed", tone: "danger" },
      { id: "i", title: "Saved", tone: "ok" },
    ] });
    const { container, unmount } = render(<ToastCenter />);
    const center = container.querySelector(".toast-center")!;
    act(() => { vi.advanceTimersByTime(3_000); });
    fireEvent.mouseEnter(center);
    act(() => { vi.advanceTimersByTime(10_000); });
    expect(useUiStore.getState().toasts.map((toast) => toast.id)).toEqual(["e", "i"]);
    fireEvent.mouseLeave(center);
    act(() => { vi.advanceTimersByTime(TOAST_AUTO_DISMISS_MS - 1); });
    expect(useUiStore.getState().toasts.map((toast) => toast.id)).toEqual(["e", "i"]);
    act(() => { vi.advanceTimersByTime(1); });
    expect(useUiStore.getState().toasts.map((toast) => toast.id)).toEqual(["e"]);
    act(() => { vi.advanceTimersByTime(60_000); });
    expect(useUiStore.getState().toasts.map((toast) => toast.id)).toEqual(["e"]);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});
