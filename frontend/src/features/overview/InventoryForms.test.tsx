import { describe, expect, it } from "vitest";
import { changedDeviceFields, changedNetworkFields } from "./inventory-logic";
import { isAmbiguousMutation } from "@/features/organizations/tenancy-logic";
import { ApiClientError } from "@/shared/lib/errors";
import type { Device, Network } from "@/shared/types/network";

describe("inventory mutation contracts", () => {
  it("sends changed fields only, including explicit nullable clearing", () => {
    const device = { hostname: "router", device_type: "router", ip_address: "192.0.2.1", spatial_ref_id: "office" } as Device;
    expect(changedDeviceFields(device, { hostname: "router", device_type: "router", ip_address: null, spatial_ref_id: "office" })).toEqual({ ip_address: null });
    expect(changedNetworkFields({ name: "LAN", description: "old", cidr: null } as Network, { name: "LAN", description: null, cidr: null })).toEqual({ description: null });
  });
  it("distinguishes rejected writes from transport/server/invalid success ambiguity", () => {
    for (const status of [403, 409, 422]) expect(isAmbiguousMutation(new ApiClientError("denied", "DENIED", status))).toBe(false);
    for (const error of [new TypeError("offline"), new SyntaxError("invalid JSON"), new ApiClientError("failed", "HTTP_503", 503), new ApiClientError("stale", "API_STALE_CONTEXT", 201)]) expect(isAmbiguousMutation(error)).toBe(true);
  });
});
