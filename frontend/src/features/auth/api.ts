import { apiRequest } from "@/shared/lib/api";
import { AccessToken, LoginRequest, TokenPair, UserProfile } from "@/shared/types/auth";

export async function login(request: LoginRequest) {
  const response = await apiRequest<TokenPair>("/api/v1/auth/login", {
    method: "POST",
    body: request,
  });
  return response.data;
}

export async function refresh(refreshToken: string) {
  const response = await apiRequest<AccessToken>("/api/v1/auth/refresh", {
    method: "POST",
    body: { refresh_token: refreshToken },
  });
  return response.data;
}

export async function getProfile(token: string) {
  const response = await apiRequest<UserProfile>("/api/v1/auth/me", {
    token,
  });
  return response.data;
}

export async function logout(token: string) {
  const response = await apiRequest<{ logged_out: boolean }>("/api/v1/auth/logout", {
    method: "POST",
    token,
  });
  return response.data;
}
