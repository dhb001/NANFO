import { describe, expect, it } from "vitest";
import { registrationTransform, validateRegistration } from "./modelRegistration";

export const savedRegistration = { version: 1 as const, translation: { x: 12, y: -3, z: 5 }, rotation: { x: 0.2, y: 1.3, z: -0.5 }, scale: { x: 0.01, y: 0.02, z: 0.03 }, target_units: "m" as const, target_up_axis: "y" as const, source: "operator-survey" };
describe("asset registration", () => {
  it("retains exact nonuniform transforms and does not register legacy assets", () => {
    expect(validateRegistration(undefined)).toBeNull(); expect(validateRegistration(null)).toBeNull();
    expect(validateRegistration(savedRegistration)).toEqual(savedRegistration);
    expect(registrationTransform(savedRegistration)).toEqual({ position: [12, -3, 5], rotation: [0.2, 1.3, -0.5], scale: [0.01, 0.02, 0.03] });
  });
  it("rejects malformed, unbounded, extra-field or incompatible registration", () => {
    for (const change of [{ version: true }, { source: "" }, { target_up_axis: "z" }, { extra: 1 },
      { scale: { x: 0, y: 1, z: 1 } }, { rotation: { x: 7, y: 0, z: 0 } }, { translation: { x: Infinity, y: 0, z: 0 } },
      { translation: { x: "1", y: 0, z: 0 } }, { scale: { x: 1, y: 1, z: 1, w: 1 } }]) expect(() => validateRegistration({ ...savedRegistration, ...change })).toThrow();
  });
});
