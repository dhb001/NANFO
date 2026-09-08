import type { UserProfile } from "@/shared/types/auth";

export const operatorProfile: UserProfile = {
  user_id: "00000000-0000-0000-0000-000000000123",
  email: "operator@example.com",
  display_name: "Test operator",
  roles: ["Operator"],
  permissions: ["read:topology", "read:telemetry", "write:config"],
};
