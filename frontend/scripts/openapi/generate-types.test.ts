import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { HEADER, firstDifference, readBackendSchema, renderOpenApiTypes } from "./generate-types.ts";

const schema = {
  openapi: "3.1.0",
  info: { title: "t", version: "1" },
  paths: {},
  components: { schemas: { Pair: { type: "object", required: ["token_type"], properties: { token_type: { type: "string" } } } } },
};

describe("OpenAPI type generation (ADR-028 item 7)", () => {
  const dirs: string[] = [];
  afterEach(() => { for (const dir of dirs.splice(0)) rmSync(dir, { recursive: true, force: true }); });

  it("renders deterministic generated types with the do-not-edit header", async () => {
    const first = await renderOpenApiTypes(schema);
    expect(first.startsWith(HEADER)).toBe(true);
    expect(first).toContain("Pair: {");
    expect(first).toContain("token_type: string;");
    expect(first.endsWith("\n")).toBe(true);
    expect(await renderOpenApiTypes(structuredClone(schema))).toBe(first);
  });

  it("rejects documents that are not OpenAPI", async () => {
    await expect(renderOpenApiTypes({ swagger: "2.0" })).rejects.toThrow("Not an OpenAPI document");
    await expect(renderOpenApiTypes(null)).rejects.toThrow("Not an OpenAPI document");
  });

  it("reports the first drifting line for api:check", () => {
    expect(firstDifference("a\nb\nc", "a\nb\nc")).toBeNull();
    expect(firstDifference("a\nb\nc", "a\nX\nc")).toEqual({ line: 2, existing: "b", next: "X" });
    expect(firstDifference("a", "a\nnew")).toEqual({ line: 2, existing: "<eof>", next: "new" });
  });

  it("reads a pre-exported schema from NANFO_OPENAPI_SCHEMA without running the backend", () => {
    const dir = mkdtempSync(path.join(tmpdir(), "nanfo-openapi-"));
    dirs.push(dir);
    const file = path.join(dir, "openapi.json");
    writeFileSync(file, JSON.stringify(schema));
    expect(readBackendSchema({ NANFO_OPENAPI_SCHEMA: file })).toEqual(schema);
  });
});
