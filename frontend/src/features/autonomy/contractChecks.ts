export const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every((item) => typeof item === "string");
export const hash = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
export const uuid = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(value);
export const registryId = (value: unknown): value is string => typeof value === "string" && /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$/.test(value);
export const timestamp = (value: unknown): value is string => typeof value === "string" && Number.isFinite(Date.parse(value));
export const finite = (value: unknown, min: number, max: number): value is number => typeof value === "number" && Number.isFinite(value) && value >= min && value <= max;
export const revision = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) >= 0;
