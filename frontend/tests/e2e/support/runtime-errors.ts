import { expect, test, type BrowserContext } from "@playwright/test";

const runtimeErrors = new WeakMap<BrowserContext, string[]>();

// Imported once by shared session support: includes navigations, reloads, popups,
// and independent tabs. Expected API denials remain handled application states.
test.beforeEach(async ({ context }) => {
  const errors: string[] = [];
  runtimeErrors.set(context, errors);
  context.on("weberror", (event) => errors.push(`pageerror: ${event.error().message}`));
  await context.exposeBinding("__nanfoReportUnhandledRejection", (_source, message: string) => {
    errors.push(`unhandledrejection: ${message}`);
  });
  await context.addInitScript(() => {
    window.addEventListener("unhandledrejection", (event) => {
      const reason: unknown = event.reason;
      const message = reason instanceof Error ? `${reason.name}: ${reason.message}` : String(reason);
      const report = (window as unknown as { __nanfoReportUnhandledRejection: (message: string) => Promise<void> }).__nanfoReportUnhandledRejection;
      void report(message);
    });
  });
});

test.afterEach(async ({ context }) => {
  expect(runtimeErrors.get(context) ?? [], "No uncaught browser errors or unhandled promise rejections").toEqual([]);
});
