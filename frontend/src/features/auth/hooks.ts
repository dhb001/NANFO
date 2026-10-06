import { useMutation } from "@tanstack/react-query";
import { login } from "@/features/auth/api";

// Refresh, logout and profile reads go through features/auth/session.ts only:
// separate mutations would bypass its single-flight rotation and revocation.
export function useLogin() {
  return useMutation({
    mutationFn: login,
  });
}
