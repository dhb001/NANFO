import { useMutation, useQuery } from "@tanstack/react-query";
import { getProfile, login, logout, refresh } from "@/features/auth/api";

export function useLogin() {
  return useMutation({
    mutationFn: login,
  });
}

export function useLogout() {
  return useMutation({
    mutationFn: logout,
  });
}

export function useRefreshToken() {
  return useMutation({
    mutationFn: refresh,
  });
}

export function useProfile(token: string | null) {
  return useQuery({
    queryKey: ["auth", "me", token],
    queryFn: () => getProfile(token as string),
    enabled: Boolean(token),
  });
}
