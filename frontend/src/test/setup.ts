import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  // Node-environment tests (build/config checks) have no DOM.
  if (typeof window === "undefined") return;
  cleanup();
  window.localStorage.clear();
  window.sessionStorage.clear();
});
