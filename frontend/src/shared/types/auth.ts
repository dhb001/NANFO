import type { Schema } from "@/shared/types/contracts";

/** `POST /auth/login` and `/auth/refresh` token pair (generated backend schema). */
export type TokenPair = Schema<"TokenPair">;

/** `GET /auth/me` (generated backend schema). */
export type UserProfile = Schema<"UserProfile">;

/** `POST /auth/login` body (generated backend schema). */
export type LoginRequest = Schema<"LoginRequest">;

/** `POST /auth/refresh` body (generated backend schema). */
export type RefreshRequest = Schema<"RefreshRequest">;
