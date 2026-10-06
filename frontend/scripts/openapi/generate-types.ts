// OpenAPI -> TypeScript contract types (ADR-028 FE-Platform item 7).
//
//   npm run api:types   regenerate src/shared/types/generated/openapi.ts
//   npm run api:check   fail (exit 1) when the committed file drifts from the backend
//
// The schema comes from the backend application itself:
//   cd ../backend && APP_ENV=test poetry run python -c "import json; from app.main import app; print(json.dumps(app.openapi()))"
// Set NANFO_OPENAPI_SCHEMA=/path/to/openapi.json to use a pre-exported schema instead
// (for example in a CI job without Poetry).
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import openapiTS, { astToString } from "openapi-typescript";

const FRONTEND_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const BACKEND_ROOT = path.resolve(FRONTEND_ROOT, "../backend");
export const OUTPUT_FILE = path.join(FRONTEND_ROOT, "src/shared/types/generated/openapi.ts");
const EXPORT_SCHEMA = "import json; from app.main import app; print(json.dumps(app.openapi()))";

export const HEADER = [
  "/**",
  " * GENERATED FILE - do not edit.",
  " * Source: backend FastAPI schema (app.main:app.openapi(), APP_ENV=test) via openapi-typescript.",
  " * Regenerate with `npm run api:types`; `npm run api:check` fails when it drifts from the backend.",
  " */",
  "",
].join("\n");

export function readBackendSchema(env: NodeJS.ProcessEnv = process.env): unknown {
  const override = env.NANFO_OPENAPI_SCHEMA;
  if (override) return JSON.parse(readFileSync(override, "utf8"));
  if (!existsSync(path.join(BACKEND_ROOT, "pyproject.toml"))) throw new Error(`Backend not found at ${BACKEND_ROOT}`);
  const result = spawnSync("poetry", ["run", "python", "-c", EXPORT_SCHEMA], {
    cwd: BACKEND_ROOT,
    env: { ...env, APP_ENV: "test" },
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    // stderr may contain local paths only (settings never print secrets); keep it short.
    throw new Error(`Backend schema export failed (exit ${result.status}): ${result.stderr.split("\n").filter(Boolean).slice(-3).join(" | ")}`);
  }
  return JSON.parse(result.stdout);
}

export async function renderOpenApiTypes(schema: unknown): Promise<string> {
  if (!schema || typeof schema !== "object" || !("openapi" in schema)) throw new Error("Not an OpenAPI document");
  const ast = await openapiTS(schema as Parameters<typeof openapiTS>[0]);
  return `${HEADER}${astToString(ast).trimEnd()}\n`;
}

/** First differing line (1-based) or null when identical. */
export function firstDifference(existing: string, next: string): { line: number; existing: string; next: string } | null {
  if (existing === next) return null;
  const left = existing.split("\n");
  const right = next.split("\n");
  for (let index = 0; index < Math.max(left.length, right.length); index++) {
    if (left[index] !== right[index]) return { line: index + 1, existing: left[index] ?? "<eof>", next: right[index] ?? "<eof>" };
  }
  return { line: left.length, existing: "", next: "" };
}

export async function main(argv = process.argv.slice(2)): Promise<number> {
  const check = argv.includes("--check");
  const generated = await renderOpenApiTypes(readBackendSchema());
  if (check) {
    const existing = existsSync(OUTPUT_FILE) ? readFileSync(OUTPUT_FILE, "utf8") : "";
    const difference = firstDifference(existing, generated);
    if (difference) {
      console.error(`OpenAPI types drifted from the backend at ${path.relative(FRONTEND_ROOT, OUTPUT_FILE)}:${difference.line}`);
      console.error(`  committed: ${difference.existing.trim().slice(0, 160)}`);
      console.error(`  backend:   ${difference.next.trim().slice(0, 160)}`);
      console.error("Run `npm run api:types`, review the contract change and commit the result.");
      return 1;
    }
    console.log("OpenAPI types match the backend schema.");
    return 0;
  }
  mkdirSync(path.dirname(OUTPUT_FILE), { recursive: true });
  writeFileSync(OUTPUT_FILE, generated);
  console.log(`Wrote ${path.relative(FRONTEND_ROOT, OUTPUT_FILE)} (${generated.length} bytes).`);
  return 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().then((code) => { process.exitCode = code; }, (error: unknown) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  });
}
