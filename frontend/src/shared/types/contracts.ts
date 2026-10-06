import type { components } from "@/shared/types/generated/openapi";

/** Backend response/request schemas generated from FastAPI (`npm run api:types`). */
export type Schemas = components["schemas"];
export type Schema<Name extends keyof Schemas> = Schemas[Name];

/**
 * Compile-time contract check (ADR-028 item 7/14): `true` when the hand-written
 * type declares no field the backend schema lacks (invented fields fail the
 * typecheck with their names), otherwise a readable error tuple.
 */
export type NoInventedFields<Hand, Generated> =
  [Exclude<keyof Hand, keyof Generated>] extends [never] ? true : ["Fields missing from the backend schema:", Exclude<keyof Hand, keyof Generated>];

/** `true` when every backend value satisfies the hand-written type (no required field the backend omits, compatible types). */
export type AcceptsBackend<Hand, Generated> = [Generated] extends [Hand] ? true : ["Backend schema is not assignable to the hand-written type"];

export type AssertContract<Check extends true> = Check;
